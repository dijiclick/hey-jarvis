import os
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape

LABEL = "com.jarvis.voice"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
REPO = Path(__file__).resolve().parent.parent


def plist_xml(uv: str, repo: Path, log_path: Path) -> str:
    args = [uv, "run", "--project", str(repo), "jarvis", "run"]
    arg_xml = "".join(f"<string>{escape(a)}</string>" for a in args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{LABEL}</string>
<key>ProgramArguments</key><array>{arg_xml}</array>
<key>WorkingDirectory</key><string>{escape(str(repo))}</string>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
<key>ProcessType</key><string>Interactive</string>
<key>StandardOutPath</key><string>{escape(str(log_path))}</string>
<key>StandardErrorPath</key><string>{escape(str(log_path))}</string>
</dict></plist>
"""


def install() -> int:
    uv = shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")
    log_path = Path.home() / ".jarvis" / "jarvis.log"
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(plist_xml(uv, REPO, log_path))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(PLIST)], capture_output=True)
    r = subprocess.run(["launchctl", "bootstrap", domain, str(PLIST)], capture_output=True, text=True)
    print(f"Installed {PLIST}" if r.returncode == 0 else f"launchctl failed: {r.stderr.strip()}")
    return r.returncode


def uninstall() -> int:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(PLIST)], capture_output=True)
    PLIST.unlink(missing_ok=True)
    print("Removed", PLIST)
    return 0
