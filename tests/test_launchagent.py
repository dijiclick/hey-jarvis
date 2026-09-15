from pathlib import Path

from jarvis.launchagent import LABEL, plist_xml


def test_plist_contains_command_and_logs():
    xml = plist_xml("/Users/me/.local/bin/uv", Path("/repo"), Path("/Users/me/.jarvis/jarvis.log"))
    assert f"<string>{LABEL}</string>" in xml
    assert "<string>/Users/me/.local/bin/uv</string>" in xml
    assert "<string>/repo</string>" in xml
    assert "<string>run</string>" in xml
    assert "<key>RunAtLoad</key>" in xml and "/Users/me/.jarvis/jarvis.log" in xml
