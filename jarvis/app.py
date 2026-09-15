import asyncio
import contextlib
import logging
import os
from collections.abc import Callable

import aiohttp

from .chrome_consent import ChromeConsentClicker
from .confirm import ConfirmationBroker
from .ears import Ears, WakeWordDetector
from .events import EventHub
from .jobs import JobEvent, JobManager
from .notifier import Notifier
from .panel import PanelServer, open_panel
from .projects import ProjectResolver, load_aliases
from .reporter import Reporter
from .scheduler import Scheduler
from .spend import SpendCache
from .store import Routine, Store
from .voice import JarvisTools, VoiceController
from .worker import ClaudeWorker

log = logging.getLogger("jarvis.app")

MIC_CHECK_DELAY_S = 5.0
MIC_SILENT_PEAK = 30
MIC_METER_INTERVAL_S = 0.1
# how long the microphone may stay flat during a conversation before Jarvis moves to another one
DEAF_AFTER_S = 6.0
DEAF_LEVEL = 30


class JarvisApp:
    def __init__(self, settings, audio_factory, *, on_state: Callable[[str], None] = lambda s: None,
                 use_ears: bool = True, open_on_start: bool = False, worker_model: str | None = None,
                 browser: bool = True, prewarm: bool = True, panel: bool = True, routines: bool = True):
        self.settings = settings
        self.audio_factory = audio_factory
        self.on_state = on_state
        self.use_ears = use_ears
        self.open_on_start = open_on_start
        self.worker_model = worker_model
        self.browser = browser
        self.prewarm = prewarm
        self.panel_enabled = panel
        self.routines_enabled = routines
        self.hub = EventHub()
        self.spend = SpendCache(getattr(settings, "openai_admin_key", None))
        self.state = "starting"
        self.chrome_consent = ChromeConsentClicker()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.store: Store | None = None
        self.audio = None
        self.broker: ConfirmationBroker | None = None
        self.jobs: JobManager | None = None
        self.voice: VoiceController | None = None
        self.notifier: Notifier | None = None
        self.panel: PanelServer | None = None
        self.scheduler: Scheduler | None = None
        self.resolver: ProjectResolver | None = None
        self.started = asyncio.Event()

    def publish_state(self, value: str) -> None:
        """Single place where a state change reaches the menu bar and the panel."""
        self.state = value
        self.hub.publish("state", value=value)
        self.on_state(value)

    def wake(self) -> None:
        """Thread-safe: open the voice session."""
        if self.loop is not None and self.voice is not None:
            self.loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self._safe_open()))

    async def _safe_open(self) -> None:
        """Open for the user (wake word, hotkey, Talk) and greet them; background reports open without a greeting."""
        try:
            if self.voice.is_open:
                return
            await self.voice.open()
            await self.voice.greet()
        except Exception as e:
            log.exception("could not open the voice session")
            self.publish_state("error")
            await self._explain_failure(e)

    async def _explain_failure(self, error: Exception) -> None:
        """Never fail silently. Chiming and then saying nothing is indistinguishable from being broken."""
        text = str(error).lower()
        if "no credits" in text or "insufficient_quota" in text or "429" in text:
            reason = ("OpenAI has no credits left, so Jarvis cannot speak. "
                      "Add credit at platform.openai.com to bring the voice back.")
        elif "invalid_api_key" in text or "401" in text:
            reason = "The OpenAI key was rejected. Check OPENAI_API_KEY in ~/.jarvis/.env."
        elif "timed out" in text or "timeout" in text:
            reason = "OpenAI did not answer in time. Jarvis will work again when the connection recovers."
        else:
            reason = f"Jarvis could not start a conversation: {type(error).__name__}."
        log.error("voice unavailable: %s", reason)
        self.hub.publish("notice", text=reason)
        if self.notifier is not None:
            with contextlib.suppress(Exception):
                await self.notifier.desktop("Jarvis can't talk", reason)
                if self.voice is not None and self.voice.is_away():
                    await self.notifier.telegram(f"⚠️ {reason}")

    def active_jobs(self) -> int:
        return len(self.store.active_jobs()) if self.store else 0

    def is_quiet(self) -> bool:
        return (self.voice is not None and self.active_jobs() == 0 and not self.voice.is_open
                and not self.voice.is_saying)

    def _make_worker(self, project):
        return ClaudeWorker(project, self.store, self.broker.confirm, model=self.worker_model,
                            browser=self.browser, hook_timeout_s=self.settings.confirm_timeout_s + 30,
                            on_browser_tool=self.chrome_consent.arm)

    def _submit_routine(self, routine: Routine) -> None:
        """A routine came due: run it as an ordinary Claude job, so it reports back by voice like anything else."""
        project = self.resolver.resolve(routine.project)
        if project is None:
            log.warning("routine %r names an unknown project %r; running it in home", routine.name, routine.project)
            project = self.resolver.resolve(None)
        self.jobs.submit(project, routine.task)

    async def _on_job_event(self, ev: JobEvent, speak) -> None:
        self.hub.publish("job", id=ev.job_id, project=ev.project, stage=ev.kind, text=ev.text)
        await speak(ev)

    async def _check_microphone(self, notifier: Notifier, tries: int = 3) -> None:
        # A Bluetooth mic alternates between working and silent, so one sample is a coin flip: take several.
        # Always log the peak, pass or fail — a silent success made this impossible to diagnose.
        peak = 0
        for attempt in range(tries):
            await asyncio.sleep(MIC_CHECK_DELAY_S if attempt == 0 else 2.0)
            if self.audio is None:
                return
            self.audio.input_peak = 0
            await asyncio.sleep(1.0)
            peak = int(getattr(self.audio, "input_peak", 0) or 0)
            log.info("microphone check %d/%d on %s: peak %s",
                     attempt + 1, tries, getattr(self.audio, "input_device", "?"), peak)
            if peak >= MIC_SILENT_PEAK:
                return
        from .audio import next_input_device

        log.warning("microphone looks silent (peak %s)", peak)
        # don't just warn and sit deaf: move to another input now, before the user says "Hey Jarvis"
        target = next_input_device(getattr(self.audio, "input_device", None))
        if target is not None:
            try:
                name = self.audio.switch_input(target)
                log.info("startup: switched away from the silent microphone to %s", name)
                self.hub.publish("notice", text=f"microphone was silent; switched to {name}")
                return
            except Exception:
                log.exception("could not switch away from the silent microphone")
        self.publish_state("error")
        await notifier.desktop("Jarvis can't hear you",
                               "No microphone audio. Allow Jarvis in System Settings > Privacy & Security > "
                               "Microphone, or set JARVIS_INPUT_DEVICE.")

    def notify_deaf(self, name: str) -> None:
        """Say it out loud: going deaf silently is the failure that actually costs the user time."""
        self.hub.publish("notice", text=f"microphone went silent; switched to {name}")
        if self.voice is not None:
            asyncio.ensure_future(self.voice.say(
                f"Speak in {self.voice.language}. Tell the user in one short sentence that the microphone went "
                f"silent and you switched to {name}."))

    async def _deaf_watchdog(self, interval_s: float = 1.0, deaf_after_s: float = DEAF_AFTER_S,
                             pick_next=None) -> None:
        """Move off a microphone that stops delivering audio during a conversation.

        Bluetooth earbuds idle in music mode and hand back pure silence, so Jarvis can sit deaf without noticing.
        It switches at most once per deaf spell: reopening a Bluetooth device repeatedly is what kills it.
        """
        from .audio import next_input_device

        silent_for = 0.0
        switched = False
        while True:
            await asyncio.sleep(interval_s)
            open_session = self.voice is not None and self.voice.is_open
            if not open_session or self.audio is None:
                silent_for, switched = 0.0, False
                continue
            if int(getattr(self.audio, "input_level", 0)) > DEAF_LEVEL:
                silent_for, switched = 0.0, False
                continue
            silent_for += interval_s
            if silent_for < deaf_after_s or switched:
                continue
            chooser = pick_next or (lambda current: next_input_device(current))
            target = chooser(getattr(self.audio, "input_device", None))
            if target is None:
                log.warning("microphone is silent and there is nowhere else to switch")
                switched = True
                continue
            try:
                name = self.audio.switch_input(target)
            except Exception:
                log.exception("could not switch microphone")
                switched = True
                continue
            switched = True
            silent_for = 0.0
            self.notify_deaf(name if isinstance(name, str) else str(target))

    async def _mic_meter(self) -> None:
        """Feed the panel live microphone and speaker levels while a conversation is open."""
        while True:
            await asyncio.sleep(MIC_METER_INTERVAL_S)
            if self.voice is not None and self.voice.is_open:
                self.hub.publish("level",
                                 mic=int(getattr(self.audio, "input_level", 0)),
                                 out=int(getattr(self.audio, "output_level", 0)))

    async def run(self, stop: asyncio.Event) -> None:
        s = self.settings
        self.loop = asyncio.get_running_loop()
        self.store = store = Store(s.db_path)
        if stale := store.fail_stale_jobs():
            log.info("marked %d stale jobs as failed", stale)
        self.resolver = resolver = ProjectResolver(s.projects_root, load_aliases(s.home / "projects.json"))
        async with aiohttp.ClientSession() as http:
            self.audio = audio = self.audio_factory(self.loop)
            self.broker = ConfirmationBroker(ask=lambda summary: self.voice.ask_confirmation(summary),
                                             timeout_s=s.confirm_timeout_s)
            self.notifier = notifier = Notifier(http, s.telegram_bot_token, s.telegram_chat_id)
            reporter = Reporter(speak=lambda text: self.voice.announce(text), notifier=notifier,
                                is_away=lambda: self.voice.is_away())
            self.jobs = jobs = JobManager(store, self._make_worker,
                                          lambda ev: self._on_job_event(ev, reporter.on_event))
            self.scheduler = Scheduler(store, self._submit_routine, hub=self.hub)
            tools = JarvisTools(jobs, resolver, store, broker=self.broker, home=s.home,
                                scheduler=self.scheduler)
            self.voice = VoiceController(s, audio, tools, resolver, store, self.broker, http,
                                         on_state=self.publish_state, hub=self.hub)
            ears = None
            background: list[asyncio.Task[None]] = []
            audio.start()
            if self.panel_enabled:
                self.panel = PanelServer(self.hub, store, lambda: self.state, spend=self.spend, home=s.home)
                if not await self.panel.start():
                    self.panel = None
                elif os.environ.get("JARVIS_PANEL_AUTOOPEN", "1") != "0":
                    open_panel(self.panel.url)
            try:
                if self.use_ears:
                    ears = Ears(audio.wake_queue, WakeWordDetector(s.wake_threshold), on_wake=self.wake,
                                hotkey=s.hotkey)
                    ears.start()
                    background.append(asyncio.create_task(self._check_microphone(notifier)))
                background.append(asyncio.create_task(self._mic_meter()))
                background.append(asyncio.create_task(self._deaf_watchdog()))
                if self.routines_enabled:
                    background.append(asyncio.create_task(self.scheduler.loop(stop)))
                if self.prewarm:
                    background.append(asyncio.create_task(jobs.prewarm(resolver.resolve(None))))
                self.publish_state("idle")
                self.started.set()
                if self.open_on_start:
                    await self._safe_open()
                await stop.wait()
            finally:
                for task in background:
                    if not task.done():
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                if ears is not None:
                    ears.stop()
                if self.panel is not None:
                    await self.panel.stop()
                await self.voice.close()
                await jobs.shutdown()
                self.chrome_consent.stop()
                audio.stop()
