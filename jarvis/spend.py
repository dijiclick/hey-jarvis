"""Real money: what OpenAI actually billed.

The ordinary project key cannot read billing (403, missing api.usage.read), so this uses the org Admin key from
OPENAI_ADMIN_KEY. Without it, Jarvis falls back to its own local estimate rather than pretending to know.
"""
import datetime as dt
import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("jarvis.spend")

COSTS_URL = "https://api.openai.com/v1/organization/costs"
CACHE_S = 900.0        # billing moves slowly; don't hammer it from the panel
TIMEOUT_S = 25.0


@dataclass
class Spend:
    today: float = 0.0
    week: float = 0.0
    month: float = 0.0
    currency: str = "usd"
    by_day: dict[str, float] = field(default_factory=dict)
    available: bool = False
    error: str = ""


def _midnight(now: float, days_back: int = 0) -> float:
    day = dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    return (day - dt.timedelta(days=days_back)).timestamp()


def fetch_costs(admin_key: str, start_time: int, limit: int = 31) -> dict:
    """Raw daily cost buckets from OpenAI. Raises urllib errors; callers decide what to do."""
    url = f"{COSTS_URL}?start_time={start_time}&limit={limit}"
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {admin_key}"})
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
        return json.load(response)


def parse_costs(payload: dict, now: float) -> Spend:
    spend = Spend(available=True)
    today_start, week_start = _midnight(now), _midnight(now, 6)
    for bucket in payload.get("data", []):
        start = bucket.get("start_time", 0)
        day = dt.datetime.fromtimestamp(start).strftime("%Y-%m-%d")
        for result in bucket.get("results", []):
            amount = result.get("amount") or {}
            value = float(amount.get("value") or 0.0)
            if not value:
                continue
            spend.currency = amount.get("currency", spend.currency)
            spend.by_day[day] = round(spend.by_day.get(day, 0.0) + value, 6)
            spend.month += value
            if start >= week_start:
                spend.week += value
            if start >= today_start:
                spend.today += value
    for name in ("today", "week", "month"):
        setattr(spend, name, round(getattr(spend, name), 4))
    return spend


def get_spend(admin_key: str | None, now: float | None = None,
              fetch: Callable[[str, int, int], dict] = fetch_costs) -> Spend:
    """Costs for today, the last 7 days and the last 30. Never raises."""
    now = now or time.time()
    if not admin_key:
        return Spend(error="no admin key")
    try:
        # 30 days back plus today is 31 buckets; ask for more so today's is never the one cut off
        payload = fetch(admin_key, int(_midnight(now, 30)), 40)
    except urllib.error.HTTPError as e:
        detail = "forbidden — the key lacks api.usage.read" if e.code == 403 else f"HTTP {e.code}"
        log.warning("could not read OpenAI costs: %s", detail)
        return Spend(error=detail)
    except Exception as e:
        log.warning("could not read OpenAI costs: %s", e)
        return Spend(error=type(e).__name__)
    return parse_costs(payload, now)


class SpendCache:
    """Keeps the last reading for a while, so the panel and the brief don't each hit the API."""

    def __init__(self, admin_key: str | None, ttl_s: float = CACHE_S,
                 clock: Callable[[], float] = time.time, fetch: Callable[..., dict] = fetch_costs):
        self.admin_key = admin_key
        self.ttl_s = ttl_s
        self.clock = clock
        self.fetch = fetch
        self._value: Spend | None = None
        self._at = 0.0

    def get(self, force: bool = False) -> Spend:
        now = self.clock()
        if force or self._value is None or now - self._at >= self.ttl_s:
            self._value = get_spend(self.admin_key, now=now, fetch=self.fetch)
            self._at = now
        return self._value


def format_spend(spend: Spend) -> str:
    if not spend.available:
        return f"OpenAI billing unavailable ({spend.error})."
    sign = "$" if spend.currency == "usd" else f"{spend.currency} "
    busiest = max(spend.by_day.items(), key=lambda kv: kv[1], default=None)
    line = f"OpenAI billed {sign}{spend.today:.2f} today, {sign}{spend.week:.2f} this week, {sign}{spend.month:.2f} in 30 days."
    if busiest and busiest[1] > 0:
        line += f" Biggest day: {busiest[0]} at {sign}{busiest[1]:.2f}."
    return line
