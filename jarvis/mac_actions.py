"""The fast lane: instant actions on the Mac for the voice, with no Claude Code and no screen reading.

A Claude Code job needs 4-5 s just to decide its first step; these run in well under a second, so "press Enter",
"open Safari" or "write this and send it" feel immediate. Anything that needs thought still goes to Claude.
"""
import json
import shutil
import subprocess
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

VSCODE_CLI = "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
CLAUDE_TRANSCRIPTS = Path.home() / ".claude" / "projects"
KEY_CODES = {"enter": 36, "return": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51, "esc": 53,
             "escape": 53, "left": 123, "right": 124, "down": 125, "up": 126}
MODIFIERS = {"cmd": "command down", "command": "command down", "shift": "shift down", "alt": "option down",
             "option": "option down", "ctrl": "control down", "control": "control down"}

Runner = Callable[..., tuple[int, str]]


def run_command(cmd: list[str], input: str | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, input=input, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return done.returncode, (done.stdout or done.stderr or "").strip()


def chat_message_arrived(prompt: str, since: float, root: Path = CLAUDE_TRANSCRIPTS) -> bool:
    """True once a Claude Code chat transcript holds a user message containing prompt, sent at or after since.

    The Claude Code chat writes every message it receives to ~/.claude/projects/<project>/<session>.jsonl, so this
    proves the prompt really reached the chat instead of trusting that the keystrokes landed.
    """
    wanted = " ".join(prompt.split())
    for path in root.glob("*/*.jsonl"):
        try:
            info = path.stat()
            if info.st_mtime < since - 1:
                continue
            with path.open("rb") as f:
                f.seek(max(0, info.st_size - 400_000))
                lines = f.read().decode("utf-8", "ignore").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except ValueError:
                continue
            attachment = record.get("attachment") or {}
            if record.get("type") == "user":
                content = record.get("message", {}).get("content")
            elif record.get("type") == "attachment" and attachment.get("type") == "queued_command":
                # sent while Claude is mid-answer: the chat saves it as a queued command, not as a user turn
                content = attachment.get("prompt")
            else:
                continue
            try:
                sent = datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if sent < since - 1:
                continue
            text = content if isinstance(content, str) else " ".join(
                block.get("text", "") for block in content or [] if isinstance(block, dict))
            if wanted in " ".join(text.split()):
                return True
    return False


def _system_events(action: str) -> list[str]:
    return ["osascript", "-e", f'tell application "System Events" to {action}']


class MacActions:
    def __init__(self, run: Runner = run_command, pause: Callable[[float], None] = time.sleep,
                 code_cli: str | None = None, sent_check: Callable[[str, float], bool] = chat_message_arrived):
        self.run = run
        self.pause = pause
        self.code_cli = code_cli
        self.sent_check = sent_check

    def _ok(self, cmd: list[str]) -> bool:
        return self.run(cmd)[0] == 0

    def _paste(self, text: str) -> bool:
        return self.run(["pbcopy"], input=text)[0] == 0 and self._ok(_system_events('keystroke "v" using {command down}'))

    def _do(self, cmd: list[str], done: str, what: str) -> str:
        code, out = self.run(cmd)
        return done if code == 0 else f"Couldn't {what}: {out.strip()[:200] or 'unknown error'}"

    def open_app(self, name: str) -> str:
        return self._do(["open", "-a", name], f"Opened {name}.", f"open {name}")

    def open_url(self, url: str) -> str:
        target = url if "://" in url else "https://" + url.lstrip("/")
        return self._do(["open", target], f"Opened {target}.", f"open {target}")

    def _bring_forward(self, app: str) -> str | None:
        """Bring app to the front and confirm it really is there. Returns why not, or None when it is.

        Typing into whatever happens to be in front is how a test once sent its text into the wrong chat: a macOS
        prompt kept TextEdit from coming forward and VS Code stayed in front. `open -a` needs no automation
        permission, and the check compares bundle ids, so an app named "Visual Studio Code" whose process is "Code"
        still matches.
        """
        code, out = self.run(["open", "-a", app])
        if code != 0:
            return f"Couldn't open {app}: {out.strip()[:200]}"
        name = app.replace("\\", "\\\\").replace('"', '\\"')
        code, want = self.run(["osascript", "-e", f'id of application "{name}"'])
        want = want.strip()
        if code != 0 or not want:
            return f"Couldn't find the app {app}."
        for _ in range(20):
            code, front = self.run(_system_events("get bundle identifier of first application process whose frontmost is true"))
            if code == 0 and front.strip() == want:
                return None
            self.pause(0.1)
        return f"Couldn't bring {app} to the front, so nothing was typed or pressed."

    def type_text(self, text: str, submit: bool = True, app: str | None = None) -> str:
        """Paste text into the app in front (keystroke garbles non-English text), then press Return to send it.

        With app, that app is brought forward and confirmed first; nothing is typed if it isn't in front.
        """
        if app and (problem := self._bring_forward(app)):
            return problem
        code, previous = self.run(["pbpaste"])
        previous = previous if code == 0 else ""
        code, out = self.run(["pbcopy"], input=text)
        if code != 0:
            return f"Couldn't type it: {out.strip()[:200] or 'the clipboard is unavailable'}"
        self.pause(0.05)
        code, out = self.run(_system_events('keystroke "v" using {command down}'))
        if code != 0:
            return f"Couldn't type into the app in front: {out.strip()[:200]}"
        if submit:
            self.pause(0.15)
            code, out = self.run(_system_events("key code 36"))
            if code != 0:
                return f"Couldn't press Enter: {out.strip()[:200]}"
        self.pause(0.3)
        if previous:
            self.run(["pbcopy"], input=previous)  # leave the user's own clipboard as it was
        return "Typed it and pressed Enter." if submit else "Typed it."

    def press_keys(self, combo: str, app: str | None = None) -> str:
        parts = [p for p in combo.lower().replace(" ", "").split("+") if p]
        if not parts:
            return "I don't know which key to press."
        *mods, key = parts
        if any(m not in MODIFIERS for m in mods) or (key not in KEY_CODES and len(key) != 1):
            return f"I don't know the key '{combo}'."
        if app and (problem := self._bring_forward(app)):
            return problem
        if key in KEY_CODES:
            action = f"key code {KEY_CODES[key]}"
        else:
            action = 'keystroke "' + key.replace("\\", "\\\\").replace('"', '\\"') + '"'
        if mods:
            action += " using {" + ", ".join(MODIFIERS[m] for m in mods) + "}"
        return self._do(_system_events(action), f"Pressed {combo}.", f"press {combo}")

    def frontmost_app(self) -> str:
        code, out = self.run(_system_events("get name of first application process whose frontmost is true"))
        name = out.strip()
        return f"{name} is in front." if code == 0 and name else f"Couldn't tell which app is in front: {name}"

    def open_project(self, path: str, app: str = "Visual Studio Code") -> str:
        """Open a project folder in an application (defaults to VS Code) and bring it to front."""
        code, out = self.run(["open", "-a", app, path])
        if code != 0:
            return f"Couldn't open {path} in {app}: {out.strip()[:200] or 'unknown error'}"
        folder = path.rstrip("/").split("/")[-1] or path
        name_esc = folder.replace("\\", "\\\\").replace('"', '\\"')
        app_esc = app.replace("\\", "\\\\").replace('"', '\\"')
        script = (
            f'tell application "System Events" to tell process "Code"\n'
            f'  set ws to (every window whose name contains "{name_esc}")\n'
            f'  if (count of ws) > 0 then perform action "AXRaise" of (item 1 of ws)\n'
            f'end tell'
        )
        self.run(["osascript", "-e", script])
        return f"Opened {folder} in {app}."

    def vscode_chat(self, prompt: str, project_path: str | None = None) -> str:
        """Write prompt into the Claude Code chat in VS Code and send it; say "sent" only once it really arrived.

        Cmd+Esc can't focus the chat: it runs "Claude Code: Blur input" whenever the chat already has focus, which is
        exactly when the user is talking to it, so the prompt went nowhere. The command palette runs
        "Claude Code: Focus input" by name from anywhere.
        """
        if project_path:
            opened = self.open_project(project_path)
            if opened.startswith("Couldn't"):
                return opened
        if problem := self._bring_forward("Visual Studio Code"):
            return problem
        since = time.time()
        code, previous = self.run(["pbpaste"])
        previous = previous if code == 0 else ""
        try:
            if not self._ok(_system_events('keystroke "p" using {command down, shift down}')):
                return "Couldn't open the VS Code command palette."
            self.pause(0.35)
            if not (self._paste("Claude Code: Focus input") and self._ok(_system_events("key code 36"))):
                return "Couldn't focus the VS Code chat."
            self.pause(0.4)
            if not self._paste(prompt):
                return "Couldn't paste into the VS Code chat."
            self.pause(0.2)
            if not self._ok(_system_events("key code 36")):
                return "Couldn't press Enter in the VS Code chat."
        finally:
            self.pause(0.3)
            if previous:
                self.run(["pbcopy"], input=previous)  # leave the user's own clipboard as it was
        for _ in range(12):
            if self.sent_check(prompt, since):
                return "Sent it to the VS Code chat."
            self.pause(0.25)
        # a busy chat saves a queued message only once its current work finishes, so not seeing it yet is not failure
        return ("Typed it into the VS Code chat and pressed Enter. If Claude there is busy, "
                "it will pick it up when it finishes.")
