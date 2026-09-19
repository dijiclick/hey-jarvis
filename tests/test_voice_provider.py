from types import SimpleNamespace

import pytest

from jarvis.config import load_settings
from jarvis.voice import PROVIDERS, build_realtime_model


def settings(provider="gemini", **over):
    base = dict(voice_provider=provider, openai_api_key="sk-test", gemini_api_key="gem-key",
                voice="cinder", gemini_voice="Charon", gemini_model="gemini-3.1-flash-live-preview",
                default_language="English")
    base.update(over)
    return SimpleNamespace(**base)


def test_both_providers_are_offered():
    assert set(PROVIDERS) == {"openai", "gemini"}


def test_gemini_is_the_default_because_it_is_cheaper():
    made = {}
    build_realtime_model(settings(), http=None, factories={
        "gemini": lambda **kw: made.update(kw) or "gemini-model",
        "openai": lambda **kw: "openai-model",
    })
    assert made["model"] == "gemini-3.1-flash-live-preview"
    assert made["voice"] == "Charon"
    assert made["api_key"] == "gem-key"


def test_openai_is_still_selectable_as_a_backup():
    made = {}
    model = build_realtime_model(settings(provider="openai"), http="session", factories={
        "gemini": lambda **kw: "gemini-model",
        "openai": lambda **kw: made.update(kw) or "openai-model",
    })
    assert model == "openai-model"
    assert made["api_key"] == "sk-test" and made["voice"] == "cinder"


def test_the_chosen_engine_is_named_in_the_log(caplog):
    with caplog.at_level("INFO", logger="jarvis.voice"):
        build_realtime_model(settings(), http=None, factories={"gemini": lambda **kw: "gemini-model"})
    assert "gemini-3.1-flash-live-preview" in caplog.text and "Charon" in caplog.text


def test_the_openai_fallback_is_named_too(caplog):
    with caplog.at_level("INFO", logger="jarvis.voice"):
        build_realtime_model(settings(provider="openai"), http=None,
                             factories={"openai": lambda **kw: "openai-model"})
    assert "openai" in caplog.text and "cinder" in caplog.text


def test_an_unknown_provider_fails_loudly():
    with pytest.raises(ValueError, match="unknown voice provider"):
        build_realtime_model(settings(provider="whisper-thing"), http=None, factories={})


def test_gemini_without_a_key_says_so_instead_of_starting_mute():
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        build_realtime_model(settings(gemini_api_key=None), http=None, factories={
            "gemini": lambda **kw: "gemini-model",
        })


def gemini_kwargs(model: str) -> dict:
    made = {}
    build_realtime_model(settings(gemini_model=model), http=None,
                         factories={"gemini": lambda **kw: made.update(kw) or "gemini-model"})
    return made


def test_native_audio_models_get_no_language_code():
    # Google rejects it ("Unsupported language code") and kills the session within a second
    assert "language" not in gemini_kwargs("gemini-2.5-flash-native-audio-preview-12-2025")


def test_flash_live_still_gets_a_language_hint():
    # left to guess, gemini-3.1-flash-live transcribed speech in the wrong language
    assert gemini_kwargs("gemini-3.1-flash-live-preview")["language"] == "en-US"


async def test_the_default_gemini_model_can_speak_first(tmp_path, monkeypatch):
    for name in ("JARVIS_GEMINI_MODEL", "JARVIS_VOICE_PROVIDER", "GEMINI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\nGEMINI_API_KEY=test-key\n")
    model = build_realtime_model(load_settings(tmp_path), http=None)
    # the greeting, job reports and approval prompts all start with generate_reply, which needs this;
    # gemini-3.1-flash-live-preview lacks it, so Jarvis could only ever answer, never speak first
    assert model.capabilities.mutable_chat_context


def test_openai_without_a_key_says_so_too():
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_realtime_model(settings(provider="openai", openai_api_key=None), http=None, factories={
            "openai": lambda **kw: "openai-model",
        })
