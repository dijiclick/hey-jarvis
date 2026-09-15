"""Routines: work that happens on its own, without being asked.

A routine is a saved task plus a schedule. When it comes due the scheduler submits it as a normal Claude job, so
it reports back by voice through the same path as anything else you ask for.
"""
import asyncio
import logging
import time
from collections.abc import Callable

from .schedule import ScheduleError, describe, next_run, parse_schedule
from .store import Routine, Store

log = logging.getLogger("jarvis.scheduler")

TICK_S = 20.0
# a routine that was due while the Mac was asleep runs once on wake, not once per missed slot
LATE_GRACE_S = 3600.0


def plan_next(schedule_text: str, after: float) -> float | None:
    return next_run(parse_schedule(schedule_text), after)


class Scheduler:
    def __init__(self, store: Store, submit: Callable[[Routine], None], hub=None,
                 clock: Callable[[], float] = time.time, tick_s: float = TICK_S):
        self.store = store
        self.submit = submit
        self.hub = hub
        self.clock = clock
        self.tick_s = tick_s

    def add(self, name: str, schedule_text: str, task: str, project: str | None = None) -> str:
        """Save a routine; raises ScheduleError when the schedule makes no sense."""
        schedule = parse_schedule(schedule_text)
        when = next_run(schedule, self.clock())
        if when is None:
            raise ScheduleError("that time has already passed")
        self.store.add_routine(name, schedule_text, task, project, when)
        return describe(schedule)

    def run_due(self) -> list[Routine]:
        """Submit everything due now and set each routine's next time. Returns what was started."""
        now = self.clock()
        started = []
        for routine in self.store.due_routines(now):
            try:
                upcoming = plan_next(routine.schedule, now)
            except ScheduleError:
                log.warning("routine %r has an unreadable schedule %r; disabling it", routine.name, routine.schedule)
                self.store.mark_routine_run(routine.id, now, None)
                continue
            self.store.mark_routine_run(routine.id, now, upcoming)
            if routine.next_run is not None and now - routine.next_run > LATE_GRACE_S:
                log.info("routine %r was very late (Mac asleep?); running it once now", routine.name)
            try:
                self.submit(routine)
            except Exception:
                log.exception("could not start routine %r", routine.name)
                continue
            started.append(routine)
            if self.hub is not None:
                self.hub.publish("routine", name=routine.name, task=routine.task, project=routine.project)
            log.info("routine %r started", routine.name)
        return started

    async def loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                self.run_due()
            except Exception:
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(stop.wait(), timeout=self.tick_s)
            except asyncio.TimeoutError:
                pass
