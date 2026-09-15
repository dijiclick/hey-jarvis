import datetime as dt

import pytest

from jarvis.schedule import Schedule, ScheduleError, describe, next_run, parse_schedule


def at(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi).timestamp()


@pytest.mark.parametrize("text,kind,extra", [
    ("every morning at 9", "daily", {"at": (9, 0)}),
    ("daily 09:30", "daily", {"at": (9, 30)}),
    ("every day at 6pm", "daily", {"at": (18, 0)}),
    ("each day at 12am", "daily", {"at": (0, 0)}),
    ("every evening", "daily", {"at": (19, 0)}),
    ("weekdays at 18:30", "weekdays", {"at": (18, 30)}),
    ("every monday 09:00", "weekly", {"weekday": 0, "at": (9, 0)}),
    ("mondays at 9am", "weekly", {"weekday": 0, "at": (9, 0)}),
    ("every friday evening", "weekly", {"weekday": 4, "at": (19, 0)}),
    ("every 30 minutes", "interval", {"minutes": 30}),
    ("every 2 hours", "interval", {"minutes": 120}),
    ("every hour", "interval", {"minutes": 60}),
])
def test_parse(text, kind, extra):
    s = parse_schedule(text)
    assert s.kind == kind
    for key, value in extra.items():
        assert getattr(s, key) == value
    assert s.text == text


def test_parse_once():
    s = parse_schedule("once 2026-10-01 14:30")
    assert s.kind == "once"
    assert s.when == at(2026, 10, 1, 14, 30)


@pytest.mark.parametrize("text", ["whenever I feel like it", "every 0 minutes", "daily 99:99"])
def test_parse_rejects_nonsense(text):
    with pytest.raises(ScheduleError):
        parse_schedule(text)


def test_daily_next_run_moves_to_tomorrow_once_passed():
    schedule = parse_schedule("every morning at 9")
    assert next_run(schedule, at(2026, 9, 14, 8, 0)) == at(2026, 9, 15 - 1, 9, 0)
    assert next_run(schedule, at(2026, 9, 14, 9, 30)) == at(2026, 9, 15, 9, 0)


def test_interval_next_run():
    assert next_run(parse_schedule("every 30 minutes"), 1000.0) == 1000.0 + 1800


def test_weekdays_skips_the_weekend():
    schedule = parse_schedule("weekdays at 10:00")
    friday_evening = at(2026, 9, 18, 20, 0)          # 2026-09-18 is a Friday
    assert next_run(schedule, friday_evening) == at(2026, 9, 21, 10, 0)   # Monday


def test_weekly_lands_on_the_named_day():
    schedule = parse_schedule("every monday 09:00")
    moment = next_run(schedule, at(2026, 9, 15, 12, 0))   # Tuesday
    assert dt.datetime.fromtimestamp(moment).weekday() == 0
    assert moment == at(2026, 9, 21, 9, 0)


def test_once_expires():
    schedule = Schedule(kind="once", when=at(2026, 9, 14, 10, 0), text="once")
    assert next_run(schedule, at(2026, 9, 14, 9, 0)) == at(2026, 9, 14, 10, 0)
    assert next_run(schedule, at(2026, 9, 14, 11, 0)) is None


@pytest.mark.parametrize("text,expected", [
    ("every morning at 9", "every day at 09:00"),
    ("weekdays at 18:30", "every weekday at 18:30"),
    ("every monday 09:00", "every Monday at 09:00"),
    ("every 30 minutes", "every 30 minutes"),
    ("every 2 hours", "every 2 hours"),
])
def test_describe(text, expected):
    assert describe(parse_schedule(text)) == expected
