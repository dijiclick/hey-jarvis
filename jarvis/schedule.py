"""Schedules you can say out loud.

"every morning at 9", "every 30 minutes", "weekdays at 6pm", "every monday 09:00", "once 2026-10-01 14:00".
Parsing is deliberately forgiving, because these arrive from speech-to-text.
"""
import datetime as dt
import re
from dataclasses import dataclass

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
            "thursday": 3, "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6}
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MORNING, AFTERNOON, EVENING = (9, 0), (14, 0), (19, 0)


@dataclass(frozen=True)
class Schedule:
    kind: str                       # daily | weekdays | weekly | interval | once
    at: tuple[int, int] | None = None   # hour, minute
    weekday: int | None = None
    minutes: int = 0                # for interval
    when: float | None = None       # for once, epoch seconds
    text: str = ""                  # what the user said


class ScheduleError(ValueError):
    pass


def _parse_time(text: str) -> tuple[int, int] | None:
    text = text.strip().lower()
    if "morning" in text:
        return MORNING
    if "afternoon" in text:
        return AFTERNOON
    if "evening" in text or "tonight" in text:
        return EVENING
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", text)
    if not m:
        return None
    hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ScheduleError(f"{hour}:{minute:02d} is not a real time")
    return hour, minute


def parse_schedule(text: str) -> Schedule:
    raw = " ".join(text.split())
    low = raw.lower()

    m = re.search(r"once\s+(\d{4}-\d{2}-\d{2})[ t]+(\d{1,2}:\d{2})", low)
    if m:
        when = dt.datetime.fromisoformat(f"{m.group(1)} {m.group(2)}").timestamp()
        return Schedule(kind="once", when=when, text=raw)

    m = re.search(r"every\s+(\d+)?\s*(minute|minutes|min|hour|hours)\b", low)
    if m:
        count = int(m.group(1) or 1)
        minutes = count * (60 if m.group(2).startswith("hour") else 1)
        if minutes < 1:
            raise ScheduleError("that interval is too short")
        return Schedule(kind="interval", minutes=minutes, text=raw)

    for name, index in WEEKDAYS.items():
        if re.search(rf"\b{name}s?\b", low):
            at = _parse_time(low) or MORNING
            return Schedule(kind="weekly", weekday=index, at=at, text=raw)

    if "weekday" in low or "working day" in low or "workday" in low:
        return Schedule(kind="weekdays", at=_parse_time(low) or MORNING, text=raw)

    at = _parse_time(low)
    if at or "daily" in low or "every day" in low or "each day" in low:
        return Schedule(kind="daily", at=at or MORNING, text=raw)

    raise ScheduleError(f"I couldn't understand the schedule {raw!r}")


def _at_on(day: dt.date, at: tuple[int, int]) -> float:
    return dt.datetime.combine(day, dt.time(at[0], at[1])).timestamp()


def next_run(schedule: Schedule, after: float) -> float | None:
    """First run strictly after `after`; None when a one-off has passed."""
    if schedule.kind == "once":
        return schedule.when if schedule.when and schedule.when > after else None
    if schedule.kind == "interval":
        return after + schedule.minutes * 60

    at = schedule.at or MORNING
    today = dt.datetime.fromtimestamp(after).date()
    for offset in range(0, 8):
        day = today + dt.timedelta(days=offset)
        if schedule.kind == "weekdays" and day.weekday() > 4:
            continue
        if schedule.kind == "weekly" and day.weekday() != schedule.weekday:
            continue
        moment = _at_on(day, at)
        if moment > after:
            return moment
    return None


def describe(schedule: Schedule) -> str:
    at = schedule.at or MORNING
    clock = f"{at[0]:02d}:{at[1]:02d}"
    if schedule.kind == "interval":
        if schedule.minutes % 60 == 0 and schedule.minutes >= 60:
            hours = schedule.minutes // 60
            return f"every {hours} hour{'s' if hours > 1 else ''}"
        return f"every {schedule.minutes} minute{'s' if schedule.minutes > 1 else ''}"
    if schedule.kind == "once":
        return "once at " + dt.datetime.fromtimestamp(schedule.when).strftime("%Y-%m-%d %H:%M")
    if schedule.kind == "weekly":
        return f"every {WEEKDAY_NAMES[schedule.weekday]} at {clock}"
    if schedule.kind == "weekdays":
        return f"every weekday at {clock}"
    return f"every day at {clock}"
