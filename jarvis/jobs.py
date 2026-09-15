import asyncio
import contextlib
import inspect
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from .projects import Project
from .store import Store

log = logging.getLogger("jarvis.jobs")


@dataclass
class JobEvent:
    job_id: int
    project: str
    kind: Literal["started", "progress", "result", "failed", "cancelled"]
    text: str


class WorkerClient(Protocol):
    def run(self, prompt: str) -> AsyncIterator[tuple[str, str]]: ...
    async def interrupt(self) -> None: ...
    async def close(self) -> None: ...


class JobManager:
    def __init__(self, store: Store, factory: Callable[[Project], WorkerClient],
                 on_event: Callable[[JobEvent], Awaitable[None] | None], cancel_grace_s: float = 5.0):
        self.store = store
        self.factory = factory
        self.on_event = on_event
        self.cancel_grace_s = cancel_grace_s
        self._clients: dict[str, WorkerClient] = {}
        self._queues: dict[str, asyncio.Queue[int]] = {}
        self._lanes: dict[str, asyncio.Task[None]] = {}
        self._running: dict[int, asyncio.Task[None]] = {}
        self._projects: dict[int, Project] = {}
        self._cancelled: set[int] = set()

    async def _emit(self, ev: JobEvent) -> None:
        try:
            r = self.on_event(ev)
            if inspect.isawaitable(r):
                await r
        except Exception:
            log.exception("event handler failed for %s", ev)

    async def prewarm(self, project: Project) -> None:
        """Start the project's worker ahead of its first job; failures only cost the head start."""
        if project.name in self._clients:
            return
        client = self._clients[project.name] = self.factory(project)
        warm = getattr(client, "warm", None)
        if warm is None:
            return
        try:
            await warm()
            log.info("worker for %s is warm", project.name)
        except Exception as e:
            log.warning("prewarm of %s failed: %s", project.name, e)
            await self._drop_client(project.name)

    def submit(self, project: Project, task: str) -> int:
        jid = self.store.create_job(project.name, str(project.path), task)
        self._projects[jid] = project
        self._queues.setdefault(project.name, asyncio.Queue()).put_nowait(jid)
        lane = self._lanes.get(project.name)
        if lane is None or lane.done():
            self._lanes[project.name] = asyncio.create_task(self._lane(project.name))
        return jid

    async def _lane(self, name: str) -> None:
        q = self._queues[name]
        while True:
            try:
                jid = q.get_nowait()
            except asyncio.QueueEmpty:
                return
            if jid in self._cancelled:
                continue
            t = asyncio.create_task(self._run_job(jid))
            self._running[jid] = t
            try:
                await t
            finally:
                self._running.pop(jid, None)

    async def _drop_client(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client is not None:
            with contextlib.suppress(Exception):
                await client.close()

    async def _run_job(self, jid: int) -> None:
        if jid in self._cancelled:
            return
        project = self._projects[jid]
        job = self.store.get_job(jid)
        self.store.set_status(jid, "running")
        await self._emit(JobEvent(jid, project.name, "started", job.task))
        try:
            client = self._clients.get(project.name)
            if client is None:
                client = self._clients[project.name] = self.factory(project)
            result = None
            async for kind, text in client.run(job.task):
                if kind == "progress":
                    self.store.add_event(jid, "progress", text)
                    await self._emit(JobEvent(jid, project.name, "progress", text))
                elif kind == "result":
                    result = text
            if jid in self._cancelled:
                return
            result = result or "Done."
            self.store.set_status(jid, "done", result)
            await self._emit(JobEvent(jid, project.name, "result", result))
        except asyncio.CancelledError:
            await self._drop_client(project.name)
            if jid in self._cancelled:
                return
            raise
        except Exception as e:
            await self._drop_client(project.name)
            if jid in self._cancelled:
                return
            msg = f"{type(e).__name__}: {e}"[:500]
            self.store.set_status(jid, "failed", msg)
            await self._emit(JobEvent(jid, project.name, "failed", msg))

    async def cancel(self, job_id: int | None = None) -> list[int]:
        targets = [job_id] if job_id is not None else [j.id for j in self.store.active_jobs()]
        jobs = []
        for jid in targets:
            job = self.store.get_job(jid)
            if job is None or job.status not in ("queued", "running"):
                continue
            # mark every target first so a lane cannot start one while we wait on another
            self._cancelled.add(jid)
            self.store.set_status(jid, "cancelled")
            jobs.append(job)
        for job in jobs:
            await self._emit(JobEvent(job.id, job.project, "cancelled", ""))
            task = self._running.get(job.id)
            if task is None:
                continue
            client = self._clients.get(job.project)
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.interrupt()
            done, _ = await asyncio.wait({task}, timeout=self.cancel_grace_s)
            if not done:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        return [job.id for job in jobs]

    async def shutdown(self) -> None:
        await self.cancel()
        for lane in self._lanes.values():
            lane.cancel()
        for name in list(self._clients):
            await self._drop_client(name)
