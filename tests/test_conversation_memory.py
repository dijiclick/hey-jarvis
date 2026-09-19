from types import SimpleNamespace

from jarvis.voice import VoiceController


def controller(transcripts=None):
    requested = []

    def recent(n=20):
        requested.append(n)
        return list(transcripts or [])

    settings = SimpleNamespace(default_language="English", voice="cinder", openai_api_key="k",
                               idle_close_s=20, away_after_s=600, confirm_timeout_s=120, home=None)
    store = SimpleNamespace(add_transcript=lambda *a: None, recent_transcripts=recent)
    broker = SimpleNamespace(offer=lambda text: False, pending=False)
    return VoiceController(settings, None, None, None, store, broker, None, clock=lambda: 1000.0), requested


def said(vc, text, role="user"):
    vc._on_item(SimpleNamespace(item=SimpleNamespace(role=role, text_content=text)))


async def test_a_finished_conversation_goes_to_long_term_memory():
    vc, _ = controller()
    learned = []
    vc.memory = SimpleNamespace(learn=lambda turns: learned.append(list(turns)))
    said(vc, "send on my way to Sam on WhatsApp")
    said(vc, "Sending it now.", role="assistant")
    await vc._finish_conversation()
    assert learned == [[("user", "send on my way to Sam on WhatsApp"), ("assistant", "Sending it now.")]]
    assert vc._turns == [], "the next conversation starts clean"


def test_without_memory_finishing_a_conversation_is_harmless():
    vc, _ = controller()
    said(vc, "what time is it")
    assert vc._finish_conversation() is None
    assert vc._turns == []


def test_a_new_conversation_carries_more_than_the_last_four_lines():
    # four lines lost "send it to Sam" as soon as the user said where; the language no longer drifts, so carry more
    vc, requested = controller(transcripts=[("user", "hi")])
    vc._history()
    assert requested and requested[-1] >= 10
