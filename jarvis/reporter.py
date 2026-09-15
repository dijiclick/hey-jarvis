import logging
from collections.abc import Awaitable, Callable

from .jobs import JobEvent
from .speech_text import spoken_text

log = logging.getLogger("jarvis.reporter")

# a routine that found nothing says so in one of these ways; none of it is worth opening a billed session for
NOTHING_MARKERS = ("silent", "no new leads", "nothing to report", "nothing open today",
                   "no changes", "nothing new", "هیچی نیست", "خبری نیست")


def is_nothing_to_say(result: str) -> bool:
    """True when a job's result carries no news, so Jarvis should not speak it."""
    text = " ".join(result.split()).strip().strip(".!،؛").lower()
    if not text:
        return True
    if text in NOTHING_MARKERS:
        return True
    # allow a little politeness around the marker, but never a long answer that merely contains the phrase
    return len(text) <= 60 and any(marker in text for marker in NOTHING_MARKERS)


class Reporter:
    def __init__(self, speak: Callable[[str], Awaitable[None]], notifier, is_away: Callable[[], bool]):
        self.speak = speak
        self.notifier = notifier
        self.is_away = is_away

    async def _safe(self, coro) -> None:
        try:
            await coro
        except Exception:
            log.exception("reporter output failed")

    async def on_event(self, ev: JobEvent) -> None:
        if ev.kind not in ("result", "failed"):
            return
        ok = ev.kind == "result"
        text = spoken_text(ev.text)
        report = f"Job {ev.job_id} in {ev.project} {'finished' if ok else 'failed'}. {text}"
        await self._safe(self.notifier.desktop(f"Jarvis · {ev.project}", text))
        if self.is_away():
            await self._safe(self.notifier.telegram(f"{'✅' if ok else '❌'} {ev.project}\n{ev.text[:3500]}"))
        if ok and is_nothing_to_say(ev.text):
            # speaking costs money by the second: a scheduled check with no news stays quiet
            log.info("job %s had nothing to report; staying silent", ev.job_id)
            return
        await self._safe(self.speak(report))
