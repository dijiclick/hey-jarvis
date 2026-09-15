"""`jarvis setup`: ask four questions, write ~/.jarvis/.env, point to the next step."""
import os
from collections.abc import Callable
from pathlib import Path

from dotenv import dotenv_values

ENGINES = {
    "gemini": ("GEMINI_API_KEY", "Gemini API key (get one at https://aistudio.google.com/apikey)"),
    "openai": ("OPENAI_API_KEY", "OpenAI API key (get one at https://platform.openai.com/api-keys)"),
}


def write_env(home: Path, values: dict[str, str]) -> Path:
    """Set these keys in home/.env, keeping every other line, in a file only the user can read."""
    home.mkdir(parents=True, exist_ok=True)
    path = home / ".env"
    remaining = dict(values)
    lines = []
    for line in (path.read_text().splitlines() if path.exists() else []):
        name = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and name in remaining:
            lines.append(f"{name}={remaining.pop(name)}")
        else:
            lines.append(line)
    lines += [f"{name}={value}" for name, value in remaining.items()]
    # private from the first byte: an API key must never sit in a world-readable file, not even briefly
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, 0o600)
    return path


def run_setup(home: Path, ask: Callable[[str, str], str], ask_secret: Callable[[str], str],
              say: Callable[[str], None]) -> int:
    path = home / ".env"
    saved = {k: v for k, v in dotenv_values(path).items() if v} if path.exists() else {}
    say("Hey Jarvis setup. Press Enter to keep the value in brackets.")

    current = saved.get("JARVIS_VOICE_PROVIDER", "gemini")
    engine = ask(f"Voice engine: gemini (cheaper) or openai [{current}]: ", current).strip().lower() or current
    if engine not in ENGINES:
        say(f"Unknown voice engine '{engine}'. Choose gemini or openai.")
        return 1

    key_name, key_prompt = ENGINES[engine]
    keep = " [saved; Enter keeps it]" if saved.get(key_name) else ""
    key = ask_secret(f"{key_prompt}{keep}: ").strip() or saved.get(key_name, "")
    if not key:
        say(f"No {key_name}, and Jarvis can't talk without one. Run `jarvis setup` again when you have a key.")
        return 1

    language_now = saved.get("JARVIS_DEFAULT_LANGUAGE", "English")
    language = ask(f"Language Jarvis should speak [{language_now}]: ", language_now).strip() or language_now
    root_now = saved.get("JARVIS_PROJECTS_ROOT", "~/Projects")
    root = ask(f"Folder that holds your projects [{root_now}]: ", root_now).strip() or root_now

    write_env(home, {"JARVIS_VOICE_PROVIDER": engine, key_name: key,
                     "JARVIS_DEFAULT_LANGUAGE": language, "JARVIS_PROJECTS_ROOT": root})
    say(f"Saved to {path} (only you can read it).")
    say("Next: `uv run jarvis doctor`, then `uv run jarvis app` and double-click Jarvis.app.")
    return 0
