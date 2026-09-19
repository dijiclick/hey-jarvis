from jarvis.profile import full_knowledge_block, profile_block

FACT = "User uses WhatsApp Web inside Google Chrome as their primary messaging client"


def test_learned_facts_reach_the_voice_and_claude(tmp_path):
    (tmp_path / "memories.md").write_text(f"- {FACT}\n")
    assert FACT in profile_block(tmp_path), "the voice needs it to go straight to WhatsApp Web"
    assert FACT in full_knowledge_block(tmp_path), "Claude needs it to do the sending"


def test_no_memories_adds_nothing(tmp_path):
    assert profile_block(tmp_path) == "" and full_knowledge_block(tmp_path) == ""
