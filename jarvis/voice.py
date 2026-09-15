import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path

import aiohttp
from livekit.agents import Agent, AgentSession, RunContext, llm
from livekit.agents.llm import function_tool
from livekit.plugins.google.realtime import RealtimeModel as GeminiRealtimeModel
from livekit.plugins.openai.realtime import GPTLiveModel

from .commitments import add_commitment, complete_commitment, open_commitments
from .profile import profile_block, remember_fact
from .schedule import ScheduleError
from .speech_text import detect_language, is_goodbye

log = logging.getLogger("jarvis.voice")

INSTRUCTIONS = """You are Jarvis, the user's personal assistant living on their Mac, in the spirit of Tony Stark's
J.A.R.V.I.S.: polished, loyal, calm, quietly witty, and always at the user's service. Speak like a trusted executive
assistant: courteous and confident, brief, never robotic. Don't use gendered forms of address such as "sir" or "madam".
When reporting results, lead with the outcome in one sentence, then offer the obvious next step if there is one.

Language — this rule outranks everything else here, including the language these instructions are written in:
speak {language} by default: every greeting, every answer, every "working on it", and every report. The only
exception: when the user's own most recent sentence is in another language, answer in that language until they go
back to {language}. Older messages and the language of your notes about the user must never pull you out of
{language}. Never switch language on your own. Keep replies to one or two short sentences. Never read code, file
paths, or URLs aloud.

Answer general questions yourself, in one or two sentences: facts, explanations, definitions, translations, simple
arithmetic, advice. Never say you can't help with a question.

Call ask_claude when the answer needs something only the computer can reach — live data (weather, news, prices,
sports), the user's own data (email, calendar, files, projects, browser), or any action. Claude Code does that work
in the background; say briefly that you're on it, and never claim something is done before a report arrives.
- For a big or multi-step task (building or changing a feature, anything touching many files, deploying, anything
  hard to undo), first say your plan in one or two sentences and ask if you should go ahead. Call ask_claude only
  after the user agrees. For small, quick, or read-only tasks, skip the plan and just do it.
- To continue earlier work or answer a question Claude asked, call ask_claude again with the same project.
- Status questions ("what are you doing?", "is it done?"): call job_status.
- Never read more than three items aloud. Speak the headline and the count ("four orders need attention; the
  urgent one is from Ali"), and offer to send the full list rather than reciting it.
- If the user asks you to repeat ("say that again", "what was that?"), say the same thing again in fewer words.
- "Stop" or "cancel" about a task: call cancel_job.
- Whenever the user says "remember" — "remember that ...", "don't forget ...", "make a note that ..." — call remember
  immediately with what they said, in one short English sentence. Never reply "I'll remember" without calling it;
  saying it without saving it is a lie. Also call remember, without being asked, when they tell you something
  lasting about themselves: where they live, their preferences, the people around them, habits, how they want
  things done. Then confirm in a few words.
- When the user wants something to happen regularly or later ("every morning", "every 30 minutes", "each Monday",
  "remind me tomorrow at 9"), call add_routine. Use list_routines to say what is scheduled, remove_routine to stop
  one. Routines run on their own and report by voice, so confirm in a few words and move on.
- When the user says they will do something ("I'll send ten emails today", "I'll call Sam tomorrow"), call
  commit_to with that promise. When they say they did it, call complete_commitment. Never nag: mention open
  promises only when they ask, or when a routine brings them up.
- When the system asks the user to confirm an action and they answer yes or no, the system delivers that answer
  itself. Do not call any tool for it; just acknowledge in a few words.
- When the user says goodbye ("bye bye", "that's all"), answer with a one- or two-word farewell; the system then ends
  the conversation.

Known projects (pass the exact name as `project`; leave it empty for general computer tasks): {projects}"""

# GPT-Live speaks the backend model's text too (fillers, continuations), so it needs the language rule as well
BACKEND_INSTRUCTIONS = """You handle delegated work for Jarvis, a voice assistant on the user's Mac. Everything you
write is spoken aloud. Write in {language} by default. When the user's latest request is in another language, write
in that language instead. Use the tools for every action. Keep each message to one short sentence. When a tool says a
job started, just say you're on it."""

