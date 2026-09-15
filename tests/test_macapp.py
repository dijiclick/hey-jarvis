import os
import plistlib
import subprocess
from pathlib import Path

from jarvis.macapp import build_app


def test_build_app_creates_bundle(tmp_path):
    app = build_app(tmp_path, repo=Path("/Users/me/my repo"), sign=False)
    with open(app / "Contents" / "Info.plist", "rb") as f:
        info = plistlib.load(f)
    assert info["CFBundleExecutable"] == "Jarvis"
    assert info["LSUIElement"] is True
    assert "NSMicrophoneUsageDescription" in info
    exe = app / "Contents" / "MacOS" / "Jarvis"
    assert os.access(exe, os.X_OK)
    text = exe.read_text()
    assert "REPO='/Users/me/my repo'" in text
    assert '"$REPO/.venv/bin/jarvis" run' in text
    assert "exec " not in text
    assert 'wait "$child"' in text
    subprocess.run(["bash", "-n", str(exe)], check=True)


def test_build_app_signs_bundle(tmp_path):
    app = build_app(tmp_path, repo=tmp_path)
    out = subprocess.run(["codesign", "--verify", str(app)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
