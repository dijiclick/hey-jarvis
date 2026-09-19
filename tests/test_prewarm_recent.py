import asyncio
from pathlib import Path
from types import SimpleNamespace

from jarvis.app import JarvisApp
from jarvis.projects import Project
from jarvis.store import Store


class FakeJobs:
    def __init__(self):
        self.warmed = []

    async def prewarm(self, project):
        self.warmed.append(project.name)


def make_app(tmp_path, jobs_made):
    app = JarvisApp(SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120),
                    audio_factory=lambda loop: None)
    app.store = Store(tmp_path / "j.db")
    for project in jobs_made:
        app.store.create_job(project, "/p", "task")
    app.jobs = FakeJobs()
    app.resolver = SimpleNamespace(resolve=lambda name: Project(name, Path("/p")))
    return app


async def test_waking_readies_the_project_used_last(tmp_path):
    app = make_app(tmp_path, ["superpower", "home", "storefront", "home"])
    app._prewarm_recent()
    await asyncio.sleep(0)
    assert app.jobs.warmed == ["storefront"], "home is always warm already; the last real project is storefront"


async def test_nothing_to_ready_without_recent_projects(tmp_path):
    app = make_app(tmp_path, ["home"])
    app._prewarm_recent()
    await asyncio.sleep(0)
    assert app.jobs.warmed == []