REPLY_START_TIMEOUT_S = 12.0
CONFIRM_ECHO_WINDOW_S = 15.0
# background speech (TV, other people) keeps "user speaking" alive; a real conversation gets replies
AGENT_SILENCE_CLOSE_S = 60.0
FAREWELL_GRACE_S = 6.0
# how long a language the user switched to sticks; after this, Jarvis goes back to JARVIS_DEFAULT_LANGUAGE
LANGUAGE_MEMORY_S = 900.0
# how many past turns seed a new conversation: enough for "carry on with that", too few to set the language
HISTORY_TURNS = 4
# after speaking a report nobody answers, close quickly — the line is billed by the second
REPORT_TAIL_S = 5.0


PROVIDERS = ("openai", "gemini")

# Gemini Flash Live needs the language spelled out; left to guess, it transcribed speech in the wrong language
GEMINI_LANGUAGES = {
    "Persian": "fa-IR",
    "English": "en-US",
    "Turkish": "tr-TR",
    "Russian": "ru-RU",
}


def _openai_model(**kwargs):
    return GPTLiveModel(**kwargs)


def _gemini_model(**kwargs):
    # imported at the top of this module, not here: LiveKit only registers plugins on the main thread,
    # and the wake word opens the voice on the jarvis-loop worker thread
    return GeminiRealtimeModel(**kwargs)


DEFAULT_FACTORIES = {"openai": _openai_model, "gemini": _gemini_model}


def build_realtime_model(settings, http, factories: dict | None = None):
    """The voice engine, chosen by JARVIS_VOICE_PROVIDER.

    Gemini is the default because the voice line item is essentially the whole bill: Gemini Live native audio lists
    at about $0.005/min listening and $0.018/min speaking, against gpt-live-1's $0.05/min. OpenAI stays one setting
    away as a fallback.
    """
    factories = DEFAULT_FACTORIES if factories is None else factories
    provider = (getattr(settings, "voice_provider", "gemini") or "gemini").strip().lower()
    if provider not in PROVIDERS:
        raise ValueError(f"unknown voice provider {provider!r}; use one of {', '.join(PROVIDERS)}")

    if provider == "gemini":
        if not getattr(settings, "gemini_api_key", None):
            raise ValueError("GEMINI_API_KEY is missing from ~/.jarvis/.env, so the Gemini voice cannot start")
        # say which engine is live: otherwise the log cannot tell a gemini run from an openai one
        log.info("voice: gemini %s, voice %s", settings.gemini_model, settings.gemini_voice)
        options = dict(model=settings.gemini_model, api_key=settings.gemini_api_key, voice=settings.gemini_voice,
                       instructions=build_instructions([], settings.default_language), temperature=0.8)
        # Native-audio models choose the language themselves and reject a language code outright: Google closes
        # the session within a second. Flash Live needs one: left to guess, it transcribed speech in the wrong
        # language.
        if "native-audio" not in settings.gemini_model:
            options["language"] = GEMINI_LANGUAGES.get(settings.default_language, "en-US")
        return factories["gemini"](**options)

    if not getattr(settings, "openai_api_key", None):
        raise ValueError("OPENAI_API_KEY is missing from ~/.jarvis/.env, so the OpenAI voice cannot start")
    log.info("voice: openai gpt-live-1, voice %s", settings.voice)
    return factories["openai"](
        voice=settings.voice,
        api_key=settings.openai_api_key,
        http_session=http,
        responses_options={"instructions": backend_instructions(settings.default_language)},
    )


def greeting_instructions(language: str) -> str:
    return (f"The user just called you by name. Speak in {language}. Greet them with only a short phrase meaning "
            "\"At your service.\", then stop and wait for them to speak.")


def build_instructions(projects: list[str], language: str = "English") -> str:
    return INSTRUCTIONS.format(projects=", ".join(projects) or "none", language=language)


def backend_instructions(language: str = "English") -> str:
    return BACKEND_INSTRUCTIONS.format(language=language)


