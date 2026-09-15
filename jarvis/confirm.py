import asyncio
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable

YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "approve", "approved",
             "بله", "آره", "اره", "آری", "باشه", "بزن", "اوکی", "evet", "tamam"}
YES_PHRASES = ("go ahead", "do it", "انجام بده")
NO_WORDS = {"no", "nope", "cancel", "stop", "dont", "نه", "خیر", "نکن", "نزن", "hayır", "hayir", "iptal"}


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", text).lower()
    return s.replace("‌", " ").replace("ي", "ی").replace("ك", "ک").replace("'", "").replace("’", "")


def parse_answer(text: str) -> bool | None:
    s = _normalize(text)
    words = set(re.findall(r"\w+", s))
    if words & NO_WORDS:
        return False
    if words & YES_WORDS or any(p in s for p in YES_PHRASES):
        return True
    return None


class ConfirmationBroker:
    def __init__(self, ask: Callable[[str], Awaitable[None]], timeout_s: float,
                 clock: Callable[[], float] = time.monotonic):
        self._ask = ask
        self._timeout_s = timeout_s
        self._clock = clock
        self._lock = asyncio.Lock()
        self._future: asyncio.Future[bool] | None = None
        self._answered_at: float | None = None

    @property
    def pending(self) -> bool:
        return self._future is not None and not self._future.done()

    def answered_within(self, seconds: float) -> bool:
        return self._answered_at is not None and self._clock() - self._answered_at <= seconds

    async def confirm(self, summary: str) -> bool:
        async with self._lock:
            self._future = asyncio.get_running_loop().create_future()
            try:
                await self._ask(summary)
                return await asyncio.wait_for(asyncio.shield(self._future), self._timeout_s)
            except asyncio.TimeoutError:
                return False
            finally:
                self._future = None

    def offer(self, user_text: str) -> bool:
        if not self.pending:
            return False
        answer = parse_answer(user_text)
        if answer is None:
            return False
        self._answered_at = self._clock()
        self._future.set_result(answer)
        return True
