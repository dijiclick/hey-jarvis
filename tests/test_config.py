from pathlib import Path

import pytest

from jarvis.config import load_settings

KEYS = ["OPENAI_API_KEY", "JARVIS_PROJECTS_ROOT", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "JARVIS_HOTKEY"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)


def test_load_settings_reads_env_file(tmp_path):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\nJARVIS_PROJECTS_ROOT=/tmp/projects\n")
    s = load_settings(tmp_path)
    assert s.openai_api_key == "sk-test"
    assert s.projects_root == Path("/tmp/projects")
    assert s.telegram_bot_token is None
    assert s.db_path == tmp_path / "jarvis.db"
    assert s.hotkey == "<ctrl>+<alt>+j"
    assert s.input_device == "auto"
    assert s.idle_close_s == 20 and s.away_after_s == 600 and s.confirm_timeout_s == 120


def test_process_env_overrides_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env")
    assert load_settings(tmp_path).openai_api_key == "sk-env"


def test_missing_key_raises(tmp_path):
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        load_settings(tmp_path)
