import pytest

from jarvis.config import load_settings

VARS = ["OPENAI_API_KEY", "GEMINI_API_KEY", "JARVIS_VOICE_PROVIDER", "JARVIS_DEFAULT_LANGUAGE",
        "JARVIS_GEMINI_VOICE", "JARVIS_GEMINI_MODEL", "JARVIS_PROJECTS_ROOT", "JARVIS_CLAUDE_MODEL",
        "JARVIS_CLAUDE_EFFORT"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in VARS:
        monkeypatch.delenv(name, raising=False)


def settings_from(tmp_path, text):
    (tmp_path / ".env").write_text(text)
    return load_settings(tmp_path)


def test_speaks_english_unless_told_otherwise(tmp_path):
    assert settings_from(tmp_path, "GEMINI_API_KEY=g\n").default_language == "English"


def test_the_default_language_is_configurable(tmp_path):
    assert settings_from(tmp_path, "GEMINI_API_KEY=g\nJARVIS_DEFAULT_LANGUAGE=Spanish\n").default_language == "Spanish"


def test_a_gemini_key_alone_is_enough(tmp_path):
    s = settings_from(tmp_path, "GEMINI_API_KEY=g\n")
    assert (s.voice_provider, s.gemini_api_key, s.openai_api_key) == ("gemini", "g", None)


def test_an_openai_key_alone_uses_the_openai_voice(tmp_path):
    s = settings_from(tmp_path, "OPENAI_API_KEY=sk-o\n")
    assert (s.voice_provider, s.openai_api_key) == ("openai", "sk-o")


def test_with_both_keys_gemini_is_the_default(tmp_path):
    assert settings_from(tmp_path, "OPENAI_API_KEY=sk-o\nGEMINI_API_KEY=g\n").voice_provider == "gemini"


def test_the_documented_voice_is_the_one_you_get(tmp_path):
    assert settings_from(tmp_path, "GEMINI_API_KEY=g\n").gemini_voice == "Enceladus"


def test_the_default_voice_model_is_the_one_that_reliably_calls_tools(tmp_path):
    # measured: preview-12-2025 said "opening Trendyol" without calling a tool in 4-8 of 10 tries, in bursts;
    # native-audio-latest called one 46/46
    assert settings_from(tmp_path, "GEMINI_API_KEY=g\n").gemini_model == "gemini-2.5-flash-native-audio-latest"


def test_no_key_at_all_points_to_setup(tmp_path):
    with pytest.raises(RuntimeError, match="jarvis setup"):
        settings_from(tmp_path, "")


def test_claude_code_runs_fast_by_default(tmp_path):
    s = settings_from(tmp_path, "GEMINI_API_KEY=g\n")
    assert (s.claude_model, s.claude_effort) == ("sonnet", "low")


def test_claude_code_speed_is_configurable(tmp_path):
    s = settings_from(tmp_path, "GEMINI_API_KEY=g\nJARVIS_CLAUDE_MODEL=opus\nJARVIS_CLAUDE_EFFORT=high\n")
    assert (s.claude_model, s.claude_effort) == ("opus", "high")


def test_a_chosen_voice_without_its_key_names_the_missing_key(tmp_path):
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        settings_from(tmp_path, "JARVIS_VOICE_PROVIDER=openai\nGEMINI_API_KEY=g\n")
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        settings_from(tmp_path, "JARVIS_VOICE_PROVIDER=gemini\nOPENAI_API_KEY=sk-o\n")
