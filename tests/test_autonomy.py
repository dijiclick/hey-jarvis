from jarvis.autonomy import Autonomy
from jarvis.events import EventHub


def test_defaults_then_remembers_the_choice(tmp_path):
    a = Autonomy(tmp_path / "autonomy.json", default="balanced")
    assert a.get() == "balanced"
    a.set("careful")
    assert Autonomy(tmp_path / "autonomy.json", default="balanced").get() == "careful"


def test_rejects_unknown_levels_and_bad_files(tmp_path):
    path = tmp_path / "autonomy.json"
    a = Autonomy(path, default="nonsense")
    assert a.get() == "balanced"
    assert a.set("yolo") is False and a.get() == "balanced"
    path.write_text("{not json")
    assert Autonomy(path, default="full").get() == "full"


def test_a_change_reaches_the_panel(tmp_path):
    hub = EventHub()
    a = Autonomy(tmp_path / "autonomy.json", hub=hub)
    with hub.subscribe() as queue:
        a.set("full")
        event = queue.get_nowait()
    assert event.kind == "autonomy" and event.as_dict()["level"] == "full"