def should_close(now: float, last_activity: float, idle_s: float, user_speaking: bool,
                 agent_busy: bool, confirm_pending: bool, last_agent_speech: float | None = None,
                 agent_silence_s: float = AGENT_SILENCE_CLOSE_S) -> bool:
    if agent_busy or confirm_pending:
        return False
    if last_agent_speech is not None and now - last_agent_speech >= agent_silence_s:
        return True
    if user_speaking:
        return False
    return now - last_activity >= idle_s


class JarvisTools:
    def __init__(self, jobs, resolver, store, broker=None, home: Path | None = None,
                 scheduler=None, clock: Callable[[], float] = time.time):
        self.jobs = jobs
        self.resolver = resolver
        self.store = store
        self.broker = broker
        self.home = home
        self.scheduler = scheduler
        self.clock = clock

    def ask_claude(self, task: str, project: str | None) -> str:
        if self.broker is not None:
            # the voice model tends to re-delegate a spoken yes/no as new work; that could repeat an action
            if self.broker.pending:
                return ("A confirmation question is waiting for the user's yes or no. No new job was started; "
                        "ask the user to answer it first.")
            if self.broker.answered_within(CONFIRM_ECHO_WINDOW_S):
                return ("The user's answer was already delivered to the running job, so no new job was started. "
                        "Just acknowledge briefly.")
        resolved = self.resolver.resolve(project)
        if resolved is None:
            options = ", ".join(self.resolver.suggestions(project or "")) or "none"
            return f"Unknown project '{project}'. Closest matches: {options}. Ask the user which one they mean."
        job_id = self.jobs.submit(resolved, task)
        return (f"Started job {job_id} in {resolved.name}. Tell the user in a few words that you're on it; "
                "a spoken report will come when it finishes.")

    def job_status(self) -> str:
        lines = []
        for job in self.store.active_jobs():
            steps = "; ".join(self.store.recent_events(job.id, 3)) or "starting"
            lines.append(f"Job {job.id} in {job.project} is {job.status}: {job.task}. Latest: {steps}")
        for job in self.store.jobs_since(self.clock() - 3600):
            if job.status in ("done", "failed", "cancelled"):
                lines.append(f"Job {job.id} in {job.project} {job.status}: {(job.result or '')[:200]}")
        return "\n".join(lines) if lines else "No jobs running or finished in the last hour."

    async def cancel_job(self, job_id: int | None) -> str:
        cancelled = await self.jobs.cancel(job_id)
        if not cancelled:
            return "Nothing to cancel."
        return "Cancelled job " + ", ".join(str(j) for j in cancelled) + "."

    def remember(self, fact: str) -> str:
        if self.home is None:
            return "Nothing was saved; no profile is configured."
        stored = remember_fact(self.home, fact)
        if not stored:
            return "That was empty, nothing to remember."
        return f"Saved: {stored}. Confirm in a few words."

    # ---- routines ----------------------------------------------------------

    def add_routine(self, name: str, when: str, task: str, project: str | None = None) -> str:
        if self.scheduler is None:
            return "Routines aren't available right now."
        try:
            described = self.scheduler.add(name.strip(), when, task, project or None)
        except ScheduleError as e:
            return f"That schedule didn't work: {e}. Ask the user for a clearer time."
        where = f" in {project}" if project else ""
        return f"Routine '{name}' saved: {described}{where}. Confirm in a few words."

    def list_routines(self) -> str:
        routines = self.store.list_routines()
        if not routines:
            return "No routines are set up yet."
        lines = []
        for r in routines:
            when = time.strftime("%a %H:%M", time.localtime(r.next_run)) if r.next_run else "not scheduled"
            state = "" if r.enabled else " (off)"
            lines.append(f"{r.name}: {r.schedule}, next {when}{state} — {r.task[:80]}")
        return (f"{len(routines)} routines. Say the count and at most three of them:\n" + "\n".join(lines))

    def remove_routine(self, name: str) -> str:
        if self.store.remove_routine(name.strip()):
            return f"Routine '{name}' removed. Confirm in a few words."
        names = ", ".join(r.name for r in self.store.list_routines()) or "none"
        return f"There is no routine called '{name}'. Existing ones: {names}."

    # ---- commitments -------------------------------------------------------

    def commit_to(self, promise: str) -> str:
        if self.home is None:
            return "Nothing was saved; no profile is configured."
        stored = add_commitment(self.home, promise)
        if not stored:
            return "That was empty, nothing to record."
        return f"Recorded: {stored}. Acknowledge in a few words, don't lecture."

    def complete_commitment(self, promise: str) -> str:
        if self.home is None:
            return "Nothing is recorded."
        done = complete_commitment(self.home, promise)
        if done is None:
            remaining = open_commitments(self.home)
            if not remaining:
                return "There were no open promises to tick off."
            return f"Nothing matched '{promise}'. Open promises: " + "; ".join(remaining[:3])
        return f"Ticked off: {done}. Say well done in a few words."


