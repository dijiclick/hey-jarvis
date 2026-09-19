from types import SimpleNamespace

import pytest

from jarvis.greeting import ensure_greeting, greeting_path, greeting_text, load_greeting
from jarvis.voice import VoiceController, greeting_instructions


def test_greeting_asks_how_to_help_in_each_language():
    assert greeting_text("English") == "Hi! How can I help you?"
    assert "سلام" in greeting_text("Persian")
    assert "Merhaba" in greeting_text("Turkish")
    assert "Привет" in greeting_text("Russian")
    assert greeting_text("Klingon") is None


async def test_records_once_per_voice_and_language(tmp_path):
    calls = []

    async def synth(text, voice):
        calls.append((text, voice))
        return b"\x01\x00" * 100

    path = await ensure_greeting(tmp_path, "Enceladus", "English", synth)
    assert path == greeting_path(tmp_path, "Enceladus", "English") and path.exists()
    assert calls == [("Hi! How can I help you?", "Enceladus")]
    await ensure_greeting(tmp_path, "Enceladus", "English", synth)
    assert len(calls) == 1, "a recorded greeting is reused, not recorded again"
    await ensure_greeting(tmp_path, "Puck", "English", synth)
    assert len(calls) == 2, "a new voice needs its own recording"
    assert load_greeting(tmp_path, "Enceladus", "English") == b"\x01\x00" * 100


async def test_a_failed_recording_leaves_nothing_behind(tmp_path):
    async def broken(text, voice):
        raise RuntimeError("TTS down")

    async def empty(text, voice):
        return b""

    assert await ensure_greeting(tmp_path, "Enceladus", "English", broken) is None
    assert await ensure_greeting(tmp_path, "Enceladus", "English", empty) is None
    assert load_greeting(tmp_path, "Enceladus", "English") is None
    assert await ensure_greeting(tmp_path, "Enceladus", "Klingon", broken) is None


class Audio:
    def __init__(self):
        self.played = []

    def play_pcm(self, pcm):
        self.played.append(pcm)


def controller(clip):
    settings = SimpleNamespace(default_language="English", voice="cinder", openai_api_key="k", idle_close_s=20,
                               away_after_s=600, confirm_timeout_s=120, home=None)
    store = SimpleNamespace(add_transcript=lambda *a: None, recent_transcripts=lambda n=20: [])
    vc = VoiceController(settings, Audio(), None, None, store, SimpleNamespace(offer=lambda t: False, pending=False),
                         None)
    vc.greeting_clip = lambda language: clip
    return vc


async def test_greets_at_once_with_the_recorded_clip():
    vc = controller(b"\x02\x00" * 10)
    spoken = []

    async def say(instructions):
        spoken.append(instructions)

    vc.say = say
    await vc.greet()
    assert vc.audio.played == [b"\x02\x00" * 10]
    assert spoken == [], "no round-trip to the voice model when the greeting is already recorded"


async def test_without_a_clip_the_voice_model_greets():
    vc = controller(None)
    spoken = []

    async def say(instructions):
        spoken.append(instructions)

    vc.say = say
    await vc.greet()
    assert vc.audio.played == [] and spoken == [greeting_instructions("English")]


@pytest.mark.parametrize("language", ["English", "Spanish"])
def test_live_greeting_asks_how_to_help(language):
    text = greeting_instructions(language)
    assert f"Speak in {language}" in text and "how can i help" in text.lower()


def test_farewell_says_bye_in_each_language():
    from jarvis.greeting import farewell_text

    assert farewell_text("English") == "Bye bye!"
    assert "خداحافظ" in farewell_text("Persian")
    assert farewell_text("Klingon") is None


async def test_farewell_is_recorded_next_to_the_greeting(tmp_path):
    calls = []

    async def synth(text, voice):
        calls.append(text)
        return b"\x03\x00" * 50

    await ensure_greeting(tmp_path, "Enceladus", "English", synth)
    await ensure_greeting(tmp_path, "Enceladus", "English", synth, kind="farewell")
    assert calls == ["Hi! How can I help you?", "Bye bye!"]
    assert load_greeting(tmp_path, "Enceladus", "English", kind="farewell") == b"\x03\x00" * 50


def goodbye_controller(clip):
    vc = controller(None)
    vc.farewell_clip = lambda language: clip
    events = []

    async def close():
        events.append("closed")

    vc.close = close
    vc.on_goodbye = lambda: events.append("turned off")
    return vc, events


async def test_bye_bye_says_bye_then_turns_jarvis_off():
    vc, events = goodbye_controller(b"\x04\x00" * 10)
    await vc._close_after_farewell()
    assert vc.audio.played == [b"\x04\x00" * 10]
    assert events == ["closed", "turned off"]


async def test_bye_bye_without_a_recording_still_turns_jarvis_off():
    vc, events = goodbye_controller(None)
    await vc._close_after_farewell()
    assert vc.audio.played == [] and events == ["closed", "turned off"]


async def test_a_flaky_recording_is_retried(tmp_path):
    # measured: the TTS preview model sometimes answers with no audio at all, then works on the next try
    replies = [RuntimeError("no audio"), b"", b"\x05\x00" * 10]

    async def flaky(text, voice):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert await ensure_greeting(tmp_path, "Enceladus", "English", flaky, kind="farewell") is not None
    assert replies == []
