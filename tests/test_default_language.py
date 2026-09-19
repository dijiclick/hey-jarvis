from types import SimpleNamespace

from jarvis.voice import (
    GEMINI_LANGUAGES,
    LANGUAGE_MEMORY_S,
    VoiceController,
    backend_instructions,
    build_instructions,
    greeting_instructions,
)

TURKISH = "Bugün hava nasıl, şemsiye alayım mı?"


def controller(now, default="English", transcripts=()):
    settings = SimpleNamespace(default_language=default, voice="cinder", openai_api_key="k",
                               idle_close_s=20, away_after_s=600, confirm_timeout_s=120, home=None)
    store = SimpleNamespace(add_transcript=lambda *a: None, recent_transcripts=lambda n=20: list(transcripts))
    broker = SimpleNamespace(offer=lambda text: False, pending=False)
    return VoiceController(settings, None, None, None, store, broker, None, clock=lambda: now[0])


def said(vc, text, role="user"):
    vc._on_item(SimpleNamespace(item=SimpleNamespace(role=role, text_content=text)))


def test_the_prompt_speaks_the_configured_language():
    text = build_instructions([], "Turkish")
    assert "speak Turkish by default" in text
    assert "outranks everything else" in text


def test_delegated_work_speaks_the_configured_language_too():
    assert "Write in Turkish by default" in backend_instructions("Turkish")


def test_no_prompt_hardcodes_another_language():
    others = [name for name in GEMINI_LANGUAGES if name != "English"]
    for text in (build_instructions([], "English"), backend_instructions("English"), greeting_instructions("English")):
        assert [name for name in others if name in text] == []
        assert not any("؀" <= ch <= "ۿ" for ch in text)


def test_it_starts_in_the_configured_language():
    assert controller([1000.0]).language == "English"
    assert controller([1000.0], default="Turkish").language == "Turkish"


def test_it_follows_the_user_into_another_language_and_back():
    vc = controller([1000.0])
    said(vc, TURKISH)
    assert vc.language == "Turkish"
    said(vc, "never mind, what time is it?")
    assert vc.language == "English"


def test_a_new_conversation_starts_in_the_default_again():
    vc = controller([1000.0])
    said(vc, TURKISH)
    vc.reset_language()
    assert vc.language == "English"


def test_old_transcripts_in_another_language_do_not_set_it():
    vc = controller([1000.0], transcripts=[("user", TURKISH), ("assistant", "Güneşli.")])
    assert vc.language == "English"


def test_a_short_garbled_fragment_does_not_switch_the_language():
    # seen live: English speech transcribed as "مسج ایلاف پک" flipped the whole conversation into Persian
    vc = controller([1000.0])
    said(vc, "مسج ایلاف پک")
    assert vc.language == "English"


def test_a_full_sentence_in_another_language_switches():
    vc = controller([1000.0])
    said(vc, "توی واتساپ به سام پیام بده لطفا")
    assert vc.language == "Persian"


def test_asking_for_a_language_switches_even_in_a_short_sentence():
    vc = controller([1000.0])
    said(vc, "speak Persian")
    assert vc.language == "Persian"
    said(vc, "به انگلیسی بگو")
    assert vc.language == "English"


def test_a_mixed_sentence_keeps_the_current_language():
    vc = controller([1000.0])
    said(vc, "send مسج to Sam on WhatsApp now")
    assert vc.language == "English"


async def test_switching_tells_the_voice_model_the_new_language():
    import asyncio

    vc = controller([1000.0])
    pushed = []

    class Agent:
        async def update_instructions(self, text):
            pushed.append(text)

    vc._agent = Agent()
    said(vc, "توی واتساپ به سام پیام بده لطفا")
    await asyncio.sleep(0)
    assert pushed and "speak Persian by default" in pushed[-1]


def test_a_stale_switch_expires():
    now = [1000.0]
    vc = controller(now)
    said(vc, TURKISH)
    now[0] += LANGUAGE_MEMORY_S + 1
    assert vc.language == "English"
