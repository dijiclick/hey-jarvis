import asyncio
import logging
import subprocess
import threading

import rumps

from .app import JarvisApp
from .audio import LocalAudio
from .config import load_settings
from .single import acquire_lock

VOICE_USD_PER_MIN = 0.05  # GPT-Live voice session price, billed per second
ICONS = {"idle": "◎", "connecting": "…", "listening": "🎙", "speaking": "🔊", "error": "⚠︎"}


from .panel import open_panel  # noqa: E402  (kept importable from here for the menu item below)


def run_menubar(verbose: bool) -> int:
    from .cli import _setup_logging

    settings = load_settings()
    lock = acquire_lock(settings.home)
    if lock is None:
        subprocess.run(["osascript", "-e", 'display notification "Jarvis is already running." with title "Jarvis"'])
        return 0
    _setup_logging(settings, verbose)
    state = {"value": "idle"}
    app = JarvisApp(settings, lambda lp: LocalAudio(lp, input_device=settings.input_device),
                    on_state=lambda s: state.__setitem__("value", s))
    loop = asyncio.new_event_loop()
    stop_holder: dict[str, asyncio.Event] = {}

    def worker() -> None:
        asyncio.set_event_loop(loop)

        async def main() -> None:
            stop_holder["stop"] = asyncio.Event()
            await app.run(stop_holder["stop"])

        try:
            loop.run_until_complete(main())
        except Exception:
            logging.getLogger("jarvis").exception("Jarvis crashed")
            state["value"] = "error"

    threading.Thread(target=worker, name="jarvis-loop", daemon=True).start()

    class Menu(rumps.App):
        def __init__(self) -> None:
            super().__init__("Jarvis", title=ICONS["idle"], quit_button=None)
            self.menu = ["Talk", "Panel", "Status", "Spending", None, "Quit"]

        @rumps.timer(0.5)
        def refresh(self, _) -> None:
            jobs = app.active_jobs()
            self.title = ICONS.get(state["value"], "◎") + (f" {jobs}" if jobs else "")

        @rumps.clicked("Talk")
        def talk(self, _) -> None:
            app.wake()

        @rumps.clicked("Panel")
        def panel(self, _) -> None:
            if app.panel is None:
                rumps.alert("Jarvis", "The panel isn't running. Check ~/.jarvis/jarvis.log.")
                return
            open_panel(app.panel.url)

        @rumps.clicked("Status")
        def status(self, _) -> None:
            if app.voice is None or app.store is None:
                rumps.alert("Jarvis", "Starting…")
                return
            rumps.alert("Jarvis", app.voice.tools.job_status())

        @rumps.clicked("Spending")
        def spending(self, _) -> None:
            import time

            from .report import build_report, format_report

            if app.store is None:
                rumps.alert("Jarvis", "Starting…")
                return
            spend = app.spend.get() if app.spend else None
            rumps.alert("Jarvis", format_report(build_report(app.store, time.time(), spend=spend)))

        @rumps.clicked("Quit")
        def quit(self, _) -> None:
            if "stop" in stop_holder:
                loop.call_soon_threadsafe(stop_holder["stop"].set)
            rumps.quit_application()

    Menu().run()
    return 0
