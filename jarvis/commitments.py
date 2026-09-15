"""What the user said they would do.

Goal monitoring works better when progress is reported to someone else, so Jarvis keeps the list and asks about it.
Commitments live in ~/.jarvis/commitments.md — plain markdown, so Claude can read and tick them off too.
"""
import datetime as dt
import re
from pathlib import Path

COMMITMENTS_NAME = "commitments.md"
HEADER = "# Commitments"
OPEN_MARK, DONE_MARK = "- [ ]", "- [x]"


def commitments_path(home: Path) -> Path:
    return home / COMMITMENTS_NAME


def load_commitments(home: Path) -> str:
    try:
        return commitments_path(home).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return ""


def open_commitments(home: Path) -> list[str]:
    return [line[len(OPEN_MARK):].strip()
            for line in load_commitments(home).splitlines() if line.startswith(OPEN_MARK)]


def add_commitment(home: Path, text: str, today: dt.date | None = None) -> str:
    """Record one promise. Returns the stored line, or "" when there was nothing to store."""
    text = " ".join(text.split()).strip(" -•")
    if not text:
        return ""
    day = (today or dt.date.today()).isoformat()
    entry = f"{day} — {text}"
    existing = load_commitments(home)
    if text.lower() in existing.lower():
        return entry
    path = commitments_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        if not existing:
            f.write(f"{HEADER}\n")
        f.write(f"{OPEN_MARK} {entry}\n")
    return entry


def complete_commitment(home: Path, needle: str) -> str | None:
    """Tick off the first open commitment containing `needle`; returns it, or None if nothing matched."""
    text = load_commitments(home)
    if not text:
        return None
    needle = needle.strip().lower()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith(OPEN_MARK) and needle and needle in line.lower():
            lines[i] = DONE_MARK + line[len(OPEN_MARK):]
            commitments_path(home).write_text("\n".join(lines) + "\n", encoding="utf-8")
            return line[len(OPEN_MARK):].strip()
    return None


def overdue(home: Path, today: dt.date | None = None) -> list[str]:
    """Open commitments made before today — the ones worth asking about."""
    day = today or dt.date.today()
    out = []
    for line in open_commitments(home):
        match = re.match(r"(\d{4}-\d{2}-\d{2})\s*—\s*(.*)", line)
        if match and dt.date.fromisoformat(match.group(1)) < day:
            out.append(line)
    return out
