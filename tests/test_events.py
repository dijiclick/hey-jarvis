import asyncio

from jarvis.events import EventHub


async def test_publish_reaches_every_subscriber():
    hub = EventHub()
    with hub.subscribe() as a, hub.subscribe() as b:
        hub.publish("state", value="listening")
        first, second = await a.get(), await b.get()
    assert first.kind == "state" and first.data == {"value": "listening"}
    assert second is first
    assert hub.subscriber_count == 0


async def test_event_as_dict_is_flat_for_json():
    hub = EventHub()
    event = hub.publish("transcript", role="user", text="merhaba dünya")
    payload = event.as_dict()
    assert payload["kind"] == "transcript" and payload["role"] == "user" and payload["text"] == "merhaba dünya"
    assert isinstance(payload["ts"], float)


async def test_recent_history_is_kept_for_late_subscribers():
    hub = EventHub(history=3)
    for i in range(5):
        hub.publish("job", id=i)
    hub.publish("state", value="idle")
    assert [e.data["id"] for e in hub.recent(kinds=("job",))] == [3, 4]
    assert len(hub.recent()) == 3


async def test_slow_subscriber_drops_oldest_instead_of_blocking():
    hub = EventHub(queue_size=2)
    with hub.subscribe() as queue:
        for i in range(5):
            hub.publish("job", id=i)
        assert queue.qsize() == 2
        assert [(await queue.get()).data["id"] for _ in range(2)] == [3, 4]
    assert hub.dropped == 3


async def test_unsubscribe_happens_even_on_error():
    hub = EventHub()
    with __import__("pytest").raises(RuntimeError):
        with hub.subscribe():
            raise RuntimeError("boom")
    assert hub.subscriber_count == 0
    hub.publish("state", value="idle")  # must not raise with no subscribers


async def test_publish_is_safe_with_no_subscribers():
    hub = EventHub()
    assert hub.publish("mic", peak=120).data == {"peak": 120}
    await asyncio.sleep(0)
