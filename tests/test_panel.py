import datetime as dt
import time

import aiohttp

from jarvis.events import EventHub
from jarvis.panel import PanelServer, snapshot
from jarvis.store import Store


def make_store(tmp_path):
    store = Store(tmp_path / "j.db")
    running = store.create_job("ShopFront", "/p", "fix the login bug")
    store.set_status(running, "running")
    store.add_event(running, "progress", "Running: npm test")
    done = store.create_job("home", "/h", "what time is it")
    store.set_status(done, "done", "It is 14:05.")
    store.add_transcript("user", "hello Jarvis")
    store.add_transcript("assistant", "at your service")
    store.add_voice_session(time.time() - 120, time.time() - 60)
    return store


PROJECTS_MD = """# Projects

## Harbor  (Harbor)
- what it is: a dental-clinic operations app
- stack: Turborepo, React, Supabase
- status: active
- last activity: 2026-09-09

## payroll  (Labs/payroll)
- what it is: unclear beyond what the scripts show
- status: paused
- last activity: 2026-05-02
"""


def test_parse_projects_reads_the_survey(tmp_path):
    from jarvis.panel import parse_projects

    (tmp_path / "projects.md").write_text(PROJECTS_MD, encoding="utf-8")
    projects = parse_projects(tmp_path)
    assert [p["name"] for p in projects] == ["Harbor", "payroll"]
    assert projects[0]["what"] == "a dental-clinic operations app"
    assert projects[0]["status"] == "active" and projects[0]["last"] == "2026-09-09"
    assert projects[1]["status"] == "paused"
    assert parse_projects(None) == [] and parse_projects(tmp_path / "nope") == []


def test_snapshot_shows_data_not_chat(tmp_path):
    from jarvis.commitments import add_commitment
    from jarvis.spend import Spend

    store = make_store(tmp_path)
    (tmp_path / "projects.md").write_text(PROJECTS_MD, encoding="utf-8")
    add_commitment(tmp_path, "send 10 outreach emails")
    store.add_routine("morning brief", "every day at 09:00", "brief me", None, 2_000_000_000.0)
    spend = Spend(today=1.83, week=10.77, month=16.82, available=True,
                  by_day={"2026-09-13": 8.89, "2026-09-14": 1.83})

    snap = snapshot("idle", store, time.time(), spend=spend, home=tmp_path)
    assert "transcripts" not in snap
    assert [p["name"] for p in snap["projects"]] == ["Harbor", "payroll"]
    assert snap["commitments"] == [f"{dt.date.today().isoformat()} — send 10 outreach emails"]
    assert [r["name"] for r in snap["routines"]] == ["morning brief"]
    assert snap["spend"]["week"] == 10.77
    assert snap["spend"]["by_day"][-1] == {"day": "2026-09-14", "value": 1.83}


def test_snapshot_without_an_admin_key_has_no_spend_block(tmp_path):
    store = make_store(tmp_path)
    assert snapshot("idle", store, time.time(), home=tmp_path)["spend"] is None


def test_snapshot_carries_real_billing_when_available(tmp_path):
    from jarvis.spend import Spend

    store = make_store(tmp_path)
    billed = snapshot("idle", store, time.time(), spend=Spend(today=1.83, available=True))
    assert billed["today"]["billed"] == 1.83

    # without an Admin key the panel must show no figure rather than a made-up one
    assert snapshot("idle", store, time.time())["today"]["billed"] is None
    assert snapshot("idle", store, time.time(), spend=Spend(error="no admin key"))["today"]["billed"] is None


def test_snapshot_has_everything_the_panel_needs(tmp_path):
    store = make_store(tmp_path)
    snap = snapshot("listening", store, time.time())
    assert snap["kind"] == "snapshot" and snap["state"] == "listening"
    assert [j["project"] for j in snap["active"]] == ["ShopFront"]
    assert snap["active"][0]["steps"] == ["Running: npm test"]
    assert [j["status"] for j in snap["recent"]] == ["done"]
    assert snap["today"]["minutes"] == 1.0 and snap["today"]["jobs"] == 2


async def test_server_serves_the_page_and_streams_events(tmp_path):
    store = make_store(tmp_path)
    hub = EventHub()
    server = PanelServer(hub, store, lambda: "idle", port=0)
    assert await server.start() is True
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(server.url) as resp:
                body = await resp.text()
            assert resp.status == 200
            assert "<canvas" in body and "Jarvis" in body

            async with session.ws_connect(server.url + "ws") as ws:
                first = await ws.receive_json(timeout=5)
                assert first["kind"] == "snapshot" and first["state"] == "idle"
                hub.publish("state", value="speaking")
                event = await ws.receive_json(timeout=5)
                assert event["kind"] == "state" and event["value"] == "speaking"
                hub.publish("transcript", role="user", text="merhaba dünya")
                event = await ws.receive_json(timeout=5)
                assert event["text"] == "merhaba dünya"
    finally:
        await server.stop()


async def test_port_in_use_does_not_crash_jarvis(tmp_path):
    store = make_store(tmp_path)
    first = PanelServer(EventHub(), store, lambda: "idle", port=0)
    assert await first.start() is True
    try:
        clash = PanelServer(EventHub(), store, lambda: "idle", port=first.port)
        assert await clash.start() is False
    finally:
        await first.stop()
