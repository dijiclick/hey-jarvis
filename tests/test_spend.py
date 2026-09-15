import datetime as dt
import urllib.error

from jarvis.spend import Spend, SpendCache, format_spend, get_spend, parse_costs

NOW = dt.datetime(2026, 9, 14, 15, 0).timestamp()


def day_start(days_back: int) -> int:
    base = dt.datetime(2026, 9, 14).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((base - dt.timedelta(days=days_back)).timestamp())


def bucket(days_back: int, value: float):
    return {"start_time": day_start(days_back),
            "results": [{"amount": {"value": value, "currency": "usd"}}]}


PAYLOAD = {"data": [bucket(20, 1.00), bucket(6, 0.50), bucket(1, 8.89), bucket(0, 0.25), bucket(0, 0.05)]}


def test_parse_splits_today_week_and_month():
    spend = parse_costs(PAYLOAD, NOW)
    assert spend.available is True
    assert spend.today == 0.30          # two buckets on the same day are added together
    assert spend.week == 9.69           # last 7 days, excludes the 20-day-old one
    assert spend.month == 10.69
    assert spend.by_day["2026-09-14"] == 0.30
    assert spend.by_day["2026-09-13"] == 8.89


def test_zero_amounts_are_ignored():
    spend = parse_costs({"data": [bucket(0, 0.0)]}, NOW)
    assert spend.by_day == {} and spend.today == 0.0 and spend.available is True


def test_no_admin_key_is_not_an_error_state():
    spend = get_spend(None, now=NOW)
    assert spend.available is False and spend.error == "no admin key"
    assert "unavailable" in format_spend(spend)


def test_forbidden_key_explains_itself():
    def forbidden(key, start, limit):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

    spend = get_spend("sk-admin-x", now=NOW, fetch=forbidden)
    assert spend.available is False
    assert "api.usage.read" in spend.error


def test_network_failure_degrades_quietly():
    def boom(key, start, limit):
        raise TimeoutError("slow")

    spend = get_spend("sk-admin-x", now=NOW, fetch=boom)
    assert spend.available is False and spend.error == "TimeoutError"


def test_cache_refetches_only_after_ttl():
    calls = []
    clock = [NOW]

    def fetch(key, start, limit):
        calls.append(start)
        return PAYLOAD

    cache = SpendCache("sk-admin-x", ttl_s=100, clock=lambda: clock[0], fetch=fetch)
    assert cache.get().today == 0.30
    cache.get()
    assert len(calls) == 1
    clock[0] += 101
    cache.get()
    assert len(calls) == 2
    cache.get(force=True)
    assert len(calls) == 3


def test_format_reports_the_busiest_day():
    text = format_spend(parse_costs(PAYLOAD, NOW))
    assert "$0.30 today" in text and "$9.69 this week" in text and "$10.69 in 30 days" in text
    assert "Biggest day: 2026-09-13 at $8.89" in text


def test_format_handles_an_empty_but_available_month():
    assert "Biggest day" not in format_spend(Spend(available=True))
