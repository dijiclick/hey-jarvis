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

from aiohttp import WSMsgType, web

from .commitments import open_commitments
from .profile import load_projects
from .report import build_report

log = logging.getLogger("jarvis.panel")

PANEL_HTML = Path(__file__).parent / "panel.html"
DEFAULT_PORT = int(os.environ.get("JARVIS_PANEL_PORT", "8787"))
HOST = "127.0.0.1"


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


def snapshot(state: str, store, now: float, spend=None, home: Path | None = None) -> dict:
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
                 home: Path | None = None):
        self.hub = hub
        self.store = store
        self.state_getter = state_getter
        self.port = port
        self.host = host
        self.spend = spend
        self.home = home
        self._runner: web.AppRunner | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    async def start(self) -> bool:
        app = web.Application()
        app.add_routes([web.get("/", self._index), web.get("/ws", self._ws)])
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
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(PANEL_HTML, headers={"Cache-Control": "no-store"})

    def _snapshot(self) -> dict:
        return snapshot(self.state_getter(), self.store, time.time(),
                        spend=self.spend.get() if self.spend else None, home=self.home)

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
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
