from types import SimpleNamespace

from jarvis.app import JarvisApp
from jarvis.jobs import JobEvent


def make_app():
    app = JarvisApp(SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120),
                    audio_factory=lambda loop: None)
    sent = []

    async def telegram(text):
        sent.append(text)
        return True

    app.notifier = SimpleNamespace(telegram=telegram)
    return app, sent


async def test_a_job_ordered_from_the_phone_reports_back_to_the_phone_not_aloud():
    app, sent = make_app()
    app.telegram_jobs.add(41)
    spoken = []

    async def speak(ev):
        spoken.append(ev)

    await app._on_job_event(JobEvent(41, "home", "result", "Two new leads: Ali and Reza."), speak)
    assert sent and "Two new leads: Ali and Reza." in sent[0]
    assert spoken == [], "nobody is at the Mac to hear it, and speaking opens a billed voice line"
    assert 41 not in app.telegram_jobs


async def test_a_job_started_by_voice_is_still_spoken():
    app, sent = make_app()
    spoken = []

    async def speak(ev):
        spoken.append(ev)

    await app._on_job_event(JobEvent(42, "home", "result", "Tests pass."), speak)
    assert spoken and sent == []
