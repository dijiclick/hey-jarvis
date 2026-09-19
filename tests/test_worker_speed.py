from jarvis.projects import Project
from jarvis.store import Store
from jarvis.worker import ClaudeWorker


async def deny(_):
    return False


def options(tmp_path, **speed):
    return ClaudeWorker(Project("home", tmp_path), Store(tmp_path / "j.db"), deny, browser=False, **speed)._options(None)


def test_voice_jobs_run_on_the_configured_model_and_effort(tmp_path):
    # measured: sonnet at low effort reached the first action in 3.8s against 5.5s for high effort
    o = options(tmp_path, model="sonnet", effort="low")
    assert (o.model, o.effort) == ("sonnet", "low")


def test_without_settings_claude_code_keeps_its_own_defaults(tmp_path):
    o = options(tmp_path)
    assert (o.model, o.effort) == (None, None)


def test_the_app_hands_the_configured_speed_to_every_job(tmp_path):
    from types import SimpleNamespace

    from jarvis.app import JarvisApp

    settings = SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120,
                               claude_model="sonnet", claude_effort="low")
    app = JarvisApp(settings, audio_factory=lambda loop: None)
    app.store, app.broker = Store(tmp_path / "j.db"), SimpleNamespace(confirm=deny)
    o = app._make_worker(Project("home", tmp_path))._options(None)
    assert (o.model, o.effort) == ("sonnet", "low")
