from pathlib import Path

from jarvis.projects import ProjectResolver
from jarvis.store import Store
from jarvis.voice import JarvisTools, build_instructions, should_close


class FakeJobs:
    def __init__(self, cancel_result=()):
        self.submitted = []
        self.cancel_result = list(cancel_result)

    def submit(self, project, task):
        self.submitted.append((project, task))
        return 7

    async def cancel(self, job_id=None):
        return self.cancel_result


def resolver(tmp_path):
    (tmp_path / "ShopFront" / ".git").mkdir(parents=True, exist_ok=True)
    return ProjectResolver(tmp_path)


def test_greeting_instructions():
    from jarvis.voice import greeting_instructions

    text = greeting_instructions("Spanish")
    assert "Speak in Spanish" in text
    assert "At your service" in text


def test_instructions_set_assistant_persona():
    text = build_instructions([])
    assert "personal assistant" in text and "at the user's service" in text
    assert "gendered forms of address" in text
    assert "Never ask for permission first" in text


def test_instructions_mention_projects_and_language():
    text = build_instructions(["ShopFront", "Ledgerly"], "Spanish")
    assert "ShopFront, Ledgerly" in text
    assert "speak Spanish by default" in text
    assert "Turkish" not in text


def test_should_close_when_agent_silent_despite_background_speech():
    # TV dialogue keeps "user speaking" on, but Jarvis hasn't said anything for 60 s
    assert should_close(100, 99, 20, True, False, False, last_agent_speech=39) is True
    assert should_close(100, 99, 20, True, False, False, last_agent_speech=50) is False
    assert should_close(100, 99, 20, True, True, False, last_agent_speech=0) is False
    assert should_close(100, 99, 20, True, False, True, last_agent_speech=0) is False


def test_should_close():
    assert should_close(30, 5, 20, False, False, False) is True
    assert should_close(10, 5, 20, False, False, False) is False
    assert should_close(30, 5, 20, True, False, False) is False
    assert should_close(30, 5, 20, False, True, False) is False
    assert should_close(30, 5, 20, False, False, True) is False


def test_ask_claude_submits_job(tmp_path):
    jobs = FakeJobs()
    tools = JarvisTools(jobs, resolver(tmp_path), Store(tmp_path / "j.db"))
    out = tools.ask_claude("fix the login bug", "shopfront")
    assert "Started job 7 in ShopFront" in out
    assert jobs.submitted[0][0].name == "ShopFront"
    assert jobs.submitted[0][1] == "fix the login bug"


class FakeBroker:
    def __init__(self, pending=False, recent=False):
        self.pending = pending
        self.recent = recent

    def answered_within(self, seconds):
        return self.recent


def test_ask_claude_refuses_echo_right_after_confirmation(tmp_path):
    jobs = FakeJobs()
    tools = JarvisTools(jobs, resolver(tmp_path), Store(tmp_path / "j.db"), broker=FakeBroker(recent=True))
    out = tools.ask_claude("The user approved: yes, go ahead. Continue the pending task.", "shopfront")
    assert jobs.submitted == []
    assert "already delivered" in out


def test_ask_claude_refuses_while_confirmation_pending(tmp_path):
    jobs = FakeJobs()
    tools = JarvisTools(jobs, resolver(tmp_path), Store(tmp_path / "j.db"), broker=FakeBroker(pending=True))
    out = tools.ask_claude("deploy it", "shopfront")
    assert jobs.submitted == []
    assert "waiting" in out


def test_english_is_the_default_language_of_both_prompts():
    from jarvis.voice import backend_instructions

    text = build_instructions([])
    assert "speak English by default" in text
    assert "goodbye" in text
    assert "Write in English by default" in backend_instructions()


def test_instructions_answer_general_questions_without_claude():
    text = build_instructions([])
    assert "Answer general questions yourself" in text
    assert "Never say you can't help" in text


def test_remember_saves_a_fact(tmp_path):
    from jarvis.profile import load_profile

    tools = JarvisTools(FakeJobs(), resolver(tmp_path), Store(tmp_path / "j.db"), home=tmp_path)
    out = tools.remember("lives in Lisbon")
    assert "Saved" in out
    assert "lives in Lisbon" in load_profile(tmp_path)
    assert "empty" in tools.remember("   ")


def test_ask_claude_unknown_project_suggests(tmp_path):
    jobs = FakeJobs()
    out = JarvisTools(jobs, resolver(tmp_path), Store(tmp_path / "j.db")).ask_claude("x", "shopfrant zzzz")
    assert "Unknown project" in out and "ShopFront" in out
    assert jobs.submitted == []


def test_ask_claude_without_project_uses_home(tmp_path):
    jobs = FakeJobs()
    JarvisTools(jobs, resolver(tmp_path), Store(tmp_path / "j.db")).ask_claude("open Safari", None)
    assert jobs.submitted[0][0].path == Path.home()


def test_job_status(tmp_path):
    store = Store(tmp_path / "j.db")
    tools = JarvisTools(FakeJobs(), resolver(tmp_path), store)
    assert "No jobs" in tools.job_status()
    jid = store.create_job("ShopFront", "/p", "fix login")
    store.set_status(jid, "running")
    store.add_event(jid, "progress", "Running: npm test")
    done = store.create_job("home", "/h", "open safari")
    store.set_status(done, "done", "Safari is open.")
    status = tools.job_status()
    assert "ShopFront" in status and "Running: npm test" in status and "Safari is open." in status


async def test_cancel_job(tmp_path):
    tools = JarvisTools(FakeJobs([3]), resolver(tmp_path), Store(tmp_path / "j.db"))
    assert await tools.cancel_job(None) == "Cancelled job 3."
    tools = JarvisTools(FakeJobs([]), resolver(tmp_path), Store(tmp_path / "j.db"))
    assert await tools.cancel_job(9) == "Nothing to cancel."
