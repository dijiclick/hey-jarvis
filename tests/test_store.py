from jarvis.store import Store


def test_job_lifecycle(tmp_path):
    s = Store(tmp_path / "j.db")
    jid = s.create_job("ShopFront", "/p", "fix login")
    assert s.get_job(jid).status == "queued"
    s.set_status(jid, "running")
    s.add_event(jid, "progress", "Running: npm test")
    s.set_status(jid, "done", "Fixed.")
    job = s.get_job(jid)
    assert (job.status, job.result) == ("done", "Fixed.")
    assert job.finished is not None
    assert s.recent_events(jid) == ["Running: npm test"]


def test_active_and_since(tmp_path):
    s = Store(tmp_path / "j.db")
    a = s.create_job("A", "/a", "t1")
    b = s.create_job("B", "/b", "t2")
    s.set_status(b, "done", "ok")
    assert [j.id for j in s.active_jobs()] == [a]
    assert {j.id for j in s.jobs_since(0)} == {a, b}


def test_fail_stale_jobs(tmp_path):
    s = Store(tmp_path / "j.db")
    a = s.create_job("A", "/a", "t1")
    b = s.create_job("A", "/a", "t2")
    s.set_status(b, "running")
    assert s.fail_stale_jobs() == 2
    assert {s.get_job(a).status, s.get_job(b).status} == {"failed"}


def test_voice_seconds_since(tmp_path):
    s = Store(tmp_path / "j.db")
    s.add_voice_session(100, 160)
    s.add_voice_session(190, 220)
    assert s.voice_seconds_since(0) == 90
    assert s.voice_seconds_since(200) == 20
    assert s.voice_seconds_since(300) == 0


def test_sessions_and_transcripts(tmp_path):
    s = Store(tmp_path / "j.db")
    assert s.get_session("A") is None
    s.set_session("A", "sess-1")
    s.set_session("A", "sess-2")
    assert s.get_session("A") == "sess-2"
    s.add_transcript("user", "merhaba dünya")
    s.add_transcript("assistant", "hi")
    assert s.recent_transcripts(10) == [("user", "merhaba dünya"), ("assistant", "hi")]
