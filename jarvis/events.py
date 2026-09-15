"""Live event stream: what Jarvis is doing right now, for the visual panel.

Everything the panel shows (state orb, transcript, jobs, mic level) arrives as events. Publishing never blocks and
never fails: a subscriber that falls behind loses its oldest events instead of stalling the assistant. Publish from
the asyncio loop thread; the audio thread should hand values to the loop first.
"""
import asyncio
import contextlib
import logging
import time
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("jarvis.events")

QUEUE_SIZE = 200
HISTORY = 200


@dataclass
class Event:
    kind: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "ts": self.ts, **self.data}


class EventHub:
    """Fan-out of Jarvis events to any number of subscribers (panel windows, loggers, tests)."""

    def __init__(self, history: int = HISTORY, queue_size: int = QUEUE_SIZE):
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._history: deque[Event] = deque(maxlen=history)
        self._queue_size = queue_size
        self.dropped = 0

    def publish(self, kind: str, **data: Any) -> Event:
        event = Event(kind=kind, data=data)
        self._history.append(event)
        for queue in self._subscribers:
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                self.dropped += 1
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)
        return event

    def recent(self, kinds: tuple[str, ...] | None = None, limit: int = 50) -> list[Event]:
        events = [e for e in self._history if kinds is None or e.kind in kinds]
        return events[-limit:]

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @contextlib.contextmanager
    def subscribe(self) -> Iterator[asyncio.Queue[Event]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._subscribers.add(queue)
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
