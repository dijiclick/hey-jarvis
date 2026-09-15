import argparse
import asyncio
import dataclasses
import logging
import shutil
import signal
import subprocess
import sys
import wave
from pathlib import Path

from .config import load_settings
from .jobs import JobEvent, JobManager
from .projects import ProjectResolver, load_aliases
from .single import acquire_lock
from .store import Store
from .worker import ClaudeWorker


def _setup_logging(settings, verbose: bool) -> None:
    settings.home.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(settings.home / "jarvis.log")]
    if sys.stderr.isatty():
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not verbose:
        for noisy in ("livekit", "livekit.agents", "livekit.plugins.openai", "asyncio", "claude_agent_sdk"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


async def _ask(task: str, project_name: str | None, model: str | None) -> int:
    settings = load_settings()
    store = Store(settings.db_path)
    resolver = ProjectResolver(settings.projects_root, load_aliases(settings.home / "projects.json"))
    project = resolver.resolve(project_name)
    if project is None:
        print(f"Unknown project {project_name!r}. Closest: {', '.join(resolver.suggestions(project_name))}")
        return 2
    done = asyncio.Event()
    outcome = {"code": 0}

    async def confirm(summary: str) -> bool:
        answer = await asyncio.to_thread(input, f"\nConfirm: {summary}? [yes/no] ")
        return answer.strip().lower() in ("y", "yes")

    def on_event(ev: JobEvent) -> None:
        if ev.kind == "progress":
            print(f"  · {ev.text}", flush=True)
        elif ev.kind in ("result", "failed"):
            print(f"\n[{ev.kind}] {ev.text}")
            outcome["code"] = 0 if ev.kind == "result" else 1
            done.set()

    from .chrome_consent import ChromeConsentClicker

    clicker = ChromeConsentClicker()
    jobs = JobManager(store, lambda p: ClaudeWorker(p, store, confirm, model=model, on_browser_tool=clicker.arm),
                      on_event)
    jid = jobs.submit(project, task)
    print(f"Job {jid} in {project.name} ({project.path})")
    await done.wait()
    await jobs.shutdown()
    clicker.stop()
    return outcome["code"]


async def _run(verbose: bool) -> int:
    from .app import JarvisApp
    from .audio import LocalAudio

    settings = load_settings()
    lock = acquire_lock(settings.home)
    if lock is None:
        print("Jarvis is already running (see the menu bar).")
        return 1
    _setup_logging(settings, verbose)
    app = JarvisApp(settings, lambda loop: LocalAudio(loop, input_device=settings.input_device),
                    on_state=lambda st: logging.getLogger("jarvis").info("state: %s", st))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    print(f"Jarvis is listening. Say 'Hey Jarvis' or press {settings.hotkey}. Ctrl+C to quit.")
    await app.run(stop)
    lock.close()
    return 0


async def _simulate(clips: list[str], gap: float, tail: float, out: str | None, model: str | None,
                    projects_root: str | None, browser: bool) -> int:
    from .app import JarvisApp
    from .audio import SR
    from .fileaudio import FileAudio

    settings = load_settings()
    if projects_root:
        settings = dataclasses.replace(settings, projects_root=Path(projects_root).expanduser())
    _setup_logging(settings, False)
    holder: dict[str, FileAudio] = {}

    def audio_factory(loop):
        holder["audio"] = FileAudio(loop, [Path(c) for c in clips], gap_s=gap)
        return holder["audio"]

    app = JarvisApp(settings, audio_factory, use_ears=False, open_on_start=True, worker_model=model,
                    browser=browser, on_state=lambda st: print(f"[state] {st}", flush=True))
    stop = asyncio.Event()
    runner = asyncio.create_task(app.run(stop))
    await app.started.wait()
    await holder["audio"].wait_finished()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + tail
    quiet_since = None
    while loop.time() < deadline:
        if app.is_quiet():
            quiet_since = quiet_since or loop.time()
            if loop.time() - quiet_since >= 3:
                break
        else:
            quiet_since = None
        await asyncio.sleep(0.5)
    stop.set()
    await runner
    for job in app.store.jobs_since(0)[-10:]:
        print(f"[job {job.id}] {job.project} {job.status}: {job.task} -> {(job.result or '')[:300]}")
    for role, text in app.store.recent_transcripts(40):
        print(f"[{role}] {text}")
    if out:
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(bytes(holder["audio"].captured))
    return 0


def _doctor() -> int:
    import urllib.request

    ok = True

    def check(name: str, passed: bool, hint: str = "", required: bool = True) -> None:
        nonlocal ok
        if required:
            ok &= passed
        mark = "✔" if passed else ("✘" if required else "–")
        print(f"{mark} {name}" + ("" if passed else f"  → {hint}"))

    try:
        settings = load_settings()
        check(f"API key for the {settings.voice_provider} voice", True)
    except RuntimeError as e:
        check("API key", False, str(e))
        return 1
    if settings.voice_provider == "openai":
        name = "gpt-live-1"
        req = urllib.request.Request(f"https://api.openai.com/v1/models/{name}",
                                     headers={"Authorization": f"Bearer {settings.openai_api_key}"})
    else:
        name = settings.gemini_model
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{name}",
                                     headers={"x-goog-api-key": settings.gemini_api_key or ""})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            check(f"{name} access", resp.status == 200)
    except Exception as e:
        check(f"{name} access", False, f"API check failed: {type(e).__name__}; check the key with `jarvis setup`")
    claude = shutil.which("claude")
    check("claude CLI installed", claude is not None, "install Claude Code")
    if claude:
        v = subprocess.run([claude, "--version"], capture_output=True, text=True)
        check(f"claude runs ({v.stdout.strip()})", v.returncode == 0, "run `claude` once and log in")
    check("npx available (browser control)", shutil.which("npx") is not None, "install Node.js")
    try:
        import sounddevice as sd

        from .audio import pick_input_device

        dev = sd.query_devices(pick_input_device(settings.input_device), kind="input")
        check(f"microphone: {dev['name']} (JARVIS_INPUT_DEVICE={settings.input_device})", True)
    except Exception as e:
        check("microphone", False, f"{e}; grant Microphone permission to your terminal")
    try:
        from .ears import WakeWordDetector

        WakeWordDetector()
        check("wake word model loads", True)
    except Exception as e:
        check("wake word model loads", False, str(e))
    port_file = Path.home() / "Library/Application Support/Google/Chrome/DevToolsActivePort"
    check("Chrome remote debugging enabled", port_file.exists(),
          "open chrome://inspect/#remote-debugging in Chrome and turn it on", required=False)
    check("Telegram configured", bool(settings.telegram_bot_token and settings.telegram_chat_id),
          "add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to ~/.jarvis/.env", required=False)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="start Jarvis")
    p_run.add_argument("--no-menubar", action="store_true")
    p_run.add_argument("-v", "--verbose", action="store_true")
    p_ask = sub.add_parser("ask", help="run one Claude job from the terminal")
    p_ask.add_argument("task")
    p_ask.add_argument("--project")
    p_ask.add_argument("--model")
    p_sim = sub.add_parser("simulate", help="drive Jarvis with WAV clips instead of the mic")
    p_sim.add_argument("clips", nargs="+")
    p_sim.add_argument("--gap", type=float, default=20.0)
    p_sim.add_argument("--tail", type=float, default=120.0)
    p_sim.add_argument("--out")
    p_sim.add_argument("--model")
    p_sim.add_argument("--projects-root")
    p_sim.add_argument("--browser", action="store_true")
    sub.add_parser("panel", help="open the live visual panel of the running Jarvis")
    sub.add_parser("routines", help="list the routines Jarvis runs on its own")
    sub.add_parser("report", help="show voice minutes, estimated spend, and job counts")
    sub.add_parser("setup", help="choose a voice engine, save your API key, pick a language")
    sub.add_parser("doctor", help="check keys, permissions, and dependencies")
    p_app = sub.add_parser("app", help="build Jarvis.app, a double-clickable launcher")
    p_app.add_argument("--dest", default=None, help="folder for Jarvis.app (default: this project)")
    sub.add_parser("install", help="start Jarvis at login (LaunchAgent)")
    sub.add_parser("uninstall", help="remove the LaunchAgent")
    args = parser.parse_args(argv)
    if args.cmd == "ask":
        logging.basicConfig(level=logging.WARNING)
        return asyncio.run(_ask(args.task, args.project, args.model))
    if args.cmd == "run":
        if args.no_menubar:
            return asyncio.run(_run(args.verbose))
        from .menubar import run_menubar

        return run_menubar(args.verbose)
    if args.cmd == "simulate":
        return asyncio.run(_simulate(args.clips, args.gap, args.tail, args.out, args.model, args.projects_root,
                                     args.browser))
    if args.cmd == "panel":
        import urllib.request

        from .menubar import open_panel
        from .panel import DEFAULT_PORT, HOST

        url = f"http://{HOST}:{DEFAULT_PORT}/"
        try:
            urllib.request.urlopen(url, timeout=3).close()
        except Exception:
            print(f"No panel at {url}. Start Jarvis first (open Jarvis.app or `jarvis run`).")
            return 1
        open_panel(url)
        print(f"Opened {url}")
        return 0
    if args.cmd == "routines":
        import time as _time

        settings = load_settings()
        routines = Store(settings.db_path).list_routines()
        if not routines:
            print("No routines yet. Say: “Hey Jarvis, every morning at 9, run the tests in my project.”")
            return 0
        for r in routines:
            when = _time.strftime("%a %d %b %H:%M", _time.localtime(r.next_run)) if r.next_run else "not scheduled"
            print(f"{'  ' if r.enabled else '× '}{r.name:22} {r.schedule:24} next {when}"
                  f"{'' if r.enabled else '  (off)'}\n    {r.task[:110]}")
        return 0
    if args.cmd == "report":
        import time

        from .report import build_report, format_report
        from .spend import get_spend

        settings = load_settings()
        spend = get_spend(settings.openai_admin_key)
        print(format_report(build_report(Store(settings.db_path), time.time(), spend=spend)))
        return 0
    if args.cmd == "setup":
        import getpass

        from .config import HOME
        from .onboarding import run_setup

        return run_setup(HOME, ask=lambda prompt, default: input(prompt), ask_secret=getpass.getpass, say=print)
    if args.cmd == "doctor":
        return _doctor()
    if args.cmd == "app":
        from .macapp import REPO, build_app

        app = build_app(Path(args.dest).expanduser() if args.dest else REPO)
        print(f"Built {app}. Double-click it to start Jarvis.")
        return 0
    if args.cmd in ("install", "uninstall"):
        from .launchagent import install, uninstall

        return install() if args.cmd == "install" else uninstall()
    return 0


if __name__ == "__main__":
    sys.exit(main())
