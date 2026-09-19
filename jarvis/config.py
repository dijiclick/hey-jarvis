import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

HOME = Path(os.environ.get("JARVIS_HOME", Path.home() / ".jarvis"))


@dataclass(frozen=True)
class Settings:
    home: Path
    openai_api_key: str | None
    projects_root: Path
    hotkey: str
    input_device: str
    voice: str
    default_language: str
    wake_threshold: float
    idle_close_s: float
    away_after_s: float
    confirm_timeout_s: float
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    openai_admin_key: str | None = None
    voice_provider: str = "gemini"
    gemini_api_key: str | None = None
    gemini_voice: str = "Enceladus"
    gemini_model: str = "gemini-2.5-flash-native-audio-latest"
    claude_model: str | None = "sonnet"
    claude_effort: str | None = "low"
    autonomy: str = "balanced"

    @property
    def db_path(self) -> Path:
        return self.home / "jarvis.db"


def load_settings(home: Path = HOME) -> Settings:
    env = {k: v for k, v in dotenv_values(home / ".env").items() if v is not None}
    env.update(os.environ)
    openai_key = env.get("OPENAI_API_KEY") or None
    gemini_key = env.get("GEMINI_API_KEY") or None
    if not openai_key and not gemini_key:
        raise RuntimeError(f"No API key found. Run `jarvis setup`, or add GEMINI_API_KEY or OPENAI_API_KEY "
                           f"to {home / '.env'}")
    # an explicit choice wins; otherwise use whichever key there is, preferring Gemini because it's cheaper
    provider = (env.get("JARVIS_VOICE_PROVIDER") or "").strip().lower() or ("gemini" if gemini_key else "openai")
    required = {"gemini": ("GEMINI_API_KEY", gemini_key), "openai": ("OPENAI_API_KEY", openai_key)}.get(provider)
    if required and not required[1]:
        raise RuntimeError(f"JARVIS_VOICE_PROVIDER={provider} needs {required[0]} in {home / '.env'} "
                           f"(or run `jarvis setup`)")
    return Settings(
        home=home,
        openai_api_key=openai_key,
        projects_root=Path(os.path.expanduser(env.get("JARVIS_PROJECTS_ROOT", "~/Projects"))),
        hotkey=env.get("JARVIS_HOTKEY", "<ctrl>+<alt>+j"),
        input_device=env.get("JARVIS_INPUT_DEVICE", "auto"),
        voice=env.get("JARVIS_VOICE", "cinder"),
        default_language=env.get("JARVIS_DEFAULT_LANGUAGE") or "English",
        wake_threshold=float(env.get("JARVIS_WAKE_THRESHOLD", "0.5")),
        idle_close_s=float(env.get("JARVIS_IDLE_CLOSE_S", "20")),
        away_after_s=float(env.get("JARVIS_AWAY_AFTER_S", "600")),
        confirm_timeout_s=float(env.get("JARVIS_CONFIRM_TIMEOUT_S", "120")),
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=env.get("TELEGRAM_CHAT_ID") or None,
        # billing needs an org Admin key; the ordinary project key gets 403 on the costs endpoint
        openai_admin_key=env.get("OPENAI_ADMIN_KEY") or None,
        voice_provider=provider,
        gemini_api_key=gemini_key,
        gemini_voice=env.get("JARVIS_GEMINI_VOICE") or "Enceladus",
        # not gemini-3.1-flash-live-preview: it can't generate_reply, so Jarvis could never speak first
        gemini_model=env.get("JARVIS_GEMINI_MODEL", "gemini-2.5-flash-native-audio-latest"),
        # the voice user is waiting: sonnet at low effort reached the first action in 3.8s, high effort in 5.5s
        claude_model=env.get("JARVIS_CLAUDE_MODEL") or "sonnet",
        claude_effort=env.get("JARVIS_CLAUDE_EFFORT") or "low",
        # the starting autonomy level; a switch in the panel or menu bar is saved and wins after that
        autonomy=(env.get("JARVIS_AUTONOMY") or "balanced").strip().lower(),
    )
