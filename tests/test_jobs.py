import asyncio
import time
from pathlib import Path

from jarvis.jobs import JobManager
from jarvis.projects import Project
from jarvis.store import Store


class FakeClient:
    def __init__(self, script, log):
        self.script, self.log = script, log
        self.interrupted = False

    async def run(self, prompt):
        self.log.append(("start", prompt, time.monotonic()))
        for kind, text, delay in self.script(prompt):
            await asyncio.sleep(delay)
            if self.interrupted:
                return
            if kind == "raise":
                raise RuntimeError(text)
            yield kind, text
        self.log.append(("end", prompt, time.monotonic()))

    async def interrupt(self):
        self.interrupted = True

    async def close(self):
        pass


async def until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while not pred():
        assert time.monotonic() < end, "timed out"
        await asyncio.sleep(0.01)


def setup(tmp_path, script, grace=0.2):
    store = Store(tmp_path / "j.db")
    events, log, made = [], [], []

    def factory(project):
        made.append(project.name)
        return FakeClient(script, log)

    jm = JobManager(store, factory, events.append, cancel_grace_s=grace)
    return jm, store, events, log, made


A = Project("A", Path("/a"))
B = Project("B", Path("/b"))


async def test_job_runs_and_reports(tmp_path):
    jm, store, events, _, _ = setup(tmp_path, lambda p: [("progress", "Running: npm test", 0), ("result", "Fixed.", 0)])
    jid = jm.submit(A, "fix login")
    await until(lambda: any(e.kind == "result" for e in events))
    assert store.get_job(jid).status == "done"
    assert store.get_job(jid).result == "Fixed."
    assert store.recent_events(jid) == ["Running: npm test"]
    assert [e.kind for e in events] == ["started", "progress", "result"]


async def test_same_project_queues_and_projects_run_in_parallel(tmp_path):
    jm, _, events, log, made = setup(tmp_path, lambda p: [("result", p, 0.2)])
    jm.submit(A, "a1")
    jm.submit(A, "a2")
    jm.submit(B, "b1")
    await until(lambda: sum(e.kind == "result" for e in events) == 3)
    t = {(kind, prompt): ts for kind, prompt, ts in log}
    assert t[("start", "a2")] >= t[("end", "a1")]
    assert t[("start", "b1")] < t[("end", "a1")]
    assert sorted(made) == ["A", "B"]


async def test_failure_marks_failed_and_next_job_runs(tmp_path):
    jm, store, events, _, made = setup(
        tmp_path, lambda p: [("raise", "boom", 0)] if p == "bad" else [("result", "ok", 0)])
    bad = jm.submit(A, "bad")
    good = jm.submit(A, "good")
    await until(lambda: store.get_job(good).status == "done")
    assert store.get_job(bad).status == "failed"
    assert "boom" in store.get_job(bad).result
    assert made == ["A", "A"]


async def test_cancel_running_job(tmp_path):
    jm, store, events, _, _ = setup(tmp_path, lambda p: [("result", "late", 5)] if p == "slow" else [("result", "ok", 0)])
    slow = jm.submit(A, "slow")
    nxt = jm.submit(A, "next")
    await until(lambda: store.get_job(slow).status == "running")
    assert await jm.cancel(slow) == [slow]
    assert store.get_job(slow).status == "cancelled"
    await until(lambda: store.get_job(nxt).status == "done")
    assert not any(e.kind == "result" and e.job_id == slow for e in events)


class WarmClient(FakeClient):
    def __init__(self, script, log, warmed, fail=False):
        super().__init__(script, log)
        self.warmed, self.fail = warmed, fail

    async def warm(self):
        if self.fail:
            raise RuntimeError("no network")
        self.warmed.append(True)


async def test_prewarm_creates_client_reused_by_next_job(tmp_path):
    store = Store(tmp_path / "j.db")
    made, warmed = [], []

    def factory(project):
        made.append(project.name)
        return WarmClient(lambda p: [("result", "ok", 0)], [], warmed)

    jm = JobManager(store, factory, lambda ev: None)
    await jm.prewarm(A)
    await jm.prewarm(A)
    assert made == ["A"] and warmed == [True]
    jid = jm.submit(A, "task")
    await until(lambda: store.get_job(jid).status == "done")
    assert made == ["A"]


async def test_prewarm_failure_is_swallowed_and_client_dropped(tmp_path):
    store = Store(tmp_path / "j.db")
    made = []

    def factory(project):
        made.append(project.name)
        return WarmClient(lambda p: [("result", "ok", 0)], [], [], fail=len(made) == 1)

    jm = JobManager(store, factory, lambda ev: None)
    await jm.prewarm(A)
    jid = jm.submit(A, "task")
    await until(lambda: store.get_job(jid).status == "done")
    assert made == ["A", "A"]


async def test_cancel_all_and_queued(tmp_path):
    jm, store, _, _, _ = setup(tmp_path, lambda p: [("result", "x", 5)])
    j1 = jm.submit(A, "one")
    j2 = jm.submit(A, "two")
    await until(lambda: store.get_job(j1).status == "running")
    assert sorted(await jm.cancel()) == [j1, j2]
    assert store.active_jobs() == []
    await jm.shutdown()
