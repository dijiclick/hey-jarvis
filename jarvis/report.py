"""Spending and activity report for Jarvis.

Two different numbers, never mixed up:
  - what OpenAI actually billed (needs an org Admin key) — the truth, for everything on the account
  - what Jarvis itself spent on voice, metered locally from session length — an estimate, only for Jarvis
Claude Code runs on the user's subscription, so it adds no per-call charge here.
"""
import datetime as dt
from dataclasses import dataclass

from .spend import Spend, format_spend

VOICE_USD_PER_MIN = 0.05


@dataclass
class Report:
    voice_min_today: float
    voice_min_7d: float
    voice_min_total: float
    jobs_today: int
    jobs_total: int
    jobs_failed_7d: int
    spend: Spend | None = None

    @property
    def cost_today(self) -> float:
        return self.voice_min_today * VOICE_USD_PER_MIN

    @property
    def cost_7d(self) -> float:
        return self.voice_min_7d * VOICE_USD_PER_MIN

    @property
    def cost_total(self) -> float:
        return self.voice_min_total * VOICE_USD_PER_MIN


def _midnight(now: float) -> float:
    return dt.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def build_report(store, now: float, spend: Spend | None = None) -> Report:
    day = _midnight(now)
    week = now - 7 * 86400
    jobs = store.jobs_since(0)
    return Report(
        voice_min_today=store.voice_seconds_since(day) / 60,
        voice_min_7d=store.voice_seconds_since(week) / 60,
        voice_min_total=store.voice_seconds_since(0) / 60,
        jobs_today=sum(1 for j in jobs if j.created >= day),
        jobs_total=len(jobs),
        jobs_failed_7d=sum(1 for j in jobs if j.created >= week and j.status == "failed"),
        spend=spend,
    )


def format_report(r: Report) -> str:
    lines = [
        "Jarvis — spending & activity",
        f"  Today:   {r.voice_min_today:5.1f} voice min  ≈ ${r.cost_today:.2f}   ·  {r.jobs_today} jobs",
        f"  7 days:  {r.voice_min_7d:5.1f} voice min  ≈ ${r.cost_7d:.2f}   ·  {r.jobs_failed_7d} failed",
        f"  Total:   {r.voice_min_total:5.1f} voice min  ≈ ${r.cost_total:.2f}   ·  {r.jobs_total} jobs",
        f"  Jarvis voice estimated at ${VOICE_USD_PER_MIN:.2f}/min. Claude runs on your subscription.",
    ]
    if r.spend is not None:
        lines.append("  " + format_spend(r.spend) + (" (whole OpenAI account)" if r.spend.available else ""))
    return "\n".join(lines)


def format_report_short(r: Report) -> str:
    text = f"Today {r.voice_min_today:.1f} min ≈ ${r.cost_today:.2f} · {r.jobs_today} jobs today"
    if r.spend is not None and r.spend.available:
        text += f" · OpenAI billed ${r.spend.today:.2f}"
    return text
