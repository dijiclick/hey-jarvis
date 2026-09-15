import stat

import pytest

from jarvis.config import load_settings
from jarvis.onboarding import run_setup, write_env

VARS = ["OPENAI_API_KEY", "GEMINI_API_KEY", "JARVIS_VOICE_PROVIDER", "JARVIS_DEFAULT_LANGUAGE",
        "JARVIS_PROJECTS_ROOT", "JARVIS_GEMINI_VOICE", "JARVIS_GEMINI_MODEL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in VARS:
        monkeypatch.delenv(name, raising=False)


class Terminal:
    """Plays the user at the keyboard: an empty answer is pressing Enter."""

    def __init__(self, answers=(), secrets=()):
        self.answers, self.secrets, self.output = list(answers), list(secrets), []

    def ask(self, prompt, default):
        return self.answers.pop(0) if self.answers else ""

    def secret(self, prompt):
        return self.secrets.pop(0) if self.secrets else ""

    def say(self, text):
        self.output.append(text)


def setup(home, **typed):
    terminal = Terminal(**typed)
    return run_setup(home, ask=terminal.ask, ask_secret=terminal.secret, say=terminal.say), terminal


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_write_env_is_readable_only_by_the_user(tmp_path):
    path = write_env(tmp_path / "home", {"GEMINI_API_KEY": "g"})
    assert path.read_text() == "GEMINI_API_KEY=g\n"
    assert mode(path) == 0o600


def test_write_env_updates_keys_and_keeps_everything_else(tmp_path):
    (tmp_path / ".env").write_text("# mine\nOPENAI_API_KEY=old\nTELEGRAM_CHAT_ID=5\n")
    write_env(tmp_path, {"OPENAI_API_KEY": "new", "JARVIS_DEFAULT_LANGUAGE": "English"})
    assert (tmp_path / ".env").read_text() == (
        "# mine\nOPENAI_API_KEY=new\nTELEGRAM_CHAT_ID=5\nJARVIS_DEFAULT_LANGUAGE=English\n")
    assert mode(tmp_path / ".env") == 0o600


def test_pressing_enter_through_setup_gives_a_working_gemini_config(tmp_path):
    code, terminal = setup(tmp_path, secrets=["g-key"])
    s = load_settings(tmp_path)
    assert code == 0
    assert (s.voice_provider, s.gemini_api_key, s.default_language) == ("gemini", "g-key", "English")
    assert "g-key" not in "\n".join(terminal.output), "a key must never be printed back"


def test_setup_can_choose_the_openai_voice_a_language_and_a_projects_folder(tmp_path):
    code, _ = setup(tmp_path, answers=["openai", "Spanish", str(tmp_path / "code")], secrets=["sk-o"])
    s = load_settings(tmp_path)
    assert code == 0
    assert (s.voice_provider, s.openai_api_key, s.default_language, s.projects_root) == (
        "openai", "sk-o", "Spanish", tmp_path / "code")


def test_rerunning_setup_keeps_the_saved_key_when_left_blank(tmp_path):
    setup(tmp_path, secrets=["g-key"])
    code, _ = setup(tmp_path, answers=["", "Turkish"], secrets=[""])
    s = load_settings(tmp_path)
    assert code == 0
    assert (s.gemini_api_key, s.default_language) == ("g-key", "Turkish")


def test_setup_without_a_key_stops_and_writes_nothing(tmp_path):
    code, terminal = setup(tmp_path, secrets=[""])
    assert code == 1
    assert not (tmp_path / ".env").exists()
    assert any("key" in line.lower() for line in terminal.output)


def test_an_unknown_voice_engine_is_refused(tmp_path):
    code, _ = setup(tmp_path, answers=["siri"], secrets=["x"])
    assert code == 1
    assert not (tmp_path / ".env").exists()
