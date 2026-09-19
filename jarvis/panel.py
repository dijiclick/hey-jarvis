"""The visual panel: a local page that shows what Jarvis is doing, live.

The browser does no audio analysis. Python pushes {state, levels, jobs, routines, spend} over a WebSocket and the
page smooths them — the approach used by the reference JARVIS HUDs, and the reason the orb stays steady.
"""
import asyncio
import contextlib
import logging
import os
import time
from pathlib import Path

from aiohttp import WSCloseCode, WSMsgType, web

from .commitments import open_commitments
from .profile import load_projects
from .report import build_report

log = logging.getLogger("jarvis.panel")

PANEL_HTML = Path(__file__).parent / "panel.html"
DEFAULT_PORT = int(os.environ.get("JARVIS_PANEL_PORT", "8787"))
HOST = "127.0.0.1"
# an open panel page retries its connection with backoff capped at 8 s (panel.html), so this covers one full retry
PANEL_RECONNECT_WAIT_S = 10.0


def open_panel(url: str) -> None:
    """Open the panel in its own chromeless Chrome window, falling back to the default browser."""
    import subprocess

    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    # its own profile: no debugging banner, and it never disturbs the user's real Chrome session
    profile = Path.home() / ".jarvis" / "panel-chrome"
    try:
        subprocess.Popen([chrome, f"--app={url}", "--window-size=1180,760",
                          f"--user-data-dir={profile}", "--no-first-run", "--no-default-browser-check"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        subprocess.run(["open", url])


def focus_panel() -> bool:
    """Bring the open panel window to the front; False when no panel Chrome is running."""
    import subprocess

    profile = Path.home() / ".jarvis" / "panel-chrome"
    found = subprocess.run(["pgrep", "-f", f"MacOS/Google Chrome --app=.*--user-data-dir={profile}"],
                           capture_output=True, text=True)
    pids = found.stdout.split()
    if not pids:
        return False
    script = f'tell application "System Events" to set frontmost of (first process whose unix id is {pids[0]}) to true'
    return subprocess.run(["osascript", "-e", script], capture_output=True).returncode == 0


def show_panel(url: str, clients: int) -> None:
    """Show the panel: bring an open window forward, and open a new one only when none is open."""
    if clients > 0 and focus_panel():
        return
    open_panel(url)


async def open_panel_unless_shown(server, wait_s: float = PANEL_RECONNECT_WAIT_S, opener=open_panel) -> None:
    """At startup a window left over from the last run reconnects on its own; open one only if none does."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        if server.clients > 0:
            log.info("panel window already open; not opening another")
            return
        await asyncio.sleep(0.25)
    if server.clients == 0:
        log.info("opening the panel window")
        opener(server.url)


def parse_projects(home: Path | None) -> list[dict]:
    """Turn the surveyed projects.md into rows: name, what it is, status, last activity."""
    if home is None:
        return []
    projects: list[dict] = []
    current: dict | None = None
    for line in load_projects(home).splitlines():
        if line.startswith("## "):
            if current:
                projects.append(current)
            current = {"name": line[3:].split("(")[0].strip(), "what": "", "status": "", "last": ""}
        elif current:
            for key, label in (("what", "what it is:"), ("status", "status:"), ("last", "last activity:")):
                if label in line:
                    current[key] = line.split(label, 1)[1].strip()
    if current:
        projects.append(current)
    return projects


def snapshot(state: str, store, now: float, spend=None, home: Path | None = None, autonomy: str | None = None) -> dict:
    """Everything a freshly opened panel needs before live events start arriving."""
    report = build_report(store, now, spend=spend)
    active = [{"id": j.id, "project": j.project, "status": j.status, "task": j.task,
               "steps": store.recent_events(j.id, 3)} for j in store.active_jobs()]
    recent = [{"id": j.id, "project": j.project, "status": j.status, "task": j.task,
               "result": (j.result or "")[:300]}
              for j in store.jobs_since(now - 24 * 3600) if j.status in ("done", "failed", "cancelled")][-10:]
    routines = [{"name": r.name, "schedule": r.schedule, "next_run": r.next_run, "enabled": r.enabled,
                 "task": r.task[:120]} for r in store.list_routines()]
    by_day = sorted((spend.by_day if spend and spend.available else {}).items())[-14:]
    return {
        "kind": "snapshot",
        "state": state,
        "autonomy": autonomy,
        "projects": parse_projects(home),
        "commitments": open_commitments(home) if home else [],
        "routines": routines,
        "active": active,
        "recent": recent,
        "today": {"minutes": round(report.voice_min_today, 1), "cost": round(report.cost_today, 2),
                  "jobs": report.jobs_today,
                  # what OpenAI actually billed today, when an Admin key makes it readable
                  "billed": round(spend.today, 2) if spend is not None and spend.available else None},
        "spend": {"week": round(spend.week, 2), "month": round(spend.month, 2),
                  "by_day": [{"day": d, "value": round(v, 2)} for d, v in by_day]}
        if spend is not None and spend.available else None,
    }


class PanelServer:
    def __init__(self, hub, store, state_getter, port: int = DEFAULT_PORT, host: str = HOST, spend=None,
                 home: Path | None = None, autonomy=None):
        self.hub = hub
        self.autonomy = autonomy
        self.store = store
        self.state_getter = state_getter
        self.port = port
        self.host = host
        self.spend = spend
        self.home = home
        self._runner: web.AppRunner | None = None
        self.clients = 0
        self._sockets: set[web.WebSocketResponse] = set()
        # changes on every start, so a panel window kept open across a restart knows to reload the new page
        self.boot = str(time.time())

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> bool:
        app = web.Application()
        app.add_routes([web.get("/", self._index), web.get("/ws", self._ws),
                        web.get("/clients", self._clients), web.post("/autonomy", self._set_autonomy)])
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        try:
            await web.TCPSite(runner, self.host, self.port).start()
        except OSError as e:
            log.warning("panel not started on %s: %s", self.url, e)
            await runner.cleanup()
            return False
        self._runner = runner
        if runner.addresses:  # port 0 means "any free port"; report the real one
            self.port = runner.addresses[0][1]
        log.info("panel at %s", self.url)
        return True

    async def stop(self) -> None:
        # close open panel windows' connections first; otherwise cleanup waits for them to leave on their own
        for ws in list(self._sockets):
            with contextlib.suppress(Exception):
                await ws.close(code=WSCloseCode.GOING_AWAY, message=b"Jarvis is stopping")
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(PANEL_HTML, headers={"Cache-Control": "no-store"})

    async def _clients(self, request: web.Request) -> web.Response:
        return web.json_response({"clients": self.clients})

    async def _set_autonomy(self, request: web.Request) -> web.Response:
        # any website can POST to localhost: accept only this page's own origin, and only JSON, which a
        # cross-site form can't send without a CORS preflight this server never answers
        origin = request.headers.get("Origin")
        if origin is not None and origin.rstrip("/") != self.url.rstrip("/"):
            return web.json_response({"error": "forbidden"}, status=403)
        if request.content_type != "application/json":
            return web.json_response({"error": "send JSON"}, status=415)
        if self.autonomy is None:
            return web.json_response({"error": "unavailable"}, status=503)
        try:
            level = (await request.json()).get("level")
        except (ValueError, AttributeError):
            level = None
        if not self.autonomy.set(level):
            return web.json_response({"error": "unknown level"}, status=400)
        return web.json_response({"level": level})

    def _snapshot(self) -> dict:
        return {**snapshot(self.state_getter(), self.store, time.time(),
                           spend=self.spend.get() if self.spend else None, home=self.home,
                           autonomy=self.autonomy.get() if self.autonomy else None), "boot": self.boot}

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        self.clients += 1
        self._sockets.add(ws)
        try:
            return await self._stream(ws)
        finally:
            self.clients -= 1
            self._sockets.discard(ws)

    async def _stream(self, ws: web.WebSocketResponse) -> web.WebSocketResponse:
        await ws.send_json(self._snapshot())

        async def drain() -> None:
            # a client that closes or sends anything unblocks the writer below
            async for message in ws:
                if message.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break

        reader = asyncio.create_task(drain())
        try:
            with self.hub.subscribe() as queue:
                while not ws.closed:
                    getter = asyncio.create_task(queue.get())
                    done, _ = await asyncio.wait({getter, reader}, return_when=asyncio.FIRST_COMPLETED)
                    if getter not in done:
                        getter.cancel()
                        break
                    event = getter.result()
                    with contextlib.suppress(ConnectionResetError):
                        await ws.send_json(event.as_dict())
                        # job and routine activity changes the data panes, so refresh them
                        if event.kind in ("job", "routine"):
                            await ws.send_json(self._snapshot())
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader
        return ws
