import asyncio
from types import SimpleNamespace

from jarvis.app import JarvisApp
from jarvis.jobs import JobEvent


def make_app():
    settings = SimpleNamespace(home=None, db_path=":memory:", confirm_timeout_s=120)
    return JarvisApp(settings, audio_factory=lambda loop: None)


async def test_publish_state_reaches_hub_and_menu_bar():
    seen = []
    app = make_app()
    app.on_state = seen.append
    with app.hub.subscribe() as queue:
        app.publish_state("listening")
        event = await queue.get()
    assert event.kind == "state" and event.data == {"value": "listening"}
    assert seen == ["listening"]
    assert app.state == "listening"


async def test_job_events_are_published_and_still_spoken():
    app = make_app()
    spoken = []

    async def speak(ev):
        spoken.append(ev.kind)

    with app.hub.subscribe() as queue:
        await app._on_job_event(JobEvent(7, "ShopFront", "result", "Tests pass."), speak)
        event = await queue.get()
    assert event.kind == "job"
    assert event.data == {"id": 7, "project": "ShopFront", "stage": "result", "text": "Tests pass."}
    assert spoken == ["result"]


async def test_level_meter_publishes_only_while_a_session_is_open():
    app = make_app()
    app.audio = SimpleNamespace(input_level=1234, output_level=567)
    app.voice = SimpleNamespace(is_open=False)
    with app.hub.subscribe() as queue:
        task = asyncio.create_task(app._mic_meter())
        await asyncio.sleep(0.25)
        assert queue.empty()
        app.voice = SimpleNamespace(is_open=True)
        event = await asyncio.wait_for(queue.get(), 1)
        task.cancel()
    assert event.kind == "level" and event.data == {"mic": 1234, "out": 567}