class JarvisAgent(Agent):
    def __init__(self, llm_model, tools: JarvisTools, projects: list[str], chat_ctx: llm.ChatContext | None = None,
                 profile: str = "", language: str = "English"):
        super().__init__(instructions=build_instructions(projects, language) + profile, llm=llm_model,
                         chat_ctx=chat_ctx)
        self._jarvis_tools = tools

    @function_tool
    async def ask_claude(self, context: RunContext, task: str, project: str | None = None) -> str:
        """Send a task to Claude Code, which acts on the user's Mac: code, shell, apps, browser, email, files,
        and anything needing live data from the internet. It runs in the background and reports back later.

        Args:
            task: The complete request in the user's own words and language, with every detail they gave.
            project: Exact project name from the known list, or empty for general computer tasks.
        """
        return self._jarvis_tools.ask_claude(task, project)

    @function_tool
    async def job_status(self, context: RunContext) -> str:
        """Get what Claude is doing now and what finished in the last hour."""
        return self._jarvis_tools.job_status()

    @function_tool
    async def cancel_job(self, context: RunContext, job_id: int | None = None) -> str:
        """Cancel a running or queued job.

        Args:
            job_id: The job number, or empty to cancel all running jobs.
        """
        return await self._jarvis_tools.cancel_job(job_id)

    @function_tool
    async def remember(self, context: RunContext, fact: str) -> str:
        """Save a lasting fact about the user so Jarvis and Claude know it in future conversations.

        Args:
            fact: One short sentence in English, e.g. "lives in Lisbon" or "prefers pnpm over npm".
        """
        return self._jarvis_tools.remember(fact)

    @function_tool
    async def add_routine(self, context: RunContext, name: str, when: str, task: str,
                          project: str | None = None) -> str:
        """Save work that should happen on its own, on a schedule, and report back by voice.

        Args:
            name: Short name for the routine, e.g. "morning tests" or "lead check".
            when: When to run, in plain words: "every morning at 9", "every 30 minutes", "weekdays at 18:30",
                "every monday 09:00", or "once 2026-10-01 14:00".
            task: What Claude should do each time, written in full as if asking it directly.
            project: Exact project name from the known list, or empty for general tasks.
        """
        return self._jarvis_tools.add_routine(name, when, task, project)

    @function_tool
    async def list_routines(self, context: RunContext) -> str:
        """List the routines that are set up and when each one runs next."""
        return self._jarvis_tools.list_routines()

    @function_tool
    async def remove_routine(self, context: RunContext, name: str) -> str:
        """Stop and delete a routine by name.

        Args:
            name: The routine's name, as given when it was created.
        """
        return self._jarvis_tools.remove_routine(name)

    @function_tool
    async def commit_to(self, context: RunContext, promise: str) -> str:
        """Record something the user says they will do, so Jarvis can ask about it later.

        Args:
            promise: The promise in one short line, e.g. "send 10 outreach emails today".
        """
        return self._jarvis_tools.commit_to(promise)

    @function_tool
    async def complete_commitment(self, context: RunContext, promise: str) -> str:
        """Tick off a promise the user says they have done.

        Args:
            promise: A few words identifying it, e.g. "outreach emails".
        """
        return self._jarvis_tools.complete_commitment(promise)


