import asyncio

import pytest

from jarvis.confirm import ConfirmationBroker, parse_answer


@pytest.mark.parametrize("text", ["yes", "Yes, go ahead.", "بله", "آره بزن", "okay do it", "evet", "آره‌"])
def test_yes(text):
    assert parse_answer(text) is True


@pytest.mark.parametrize("text", ["no", "نه", "No, don't.", "نه نکن", "cancel that", "hayır"])
def test_no(text):
    assert parse_answer(text) is False


@pytest.mark.parametrize("text", ["hmm", "what did you say", "ساعت چنده", ""])
def test_unclear(text):
    assert parse_answer(text) is None


def make_broker(timeout=2.0):
    asked = []

    async def ask(summary):
        asked.append(summary)

    return ConfirmationBroker(ask=ask, timeout_s=timeout), asked


async def test_yes_flow_ignores_unclear():
    b, asked = make_broker()
    task = asyncio.create_task(b.confirm("push to main"))
    await asyncio.sleep(0.01)
    assert b.pending and asked == ["push to main"]
    assert b.offer("hmm") is False
    assert b.offer("بله") is True
    assert await task is True
    assert not b.pending


async def test_timeout_denies():
    b, _ = make_broker(timeout=0.05)
    assert await b.confirm("deploy") is False


async def test_offer_without_pending():
    b, _ = make_broker()
    assert b.offer("yes") is False


async def test_answered_within_tracks_recent_answer():
    now = [100.0]

    async def ask(summary):
        pass

    b = ConfirmationBroker(ask=ask, timeout_s=2, clock=lambda: now[0])
    assert b.answered_within(10) is False
    task = asyncio.create_task(b.confirm("push"))
    await asyncio.sleep(0.01)
    b.offer("yes")
    await task
    now[0] = 105.0
    assert b.answered_within(10) is True
    now[0] = 111.0
    assert b.answered_within(10) is False


async def test_confirmations_are_serialized():
    b, asked = make_broker()
    t1 = asyncio.create_task(b.confirm("first"))
    t2 = asyncio.create_task(b.confirm("second"))
    await asyncio.sleep(0.01)
    assert asked == ["first"]
    b.offer("yes")
    await asyncio.sleep(0.01)
    assert asked == ["first", "second"]
    b.offer("no")
    assert [await t1, await t2] == [True, False]
