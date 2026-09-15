from jarvis.jobs import JobEvent
from jarvis.reporter import Reporter


class FakeNotifier:
    def __init__(self):
        self.desktop_calls, self.telegram_calls = [], []

    async def desktop(self, title, body):
        self.desktop_calls.append((title, body))

    async def telegram(self, text):
        self.telegram_calls.append(text)
        return True


def make(away=False, fail_speak=False):
    spoken, n = [], FakeNotifier()

    async def speak(text):
        if fail_speak:
            raise RuntimeError("voice down")
        spoken.append(text)

    return Reporter(speak=speak, notifier=n, is_away=lambda: away), spoken, n


async def test_result_speaks_and_notifies_desktop_only_when_present():
    r, spoken, n = make()
    await r.on_event(JobEvent(3, "ShopFront", "result", "Fixed **login**. Tests pass."))
    assert "ShopFront" in spoken[0] and "Fixed login. Tests pass." in spoken[0]
    assert n.desktop_calls == [("Jarvis · ShopFront", "Fixed login. Tests pass.")]
    assert n.telegram_calls == []


async def test_away_also_sends_telegram():
    r, _, n = make(away=True)
    await r.on_event(JobEvent(3, "ShopFront", "result", "Fixed."))
    assert n.telegram_calls[0].startswith("✅ ShopFront")


async def test_failed_wording():
    r, spoken, n = make(away=True)
    await r.on_event(JobEvent(4, "A", "failed", "WorkerError: rate limited"))
    assert "failed" in spoken[0]
    assert n.telegram_calls[0].startswith("❌ A")


async def test_progress_started_cancelled_are_silent():
    r, spoken, n = make()
    for kind in ("progress", "started", "cancelled"):
        await r.on_event(JobEvent(1, "A", kind, "x"))
    assert spoken == [] and n.desktop_calls == []


async def test_speak_error_is_swallowed():
    r, _, n = make(fail_speak=True)
    await r.on_event(JobEvent(1, "A", "result", "ok"))
    assert n.desktop_calls