class VoiceController:
    def __init__(self, settings, audio, tools: JarvisTools, resolver, store, broker,
                 http: aiohttp.ClientSession, on_state: Callable[[str], None] = lambda s: None,
                 clock: Callable[[], float] = time.monotonic, hub=None):
        self.settings = settings
        self.audio = audio
        self.tools = tools
        self.resolver = resolver
        self.store = store
        self.broker = broker
        self.http = http
        self.on_state = on_state
        self.clock = clock
        self.hub = hub
        self.session: AgentSession | None = None
        self._model: GPTLiveModel | None = None
        self._lock = asyncio.Lock()
        self._say_lock = asyncio.Lock()
        self._watch: asyncio.Task[None] | None = None
        self._last_activity = clock()
        self._last_user_speech = clock()
        self._last_agent_speech = clock()
        self._opened_at = clock()
        self._opened_wall = time.time()
        self._user_speaking = False
        self._agent_busy = False
        self._speech_starts = 0
        self._language: str | None = None
        self._language_at = 0.0

    def _publish(self, kind: str, **data) -> None:
        if self.hub is not None:
            self.hub.publish(kind, **data)

    @property
    def is_open(self) -> bool:
        return self.session is not None

    @property
    def is_saying(self) -> bool:
        return self._say_lock.locked()

    @property
    def language(self) -> str:
        """The configured default language, unless the user recently spoke another one."""
        if self._language and self.clock() - self._language_at <= LANGUAGE_MEMORY_S:
            return self._language
        return self.settings.default_language

    def reset_language(self) -> None:
        """Back to the default. Every conversation starts fresh, so yesterday's language never carries over."""
        self._language = None
        self._language_at = 0.0

    def is_away(self) -> bool:
        return self.clock() - self._last_user_speech >= self.settings.away_after_s

    def _touch(self) -> None:
        self._last_activity = self.clock()

    def _history(self) -> llm.ChatContext:
        """Recent turns, for continuity — but only a few.

        Seeding a long history dragged Jarvis out of its default language: old turns in another language acted like
        examples and it kept answering in that language. A short tail keeps "carry on with that" working without
        letting yesterday's language decide today's.
        """
        ctx = llm.ChatContext.empty()
        for role, text in self.store.recent_transcripts(HISTORY_TURNS):
            ctx.add_message(role=role, content=text)
        return ctx

    async def open(self) -> None:
        async with self._lock:
            self._touch()
            if self.session is not None:
                return
            self.on_state("connecting")
            model = build_realtime_model(self.settings, self.http)
            session = AgentSession(llm=model)
            mic, speaker = self.audio.attach()
            session.input.audio = mic
            session.output.audio = speaker
            session.on("user_state_changed", self._on_user_state)
            session.on("agent_state_changed", self._on_agent_state)
            session.on("conversation_item_added", self._on_item)
            session.on("close", lambda ev: asyncio.ensure_future(self._on_session_closed(session)))
            agent = JarvisAgent(model, self.tools, self.resolver.names(), chat_ctx=self._history(),
                                profile=profile_block(self.settings.home), language=self.settings.default_language)
            try:
                await session.start(agent, record=False)
            except Exception:
                self.audio.detach()
                with contextlib.suppress(Exception):
                    await model.aclose()
                self.on_state("idle")
                raise
            self.session, self._model = session, model
            self.reset_language()   # every conversation begins in the default language
            self._opened_at = self._last_agent_speech = self.clock()
            self._opened_wall = time.time()
            self.audio.play_chime()
            self._watch = asyncio.create_task(self._idle_watch())
            self.on_state("listening")
            self._publish("session", open=True, language=self.language)
            log.info("voice session open")

    async def close(self) -> None:
        async with self._lock:
            session, model = self.session, self._model
            self.session, self._model = None, None
            if session is None:
                return
            if self._watch is not None and self._watch is not asyncio.current_task():
                self._watch.cancel()
            self.audio.detach()
            with contextlib.suppress(Exception):
                await session.aclose()
            with contextlib.suppress(Exception):
                await model.aclose()
            self._user_speaking = self._agent_busy = False
            ended = time.time()
            with contextlib.suppress(Exception):
                self.store.add_voice_session(self._opened_wall, ended)
            self.audio.play_chime(freq=587.0)
            self.on_state("idle")
            self._publish("session", open=False, seconds=round(ended - self._opened_wall))
            log.info("voice session closed after %.0fs", ended - self._opened_wall)

    async def _on_session_closed(self, session: AgentSession) -> None:
        if self.session is session:
            log.warning("voice session closed by the service")
            await self.close()

    async def _close_after_farewell(self) -> None:
        # let the model start and finish its one-word farewell, but don't wait long
        deadline = self.clock() + FAREWELL_GRACE_S
        await asyncio.sleep(1.0)
        while self.clock() < deadline and (self._agent_busy or self._user_speaking):
            await asyncio.sleep(0.2)
        log.info("user said goodbye")
        await self.close()

    async def say(self, instructions: str) -> None:
        """Make the model speak now; retries once if speech never starts."""
        async with self._say_lock:
            await self.open()
            # a request sent the instant a session starts is sometimes dropped by the service
            settle = 1.0 - (self.clock() - self._opened_at)
            if settle > 0:
                await asyncio.sleep(settle)
            for attempt in range(2):
                session = self.session
                if session is None:
                    return
                before = self._speech_starts
                self._touch()
                session.generate_reply(instructions=instructions)
                deadline = self.clock() + REPLY_START_TIMEOUT_S
                while self.clock() < deadline and self._speech_starts == before and self.session is session:
                    await asyncio.sleep(0.2)
                if self._speech_starts != before:
                    return
                log.warning("spoken reply did not start (attempt %d)", attempt + 1)

    async def greet(self) -> None:
        await self.say(greeting_instructions(self.language))

    async def announce(self, report: str) -> None:
        await self.say(f"A background job report arrived. Speak in {self.language}. Tell the user in one or two "
                       f"short sentences, without reading code or paths. Report: {report}")
        # a report nobody answers should not hold a billed line open for the full idle timeout
        self._last_activity = self.clock() - max(0.0, self.settings.idle_close_s - REPORT_TAIL_S)

    async def ask_confirmation(self, summary: str) -> None:
        self._publish("confirm", question=summary)
        await self.say(f"Claude wants to do something that needs the user's approval: {summary}. Speak in "
                       f"{self.language}. Ask the user in one short sentence whether to go ahead, yes or no.")

    def _on_user_state(self, ev) -> None:
        self._user_speaking = ev.new_state == "speaking"
        self._touch()
        if self._user_speaking:
            self._last_user_speech = self.clock()

    def _on_agent_state(self, ev) -> None:
        self._agent_busy = ev.new_state in ("thinking", "speaking")
        if ev.new_state == "speaking":
            self._speech_starts += 1
        if self._agent_busy:
            self._last_agent_speech = self.clock()
        self._touch()
        self.on_state("speaking" if ev.new_state == "speaking" else "listening")

    def _on_item(self, ev) -> None:
        item = ev.item
        role = getattr(item, "role", None)
        text = (getattr(item, "text_content", None) or "").strip()
        if role not in ("user", "assistant") or not text:
            return
        self.store.add_transcript(role, text)
        self._touch()
        log.info("%s: %s", role, text)
        self._publish("transcript", role=role, text=text)
        if role == "assistant":
            self._last_agent_speech = self.clock()
        if role == "user":
            self._last_user_speech = self.clock()
            if lang := detect_language(text):
                self._language = lang
                self._language_at = self.clock()
            if self.broker.offer(text):
                return
            if is_goodbye(text) and not self.broker.pending:
                asyncio.ensure_future(self._close_after_farewell())

    async def _idle_watch(self) -> None:
        while self.session is not None:
            await asyncio.sleep(1.0)
            if should_close(self.clock(), self._last_activity, self.settings.idle_close_s,
                            self._user_speaking, self._agent_busy, self.broker.pending,
                            last_agent_speech=self._last_agent_speech):
                await self.close()
                return
