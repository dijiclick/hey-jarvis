import os

from jarvis.projects import Project
from jarvis.store import Store
from jarvis.worker import SESSION_MAX_BYTES, SESSION_MAX_IDLE_S, ClaudeWorker, should_resume

SID = "83fcce6e-8052-44b5-97e5-9fa706611e8f"
NOW = 1_800_000_000.0


def transcript(sessions_dir, size, idle_s):
    """A saved Claude Code session: ~/.claude/projects/<encoded cwd>/<session id>.jsonl"""
    folder = sessions_dir / "-Users-me-Projects-superpower"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{SID}.jsonl"
    path.write_bytes(b"x" * size)
    os.utime(path, (NOW - idle_s, NOW - idle_s))
    return path


def test_a_small_recent_session_is_continued(tmp_path):
    assert should_resume(transcript(tmp_path, 50_000, 600), NOW) is True


def test_a_huge_session_starts_fresh(tmp_path):
    # measured: resuming the 11 MB home session cost 16.9s to the first action against 8.9s fresh
    assert should_resume(transcript(tmp_path, SESSION_MAX_BYTES + 1, 600), NOW) is False


def test_a_session_idle_for_hours_starts_fresh(tmp_path):
    assert should_resume(transcript(tmp_path, 50_000, SESSION_MAX_IDLE_S + 60), NOW) is False


def test_a_missing_transcript_starts_fresh_instead_of_failing_to_resume(tmp_path):
    assert should_resume(tmp_path / "nope.jsonl", NOW) is False


async def deny(_):
    return False


def worker(tmp_path, size, idle_s):
    store = Store(tmp_path / "j.db")
    store.set_session("superpower", SID)
    transcript(tmp_path / "sessions", size, idle_s)
    return ClaudeWorker(Project("superpower", tmp_path), store, deny, browser=False,
                        sessions_dir=tmp_path / "sessions", clock=lambda: NOW)


def test_the_worker_continues_a_small_recent_session(tmp_path):
    assert worker(tmp_path, 50_000, 600)._pick_resume() == SID


def test_the_worker_drops_a_session_that_grew_too_big(tmp_path):
    assert worker(tmp_path, SESSION_MAX_BYTES + 1, 600)._pick_resume() is None
