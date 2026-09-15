import asyncio
import datetime as dt

import pytest

from jarvis.schedule import ScheduleError
from jarvis.scheduler import Scheduler
from jarvis.store import Store

# a real "now", because one-off schedules are absolute dates; a 1970 fake clock would leave them all in the future
NOW = dt.datetime(2026, 9, 14, 12, 0).timestamp()
PAST_ONE_OFF = "once 2026-09-13 09:00"
FUTURE_ONE_OFF = "once 2026-09-15 14:00"
DUE = NOW - 60        # a routine whose moment has arrived
NOT_YET = NOW + 3600  # one that is still waiting


def make(tmp_path, now=NOW):
    store = Store(tmp_path / "j.db")
    submitted = []
    clock = [now]
    sched = Scheduler(store, submitted.append, clock=lambda: clock[0], tick_s=0.01)
    return store, sched, submitted, clock


def test_add_saves_a_routine_and_describes_it(tmp_path):
    store, sched, _, _ = make(tmp_path)
    assert sched.add("morning tests", "every morning at 9", "run tests", "ShopFront") == "every day at 09:00"
    routine = store.get_routine("morning tests")
    assert routine.task == "run tests" and routine.project == "ShopFront"
    assert routine.next_run > NOW


def test_add_rejects_nonsense_and_past_one_offs(tmp_path):
    _, sched, _, _ = make(tmp_path)
    with pytest.raises(ScheduleError):
        sched.add("bad", "whenever", "x")
    with pytest.raises(ScheduleError):
        sched.add("past", PAST_ONE_OFF, "x")


def test_run_due_submits_only_what_is_due_and_reschedules(tmp_path):
    store, sched, submitted, _ = make(tmp_path)
    store.add_routine("due", "every 30 minutes", "check leads", None, DUE)
    store.add_routine("later", "every 30 minutes", "not yet", None, NOT_YET)

    started = sched.run_due()
    assert [r.name for r in started] == ["due"]
    assert [r.name for r in submitted] == ["due"]
    assert store.get_routine("due").next_run == NOW + 1800
    assert store.get_routine("due").last_run == NOW

    assert sched.run_due() == []          # not due again yet
    assert len(submitted) == 1


def test_a_spent_one_off_is_disabled_after_running(tmp_path):
    # its moment has arrived and passed, which is how a one-off looks by the time it runs
    store, sched, submitted, _ = make(tmp_path)
    store.add_routine("one off", PAST_ONE_OFF, "do it", None, DUE)
    sched.run_due()
    assert [r.name for r in submitted] == ["one off"]
    routine = store.get_routine("one off")
    assert routine.enabled is False and routine.next_run is None


def test_unreadable_schedule_is_disabled_not_crashing(tmp_path):
    store, sched, submitted, _ = make(tmp_path)
    store.add_routine("broken", "gibberish", "x", None, DUE)
    assert sched.run_due() == []
    assert store.get_routine("broken").enabled is False
    assert submitted == []


def test_a_failing_submit_does_not_stop_the_others(tmp_path):
    store = Store(tmp_path / "j.db")
    seen = []

    def submit(routine):
        seen.append(routine.name)
        if routine.name == "boom":
            raise RuntimeError("no worker")

    sched = Scheduler(store, submit, clock=lambda: NOW)
    store.add_routine("boom", "every 30 minutes", "x", None, DUE - 10)
    store.add_routine("fine", "every 30 minutes", "y", None, DUE)
    started = sched.run_due()
    assert seen == ["boom", "fine"]
    assert [r.name for r in started] == ["fine"]
    assert store.get_routine("boom").next_run == NOW + 1800   # still rescheduled


async def test_loop_ticks_until_stopped(tmp_path):
    store, sched, submitted, _ = make(tmp_path)
    store.add_routine("tick", "every 30 minutes", "x", None, DUE)
    stop = asyncio.Event()
    task = asyncio.create_task(sched.loop(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, 2)
    assert [r.name for r in submitted] == ["tick"]


def test_routine_events_reach_the_panel(tmp_path):
    from jarvis.events import EventHub

    store = Store(tmp_path / "j.db")
    hub = EventHub()
    sched = Scheduler(store, lambda r: None, hub=hub, clock=lambda: NOW)
    store.add_routine("brief", "every morning at 9", "daily brief", None, DUE)
    sched.run_due()
    assert [e.data["name"] for e in hub.recent(kinds=("routine",))] == ["brief"]
