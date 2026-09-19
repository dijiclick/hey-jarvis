"""What Jarvis knows about the user.

A small markdown file at ~/.jarvis/profile.md, read into every voice conversation and into Claude's system prompt,
so Jarvis doesn't ask again for things it was already told. The user adds facts by voice ("remember that ..."),
and Claude can edit the file directly.
"""
from pathlib import Path

PROFILE_NAME = "profile.md"
HEADER = "# About the user"


def profile_path(home: Path) -> Path:
    return home / PROFILE_NAME


def load_profile(home: Path) -> str:
    try:
        return profile_path(home).read_text().strip()
    except (FileNotFoundError, NotADirectoryError):
        return ""


def remember_fact(home: Path, fact: str) -> str:
    """Append one fact; returns the stored text, or "" if it was empty or already known."""
    fact = " ".join(fact.split()).strip(" -•")
    if not fact:
        return ""
    existing = load_profile(home)
    if fact.lower() in existing.lower():
        return fact
    path = profile_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        if not existing:
            f.write(f"{HEADER}\n")
        f.write(f"- {fact}\n")
    return fact


PROJECTS_NAME = "projects.md"
MEMORIES_NAME = "memories.md"


def memories_path(home: Path) -> Path:
    """Facts long-term memory learned from past conversations, rewritten after each one."""
    return home / MEMORIES_NAME


def load_memories(home: Path) -> str:
    try:
        return memories_path(home).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError, TypeError):
        return ""


def load_projects(home: Path) -> str:
    try:
        return (home / PROJECTS_NAME).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, NotADirectoryError):
        return ""


def projects_summary(home: Path) -> str:
    """One line per project — small enough for the voice model's fixed instructions."""
    lines = []
    name = None
    for line in load_projects(home).splitlines():
        if line.startswith("## "):
            name = line[3:].split("(")[0].strip()
        elif name and "what it is:" in line:
            lines.append(f"- {name}: {line.split('what it is:', 1)[1].strip()}")
            name = None
    return "\n".join(lines)


def profile_block(home: Path, projects: bool = True) -> str:
    """The block appended to prompts; empty when nothing is known yet."""
    parts = []
    if text := load_profile(home):
        parts.append("What you already know about the user (use it, don't ask again):\n" + text)
    if learned := load_memories(home):
        parts.append("What you learned about the user in past conversations (use it, don't ask again):\n" + learned)
    if projects and (summary := projects_summary(home)):
        parts.append("The user's projects:\n" + summary)
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


def full_knowledge_block(home: Path) -> str:
    """Everything, including the long project detail — for Claude, which has room for it."""
    parts = []
    if text := load_profile(home):
        parts.append("What you already know about the user:\n" + text)
    if learned := load_memories(home):
        parts.append("What you learned about the user in past conversations:\n" + learned)
    if projects := load_projects(home):
        parts.append("The user's projects, surveyed from disk:\n" + projects)
    return ("\n\n" + "\n\n".join(parts)) if parts else ""
