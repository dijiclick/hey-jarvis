import os

from jarvis.memory import LongTermMemory, mem0_config, memories_path


class FakeMem0:
    """Stands in for mem0.Memory: records what it is taught, returns canned facts, no Gemini calls."""

    def __init__(self, facts=(), fail=False):
        self.added, self.facts, self.fail = [], list(facts), fail

    def add(self, messages, user_id):
        if self.fail:
            raise RuntimeError("Gemini is down")
        self.added.append((messages, user_id))

    def get_all(self, filters):
        return {"results": [{"memory": fact} for fact in self.facts]}


def memory(tmp_path, fake, key="gem-key"):
    built = []

    def factory(config):
        built.append(config)
        return fake

    return LongTermMemory(tmp_path, key, factory=factory), built


# the real conversation that taught Jarvis nothing: it looked for a WhatsApp app and never learned it's the web
CONVERSATION = [
    ("user", "In WhatsApp, send on my way to Sam."),
    ("assistant", "I couldn't find an application named WhatsApp."),
    ("user", "<noise>"),
    ("user", "No, I use WhatsApp Web in my main Chrome."),
    ("assistant", ""),
]


def test_a_finished_conversation_is_learned_from(tmp_path):
    fake = FakeMem0(facts=["User uses WhatsApp Web inside Google Chrome"])
    m, _ = memory(tmp_path, fake)
    m.learn(CONVERSATION)
    messages, user_id = fake.added[0]
    assert user_id == "owner"
    assert messages == [
        {"role": "user", "content": "In WhatsApp, send on my way to Sam."},
        {"role": "assistant", "content": "I couldn't find an application named WhatsApp."},
        {"role": "user", "content": "No, I use WhatsApp Web in my main Chrome."},
    ]


def test_learned_facts_are_written_where_jarvis_and_claude_read_them(tmp_path):
    m, _ = memory(tmp_path, FakeMem0(facts=["User's colleague is named Sam",
                                            "User uses WhatsApp Web inside Google Chrome"]))
    m.learn(CONVERSATION)
    assert memories_path(tmp_path).read_text() == (
        "- User's colleague is named Sam\n- User uses WhatsApp Web inside Google Chrome\n")


def test_a_conversation_where_the_user_said_nothing_teaches_nothing(tmp_path):
    fake = FakeMem0()
    m, built = memory(tmp_path, fake)
    m.learn([("assistant", "At your service."), ("user", "<noise>")])
    assert fake.added == [] and built == [], "no Gemini call for an empty conversation"


def test_a_memory_failure_never_breaks_jarvis(tmp_path, caplog):
    m, _ = memory(tmp_path, FakeMem0(fail=True))
    with caplog.at_level("ERROR", logger="jarvis.memory"):
        m.learn(CONVERSATION)
    assert "could not learn" in caplog.text


def test_without_a_gemini_key_memory_stays_off(tmp_path):
    fake = FakeMem0()
    m, built = memory(tmp_path, fake, key=None)
    m.learn(CONVERSATION)
    assert built == [] and fake.added == []


def test_memories_stay_on_this_mac_use_gemini_and_send_no_telemetry(tmp_path):
    config = mem0_config(tmp_path, "gem-key")
    assert config["llm"]["provider"] == "gemini" and config["embedder"]["provider"] == "gemini"
    assert config["vector_store"]["config"]["path"].startswith(str(tmp_path))
    assert config["history_db_path"].startswith(str(tmp_path))
    assert os.environ.get("MEM0_TELEMETRY") == "False"
