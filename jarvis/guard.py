import os
import re
import shlex
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Risk:
    category: str
    summary: str


BranchOf = Callable[[Path], str | None]

_SEGMENT_SPLIT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
_DEPLOY = [
    r"\bvercel\b.*--prod\b", r"\bfly(?:ctl)?\s+deploy\b", r"\bdocker\s+push\b",
    r"\b(?:npm|pnpm|yarn)\s+publish\b", r"\beas\s+submit\b", r"\bsupabase\s+db\s+push\b",
    r"\bgit\s+push\s+heroku\b", r"\bnetlify\s+deploy\b.*--prod\b", r"\bterraform\s+apply\b",
    r"\bkubectl\s+(?:apply|delete)\b",
]
_DB_CLIENT = re.compile(r"\b(?:psql|mysql|mongosh)\b")
_DB_WRITE_SQL = re.compile(r"\b(?:insert|update|delete|drop|alter|truncate)\b", re.I)
_DB_MIGRATE = re.compile(r"\bprisma\s+(?:migrate\s+deploy|db\s+push)\b|\bdrizzle-kit\s+push\b")
_READ_PREFIX = ("get_", "list_", "search_", "read_", "check_", "fetch_", "find_")
_SEND = re.compile(r"(^|_)(send|reply|forward|post)(_|$)")

# how much Claude may do without a spoken yes; the user switches it from the panel or the menu bar
LEVELS = ("full", "balanced", "careful")
DEFAULT_LEVEL = "balanced"


def current_branch(cwd: Path) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return (out.stdout.strip() or None) if out.returncode == 0 else None


def _tokens(segment: str) -> list[str]:
    try:
        toks = shlex.split(segment)
    except ValueError:
        toks = segment.split()
    while toks and (toks[0] == "sudo" or re.match(r"^\w+=", toks[0])):
        toks.pop(0)
    return toks


def _git_push(toks: list[str], cwd: Path, branch_of: BranchOf) -> Risk | None:
    if len(toks) >= 3 and toks[:3] == ["gh", "pr", "merge"]:
        return Risk("git_push", "merge a pull request: " + " ".join(toks))
    if not toks or toks[0] != "git" or "push" not in toks:
        return None
    args = toks[toks.index("push") + 1:]
    flags = [a for a in args if a.startswith("-")]
    refspecs = [a for a in args if not a.startswith("-")][1:]
    if any(f in ("-f", "--force") or f.startswith("--force") for f in flags) or any(r.startswith("+") for r in refspecs):
        return Risk("git_push", "force push: " + " ".join(toks))
    if any(r.lstrip("+").split(":")[-1] in ("main", "master") for r in refspecs):
        return Risk("git_push", f"push to main in {cwd.name}")
    if not refspecs and branch_of(cwd) in ("main", "master"):
        return Risk("git_push", f"push to main in {cwd.name}")
    return None


def _delete(toks: list[str], cwd: Path) -> Risk | None:
    if not toks or os.path.basename(toks[0]) not in ("rm", "rmdir", "unlink", "trash"):
        return None
    flags = [t for t in toks[1:] if t.startswith("-")]
    targets = [t for t in toks[1:] if not t.startswith("-")]
    recursive = "--recursive" in flags or any("r" in f.lower() for f in flags if not f.startswith("--"))
    home = Path.home()
    summary = "delete " + " ".join(targets)
    if cwd == home and recursive:
        return Risk("delete", summary)
    for t in targets:
        t = t.replace("${HOME}", str(home)).replace("$HOME", str(home))
        if "$" in t or "`" in t:
            return Risk("delete", summary)
        p = Path(os.path.expanduser(t))
        resolved = Path(os.path.normpath(p if p.is_absolute() else cwd / p))
        if cwd not in resolved.parents:
            return Risk("delete", summary)
    return None


def _bash(command: str, cwd: Path, branch_of: BranchOf) -> Risk | None:
    short = command.strip()[:160]
    for segment in _SEGMENT_SPLIT.split(command):
        toks = _tokens(segment)
        if not toks or toks[0] in ("echo", "printf"):
            continue
        risk = _git_push(toks, cwd, branch_of) or _delete(toks, cwd)
        if risk:
            return risk
        if toks[0] == "git" and "commit" in toks:
            continue
        joined = " ".join(toks)
        if any(re.search(p, joined) for p in _DEPLOY):
            return Risk("deploy", "deploy: " + short)
        if _DB_MIGRATE.search(joined) or (
            _DB_CLIENT.search(joined) and _DB_WRITE_SQL.search(joined)
            and not re.search(r"localhost|127\.0\.0\.1", joined)
        ):
            return Risk("db_write", "database write: " + short)
    return None


def _mcp(tool_name: str) -> Risk | None:
    parts = tool_name.split("__")
    action = parts[-1].lower()
    service = parts[1].removeprefix("claude_ai_") if len(parts) > 2 else tool_name
    if action.startswith(_READ_PREFIX) or "draft" in action:
        return None
    label = f"{action.replace('_', ' ')} via {service}"
    if re.search(r"(^|_)(buy|purchase|checkout|pay|payment)(_|$)", action):
        return Risk("payment", label)
    if re.search(r"(^|_)deploy(_|$)", action):
        return Risk("deploy", label)
    return None


def _careful(tool_name: str, tool_input: dict[str, Any]) -> Risk | None:
    """What only the careful level asks about: any push, and anything sent to another person."""
    if tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        for segment in _SEGMENT_SPLIT.split(command):
            toks = _tokens(segment)
            if toks[:1] == ["git"] and "push" in toks:
                return Risk("git_push", "push: " + " ".join(toks))
        return None
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__")
        action = parts[-1].lower()
        if _SEND.search(action) and "draft" not in action:
            service = parts[1].removeprefix("claude_ai_") if len(parts) > 2 else tool_name
            return Risk("message", f"{action.replace('_', ' ')} via {service}")
    return None


def classify(tool_name: str, tool_input: dict[str, Any], cwd: Path, branch_of: BranchOf = current_branch,
             level: str = DEFAULT_LEVEL) -> Risk | None:
    risk = None
    if tool_name == "Bash":
        risk = _bash(str(tool_input.get("command", "")), cwd, branch_of)
    elif tool_name.startswith("mcp__"):
        risk = _mcp(tool_name)
    if level == "full":
        # even full autonomy stops before spending money: a wrong purchase is the hardest thing to undo
        return risk if risk is not None and risk.category == "payment" else None
    if level == "careful" and risk is None:
        return _careful(tool_name, tool_input)
    return risk


def make_guard_hook(cwd: Path, confirm: Callable[[str], Awaitable[bool]], branch_of: BranchOf = current_branch,
                    level: Callable[[], str] = lambda: DEFAULT_LEVEL):
    async def hook(hook_input: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        where = Path(hook_input.get("cwd") or cwd)
        # read on every call, so a switch in the panel applies to jobs that are already running
        risk = classify(hook_input.get("tool_name", ""), hook_input.get("tool_input") or {}, where, branch_of,
                        level=level())
        if risk is None:
            return {}
        if await confirm(risk.summary):
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}
        return {"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": f"The user did not approve: {risk.summary}. Do not retry it; say it was skipped.",
        }}

    return hook
