from types import SimpleNamespace

from jarvis.app import JarvisApp
from jarvis.jobs import JobEvent


def make_app():
    app = JarvisApp(SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120), audio_factory=lambda loop: None)
    asked = []
    app.voice = SimpleNamespace(expect_answer=lambda project, question: asked.append((project, question)))
    return app, asked


async def nothing(ev):
    pass


async def test_a_job_that_ends_with_a_question_waits_for_the_users_answer():
    app, asked = make_app()
    await app._on_job_event(JobEvent(91, "superpower", "result", "Typed it, not sent. Should I press Enter?"), nothing)
    assert asked == [("superpower", "Typed it, not sent. Should I press Enter?")]


async def test_a_plain_result_or_a_failure_waits_for_nothing():
    app, asked = make_app()
    await app._on_job_event(JobEvent(92, "superpower", "result", "Sent. VS Code is answering."), nothing)
    await app._on_job_event(JobEvent(93, "superpower", "failed", "Could it be offline?"), nothing)
    assert asked == []
