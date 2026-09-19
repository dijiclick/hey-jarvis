import asyncio
import json
import logging
from types import SimpleNamespace

from jarvis import voice
from jarvis.action_check import promised_action
from jarvis.voice import VoiceController


class Tools:
    def __init__(self):
        self.asked = []

    def ask_claude(self, task, project):
        self.asked.append((task, project))
        return f"Started job 7 in home."


def controller(checker):
    settings = SimpleNamespace(default_language="English", voice="cinder", openai_api_key="k",
                               idle_close_s=20, away_after_s=600, confirm_timeout_s=120, home=None)
    store = SimpleNamespace(add_transcript=lambda *a: None, recent_transcripts=lambda n=20: [])
    broker = SimpleNamespace(offer=lambda text: False, pending=False)
    tools = Tools()
    vc = VoiceController(settings, None, tools, None, store, broker, None, clock=lambda: 1000.0)
    vc.action_check = checker
    return vc, tools


def said(vc, text, role="user"):
    vc._on_item(SimpleNamespace(item=SimpleNamespace(role=role, text_content=text)))


async def settle():
    for _ in range(5):
        await asyncio.sleep(0)


TRENDYOL = "Şimdi benim için Trendyol'u aç, en iyi süpürgeyi bul."
PROMISE = "Hemen Trendyol'u açıp en iyi süpürgeyi bulmak için Claude Code'a görev veriyorum."


async def test_a_promise_without_a_tool_call_is_logged_and_actually_started(monkeypatch, caplog):
    # the 18:34 bug: "I'm giving it to Claude Code" was said, no tool was called, nothing happened
    monkeypatch.setattr(voice, "ACTION_GRACE_S", 0)
    seen = []

    async def checker(user, assistant):
        seen.append((user, assistant))
        return "Open Trendyol in Chrome and find the best-rated vacuum cleaner"

    vc, tools = controller(checker)
    with caplog.at_level(logging.WARNING, logger="jarvis.voice"):
        said(vc, TRENDYOL)
        said(vc, PROMISE, role="assistant")
        await settle()
    assert seen == [(TRENDYOL, PROMISE)]
    assert tools.asked == [("Open Trendyol in Chrome and find the best-rated vacuum cleaner", None)]
    assert any("missed action" in r.message for r in caplog.records), "every miss is in the log, to fix later"


async def test_a_reply_that_came_with_a_tool_call_is_not_checked(monkeypatch):
    monkeypatch.setattr(voice, "ACTION_GRACE_S", 0)
    seen = []

    async def checker(user, assistant):
        seen.append(user)
        return "anything"

    vc, tools = controller(checker)
    said(vc, "open Safari")
    vc._tool_used()
    said(vc, "Opened.", role="assistant")
    await settle()
    assert seen == [] and tools.asked == []


async def test_a_tool_call_that_lands_during_the_check_is_not_doubled(monkeypatch):
    monkeypatch.setattr(voice, "ACTION_GRACE_S", 0)
    vc, tools = None, None

    async def checker(user, assistant):
        vc._tool_used()  # the model called the tool late, while we were asking
        return "Open Trendyol"

    vc, tools = controller(checker)
    said(vc, TRENDYOL)
    said(vc, PROMISE, role="assistant")
    await settle()
    assert tools.asked == []


async def test_a_plain_answer_starts_nothing(monkeypatch):
    monkeypatch.setattr(voice, "ACTION_GRACE_S", 0)

    async def checker(user, assistant):
        return None

    vc, tools = controller(checker)
    said(vc, "what is the capital of France?")
    said(vc, "Paris.", role="assistant")
    await settle()
    assert tools.asked == []


async def test_only_the_first_reply_to_a_request_is_checked(monkeypatch):
    # "still working on it" after a recovered job must not start the same work again
    monkeypatch.setattr(voice, "ACTION_GRACE_S", 0)
    calls = []

    async def checker(user, assistant):
        calls.append(assistant)
        return "Open Trendyol"

    vc, tools = controller(checker)
    said(vc, TRENDYOL)
    said(vc, PROMISE, role="assistant")
    said(vc, "Evet, işlem devam ediyor.", role="assistant")
    await settle()
    assert len(tools.asked) == 1


class FakeGemini:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []
        self.models = self

    def generate_content(self, model, contents, config=None):
        self.prompts.append(contents)
        return SimpleNamespace(text=self.reply)


async def test_the_checker_returns_the_task_when_an_action_was_promised():
    fake = FakeGemini(json.dumps({"promised_action": True, "task": "Open Trendyol and find the best vacuum"}))
    task = await promised_action("key", TRENDYOL, PROMISE, client_factory=lambda key: fake)
    assert task == "Open Trendyol and find the best vacuum"
    assert TRENDYOL in str(fake.prompts[0]) and PROMISE in str(fake.prompts[0])


async def test_the_checker_returns_nothing_for_an_answer_or_garbage():
    no = FakeGemini(json.dumps({"promised_action": False, "task": ""}))
    assert await promised_action("key", "capital of France?", "Paris.", client_factory=lambda key: no) is None
    junk = FakeGemini("not json")
    assert await promised_action("key", "x", "y", client_factory=lambda key: junk) is None
    assert await promised_action(None, "x", "y") is None
