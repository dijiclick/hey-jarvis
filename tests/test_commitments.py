import datetime as dt

from jarvis.commitments import (
    add_commitment,
    commitments_path,
    complete_commitment,
    load_commitments,
    open_commitments,
    overdue,
)

TODAY = dt.date(2026, 9, 14)


def test_missing_file_is_empty(tmp_path):
    assert load_commitments(tmp_path) == ""
    assert open_commitments(tmp_path) == []
    assert overdue(tmp_path, TODAY) == []


def test_add_writes_a_dated_open_item(tmp_path):
    assert add_commitment(tmp_path, "send 10 outreach emails", TODAY) == "2026-09-14 — send 10 outreach emails"
    text = commitments_path(tmp_path).read_text()
    assert text.startswith("# Commitments")
    assert "- [ ] 2026-09-14 — send 10 outreach emails" in text
    assert open_commitments(tmp_path) == ["2026-09-14 — send 10 outreach emails"]


def test_add_ignores_empties_and_duplicates(tmp_path):
    add_commitment(tmp_path, "send 10 outreach emails", TODAY)
    add_commitment(tmp_path, "Send 10 outreach emails", TODAY)
    assert add_commitment(tmp_path, "   ") == ""
    assert len(open_commitments(tmp_path)) == 1


def test_complete_ticks_the_matching_item(tmp_path):
    add_commitment(tmp_path, "send 10 outreach emails", TODAY)
    add_commitment(tmp_path, "call the supplier", TODAY)
    assert complete_commitment(tmp_path, "outreach") == "2026-09-14 — send 10 outreach emails"
    assert open_commitments(tmp_path) == ["2026-09-14 — call the supplier"]
    assert "- [x] 2026-09-14 — send 10 outreach emails" in commitments_path(tmp_path).read_text()


def test_complete_returns_none_when_nothing_matches(tmp_path):
    add_commitment(tmp_path, "call the supplier", TODAY)
    assert complete_commitment(tmp_path, "invoices") is None
    assert complete_commitment(tmp_path, "") is None
    assert len(open_commitments(tmp_path)) == 1


def test_overdue_only_counts_earlier_days(tmp_path):
    add_commitment(tmp_path, "yesterday's promise", dt.date(2026, 9, 13))
    add_commitment(tmp_path, "today's promise", TODAY)
    assert overdue(tmp_path, TODAY) == ["2026-09-13 — yesterday's promise"]


def test_completed_items_are_not_overdue(tmp_path):
    add_commitment(tmp_path, "old thing", dt.date(2026, 9, 1))
    complete_commitment(tmp_path, "old thing")
    assert overdue(tmp_path, TODAY) == []
