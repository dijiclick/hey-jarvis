"""Build Jarvis.app: a double-clickable menu-bar launcher for this repo."""
import plistlib
import shlex
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BUNDLE_ID = "com.jarvis.voice.app"

LAUNCHER = """#!/bin/bash
# Jarvis.app launcher. Python runs as a child (not exec) so macOS attributes Microphone and
# Accessibility permissions to Jarvis.app instead of to the shared python binary.
REPO={repo}
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p "$HOME/.jarvis"
if [ ! -x "$REPO/.venv/bin/jarvis" ]; then
  uv sync --project "$REPO" >> "$HOME/.jarvis/launcher.log" 2>&1
fi
cd "$REPO"
"$REPO/.venv/bin/jarvis" run >> "$HOME/.jarvis/launcher.log" 2>&1 &
child=$!
trap 'kill "$child" 2>/dev/null' TERM INT HUP
wait "$child"
"""


def info_plist() -> dict:
    return {
        "CFBundleName": "Jarvis",
        "CFBundleDisplayName": "Jarvis",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "Jarvis",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "LSMinimumSystemVersion": "13.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Jarvis listens for \"Hey Jarvis\" and your voice commands.",
        "NSAppleEventsUsageDescription": "Jarvis controls apps on your Mac when you ask it to.",
    }


def build_app(dest: Path, repo: Path = REPO, sign: bool = True) -> Path:
    app = dest / "Jarvis.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    (app / "Contents" / "Resources").mkdir(exist_ok=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info_plist(), f)
    exe = macos / "Jarvis"
    exe.write_text(LAUNCHER.format(repo=shlex.quote(str(repo))))
    exe.chmod(0o755)
    if sign:
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True, capture_output=True)
    return app
