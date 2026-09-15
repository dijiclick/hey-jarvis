from jarvis.profile import (
    full_knowledge_block,
    load_projects,
    profile_block,
    projects_summary,
    remember_fact,
)

PROJECTS_MD = """# Projects

## Dialer  (Dialer)
- what it is: a Turkish phone-sales agent that calls customers and books appointments
- stack: Python, FastAPI, LiveKit
- status: active
- last activity: 2026-09-01
- notable: deploys to a VPS, uses Supabase

## ShopFront  (ShopFront)
- what it is: a fashion storefront with a mobile app and a price collector
- stack: Next.js, pnpm monorepo, Playwright
- status: active
- last activity: 2026-08-29
- notable: has tests, deploys to Vercel

_Generated 2026-09-14_
"""


def test_missing_projects_file_is_empty(tmp_path):
    assert load_projects(tmp_path) == ""
    assert projects_summary(tmp_path) == ""
    assert full_knowledge_block(tmp_path) == ""


def test_summary_is_one_line_per_project(tmp_path):
    (tmp_path / "projects.md").write_text(PROJECTS_MD, encoding="utf-8")
    summary = projects_summary(tmp_path)
    assert summary.splitlines() == [
        "- Dialer: a Turkish phone-sales agent that calls customers and books appointments",
        "- ShopFront: a fashion storefront with a mobile app and a price collector",
    ]
    assert "FastAPI" not in summary          # detail is for Claude, not the voice prompt
    assert len(summary) < len(PROJECTS_MD)


def test_profile_block_carries_the_compact_projects(tmp_path):
    (tmp_path / "projects.md").write_text(PROJECTS_MD, encoding="utf-8")
    remember_fact(tmp_path, "lives in Lisbon")
    block = profile_block(tmp_path)
    assert "lives in Lisbon" in block
    assert "The user's projects:" in block and "- Dialer:" in block
    assert "Supabase" not in block
    assert "Supabase" not in profile_block(tmp_path, projects=False)


def test_full_knowledge_block_keeps_every_detail(tmp_path):
    (tmp_path / "projects.md").write_text(PROJECTS_MD, encoding="utf-8")
    remember_fact(tmp_path, "lives in Lisbon")
    full = full_knowledge_block(tmp_path)
    assert "lives in Lisbon" in full
    assert "Supabase" in full and "pnpm monorepo" in full
