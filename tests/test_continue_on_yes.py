from types import SimpleNamespace

import pytest

from jarvis.projects import ProjectResolver
from jarvis.speech_text import ends_with_question
from jarvis.store import Store
from jarvis.voice import CONFIRM_ECHO_WINDOW_S, CONTINUE_WINDOW_S, JarvisTools, VoiceController

# what Claude actually ended job 91 with, in English and as it was really said
QUESTION = "The text is in the VS Code chat box, not sent yet. Should I press Enter to send it?"
QUESTION_FA = "متن توی باکس ورودی وی‌اس‌کد نوشته شده؛ ارسالش نکردم. بزنم اینتر که بفرسته؟"


class FakeJobs:
    def __init__(self):
        self.submitted = []

    def submit(self, project, task):
        self.submitted.append((project.name, task))
        return 92


def setup(tmp_path, now):
    (tmp_path / "superpower" / ".git").mkdir(parents=True)
    jobs = FakeJobs()
    clock = lambda: now[0]
    tools = JarvisTools(jobs, ProjectResolver(tmp_path), Store(tmp_path / "j.db"), clock=clock)
    settings = SimpleNamespace(default_language="English", voice="cinder", openai_api_key="k",
                               idle_close_s=20, away_after_s=600, confirm_timeout_s=120, home=None)
    store = SimpleNamespace(add_transcript=lambda *a: None, recent_transcripts=lambda n=20: [])
    broker = SimpleNamespace(offer=lambda text: False, pending=False, answered_within=lambda s: False)
    vc = VoiceController(settings, None, tools, None, store, broker, None, clock=clock)
    return vc, tools, jobs


def said(vc, text):
    vc._on_item(SimpleNamespace(item=SimpleNamespace(role="user", text_content=text)))


@pytest.mark.parametrize("text", [QUESTION, QUESTION_FA, "Want me to deploy it?  "])
def test_a_report_that_ends_with_a_question_is_recognised(text):
    assert ends_with_question(text) is True


@pytest.mark.parametrize("text", ["Done. All 42 tests pass.", "Is it fixed? Yes, the tests pass now.", ""])
def test_a_plain_report_is_not_a_question(text):
    assert ends_with_question(text) is False


def test_yes_to_claudes_question_continues_the_job(tmp_path):
    vc, _, jobs = setup(tmp_path, [1000.0])
    vc.expect_answer("superpower", QUESTION_FA)
    said(vc, "بله")
    assert len(jobs.submitted) == 1
    project, task = jobs.submitted[0]
    assert project == "superpower"
    assert QUESTION_FA in task and "بله" in task


def test_the_voice_model_cannot_start_the_same_thing_twice(tmp_path):
    now = [1000.0]
    vc, tools, jobs = setup(tmp_path, now)
    vc.expect_answer("superpower", QUESTION)
    said(vc, "yes, do it")
    reply = tools.ask_claude("press enter in VS Code", "superpower")
    assert len(jobs.submitted) == 1 and "already" in reply
    now[0] += CONFIRM_ECHO_WINDOW_S + 1
    tools.ask_claude("now run the tests", "superpower")
    assert len(jobs.submitted) == 2, "a genuinely new request later still goes through"


def test_no_drops_the_question(tmp_path):
    vc, _, jobs = setup(tmp_path, [1000.0])
    vc.expect_answer("superpower", QUESTION)
    said(vc, "no, leave it")
    said(vc, "yes")
    assert jobs.submitted == []


def test_unrelated_speech_keeps_the_question_open(tmp_path):
    vc, _, jobs = setup(tmp_path, [1000.0])
    vc.expect_answer("superpower", QUESTION)
    said(vc, "what time is it?")
    assert jobs.submitted == []
    said(vc, "okay, go ahead")
    assert len(jobs.submitted) == 1


def test_a_new_request_starting_with_okay_is_not_an_answer(tmp_path):
    vc, _, jobs = setup(tmp_path, [1000.0])
    vc.expect_answer("superpower", QUESTION)
    said(vc, "okay now open Chrome and check my email please")
    assert jobs.submitted == []


def test_a_stale_question_expires(tmp_path):
    now = [1000.0]
    vc, _, jobs = setup(tmp_path, now)
    vc.expect_answer("superpower", QUESTION)
    now[0] += CONTINUE_WINDOW_S + 1
    said(vc, "yes")
    assert jobs.submitted == []
