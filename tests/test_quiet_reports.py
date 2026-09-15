import pytest

from jarvis.jobs import JobEvent
from jarvis.reporter import Reporter, is_nothing_to_say


class FakeNotifier:
    def __init__(self):
        self.desktop_calls, self.telegram_calls = [], []

    async def desktop(self, title, body):
        self.desktop_calls.append((title, body))

    async def telegram(self, text):
        self.telegram_calls.append(text)
        return True


def make(away=False):
    spoken, n = [], FakeNotifier()

    async def speak(text):
        spoken.append(text)

    return Reporter(speak=speak, notifier=n, is_away=lambda: away), spoken, n


@pytest.mark.parametrize("result", [
    "SILENT",
    "silent.",
    "No new leads",
    "no new leads.",
    "Nothing to report.",
    "nothing open today",
    "خبری نیست",
    "",
    "   ",
])
def test_nothing_to_say_is_recognised(result):
    assert is_nothing_to_say(result) is True


@pytest.mark.parametrize("result", [
    "Two leads: Ali asking about bulk pricing, and a quote request from Reza.",
    "Fixed the login bug in ShopFront; all 42 tests pass.",
    "There is nothing new in the repo, but the deploy failed and needs your attention today.",
    "I checked and there were no new leads, however your Vercel build is broken and the site is down.",
])
def test_real_news_is_still_spoken(result):
    assert is_nothing_to_say(result) is False


async def test_a_quiet_routine_does_not_open_a_billed_session():
    reporter, spoken, notifier = make()
    await reporter.on_event(JobEvent(9, "home", "result", "SILENT"))
    assert spoken == [], "speaking costs money by the second"
    assert notifier.desktop_calls, "it should still be visible on screen, which is free"


async def test_a_real_result_is_spoken():
    reporter, spoken, _ = make()
    await reporter.on_event(JobEvent(9, "home", "result", "Two leads need a reply."))
    assert spoken and "Two leads" in spoken[0]


async def test_failures_are_always_spoken_even_if_terse():
    reporter, spoken, _ = make()
    await reporter.on_event(JobEvent(9, "home", "failed", "SILENT"))
    assert spoken, "a failure must never be swallowed by the quiet filter"
