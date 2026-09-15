import time

from jarvis.report import build_report, format_report, format_report_short
from jarvis.spend import Spend
from jarvis.store import Store


def test_build_report_counts_voice_and_jobs(tmp_path):
    s = Store(tmp_path / "j.db")
    now = time.time()
    s.add_voice_session(now - 100, now - 40)   # 60s today
    s.add_voice_session(now - 3 * 86400, now - 3 * 86400 + 120)  # 120s within 7d, not today
    a = s.create_job("A", "/a", "t1")
    s.set_status(a, "done", "ok")
    old = s.create_job("B", "/b", "t2")
    s.set_status(old, "failed", "boom")

    r = build_report(s, now)
    assert round(r.voice_min_today, 2) == 1.0
    assert round(r.voice_min_7d, 2) == 3.0
    assert round(r.cost_today, 4) == 0.05
    assert r.jobs_today == 2
    assert r.jobs_total == 2
    assert r.jobs_failed_7d == 1
    assert r.spend is None


def test_format_report_without_billing_keeps_the_estimate_wording(tmp_path):
    s = Store(tmp_path / "j.db")
    text = format_report(build_report(s, time.time()))
    assert "estimated at" in text
    assert "$0.00" in text
    assert "OpenAI billed" not in text


def test_format_report_adds_real_billing_when_available(tmp_path):
    s = Store(tmp_path / "j.db")
    spend = Spend(today=1.83, week=8.94, month=14.98, available=True, by_day={"2026-09-13": 8.89})
    text = format_report(build_report(s, time.time(), spend=spend))
    assert "OpenAI billed $1.83 today" in text
    assert "whole OpenAI account" in text


def test_format_report_says_when_billing_is_unavailable(tmp_path):
    s = Store(tmp_path / "j.db")
    text = format_report(build_report(s, time.time(), spend=Spend(error="no admin key")))
    assert "billing unavailable" in text
    assert "whole OpenAI account" not in text


def test_format_report_short(tmp_path):
    s = Store(tmp_path / "j.db")
    now = time.time()
    s.add_voice_session(now - 60, now)
    short = format_report_short(build_report(s, now))
    assert "Today 1.0 min" in short and "OpenAI billed" not in short

    with_spend = format_report_short(build_report(s, now, spend=Spend(today=1.83, available=True)))
    assert "OpenAI billed $1.83" in with_spend
