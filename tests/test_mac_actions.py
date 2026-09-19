from jarvis.mac_actions import MacActions


class Recorder:
    """Stands in for the shell: records every command instead of touching the Mac."""

    APP_IDS = {"TextEdit": "com.apple.TextEdit", "Visual Studio Code": "com.microsoft.VSCode"}

    def __init__(self, clipboard="", front="Code", fail=False, front_id="com.apple.TextEdit"):
        self.calls, self.clipboard, self.front, self.fail = [], clipboard, front, fail
        self.front_id = front_id

    def __call__(self, cmd, input=None):
        self.calls.append((cmd, input))
        if self.fail:
            return 1, "execution error"
        if cmd == ["pbpaste"]:
            return 0, self.clipboard
        if cmd == ["pbcopy"]:
            self.clipboard = input
        script = " ".join(cmd)
        if cmd[0] == "osascript" and "bundle identifier" in script:
            return 0, self.front_id + "\n"
        if cmd[0] == "osascript" and script.startswith("osascript -e id of application"):
            name = script.split('"')[1]
            return (0, self.APP_IDS[name] + "\n") if name in self.APP_IDS else (1, "Can't get application")
        if cmd[0] == "osascript" and "frontmost" in script:
            return 0, self.front + "\n"
        return 0, ""


def make(**kw):
    rec = Recorder(**kw)
    return MacActions(run=rec, pause=lambda s: None, code_cli="/code", sent_check=lambda prompt, since: True), rec


def scripts(rec):
    """The AppleScript lines sent through osascript, in order."""
    return [line for cmd, _ in rec.calls if cmd[0] == "osascript" for line in cmd[2::2]]


def test_open_app():
    a, rec = make()
    assert "Opened" in a.open_app("Visual Studio Code")
    assert rec.calls[0][0] == ["open", "-a", "Visual Studio Code"]


def test_open_url_adds_https_only_when_missing():
    a, rec = make()
    a.open_url("github.com/dijiclick/hey-jarvis")
    a.open_url("http://localhost:3000")
    assert [c for c, _ in rec.calls] == [["open", "https://github.com/dijiclick/hey-jarvis"],
                                         ["open", "http://localhost:3000"]]


def test_type_text_pastes_then_presses_return():
    a, rec = make()
    a.type_text("سلام جارویس، اینتر زده شد")
    assert ("pbcopy" in rec.calls[1][0] and rec.calls[1][1] == "سلام جارویس، اینتر زده شد")
    lines = scripts(rec)
    paste = next(i for i, s in enumerate(lines) if 'keystroke "v" using {command down}' in s)
    enter = next(i for i, s in enumerate(lines) if "key code 36" in s)
    assert paste < enter


def test_type_text_without_submit_does_not_press_return():
    a, rec = make()
    a.type_text("draft only", submit=False)
    assert not any("key code 36" in s for s in scripts(rec))


def test_type_text_puts_the_users_clipboard_back():
    a, rec = make(clipboard="my own notes")
    a.type_text("hello")
    assert rec.clipboard == "my own notes"


def test_press_keys_with_modifiers():
    a, rec = make()
    a.press_keys("cmd+shift+p")
    assert scripts(rec) == ['tell application "System Events" to keystroke "p" using {command down, shift down}']


def test_press_named_keys():
    a, rec = make()
    a.press_keys("enter")
    a.press_keys("Esc")
    assert scripts(rec) == ['tell application "System Events" to key code 36',
                            'tell application "System Events" to key code 53']


def test_an_unknown_key_runs_nothing():
    a, rec = make()
    assert "don't know" in a.press_keys("hyper+banana")
    assert rec.calls == []


def test_open_project():
    a, rec = make()
    assert "Opened superpower" in a.open_project("/Users/me/Projects/superpower")
    assert rec.calls[0][0] == ["open", "-a", "Visual Studio Code", "/Users/me/Projects/superpower"]


PALETTE = 'tell application "System Events" to keystroke "p" using {command down, shift down}'
PASTE = 'tell application "System Events" to keystroke "v" using {command down}'
ENTER = 'tell application "System Events" to key code 36'


def test_vscode_chat_never_uses_the_cmd_esc_toggle():
    # Cmd+Esc runs "Claude Code: Blur input" when the chat already has focus, so the prompt went nowhere
    a, rec = make(front_id="com.microsoft.VSCode")
    a.vscode_chat("hi")
    assert not any("key code 53 using {command down}" in s for s in scripts(rec))


def test_vscode_chat_focuses_the_chat_by_command_then_pastes_and_sends():
    a, rec = make(front_id="com.microsoft.VSCode")
    a.vscode_chat("What does the Gemini API cost per minute?")
    copied = [text for cmd, text in rec.calls if cmd == ["pbcopy"]]
    assert copied[:2] == ["Claude Code: Focus input", "What does the Gemini API cost per minute?"]
    keys = [s for s in scripts(rec) if s in (PALETTE, PASTE, ENTER)]
    assert keys == [PALETTE, PASTE, ENTER, PASTE, ENTER], "palette, run the focus command, then paste and send"


def test_vscode_chat_says_sent_only_when_the_message_arrived():
    arrived = MacActions(run=Recorder(front_id="com.microsoft.VSCode"), pause=lambda s: None,
                         sent_check=lambda prompt, since: True)
    lost = MacActions(run=Recorder(front_id="com.microsoft.VSCode"), pause=lambda s: None,
                      sent_check=lambda prompt, since: False)
    assert arrived.vscode_chat("hi") == "Sent it to the VS Code chat."
    # measured live: a busy chat saves a queued message only when its current work finishes, so "not seen yet" is not
    # a failure; say what was done instead of "may not have been sent", which made four real sends sound failed
    unconfirmed = lost.vscode_chat("hi")
    assert unconfirmed.startswith("Typed it into the VS Code chat and pressed Enter")
    assert "Sent it" not in unconfirmed and "not have been sent" not in unconfirmed


def test_vscode_chat_with_a_project_opens_it_first():
    a, rec = make(front_id="com.microsoft.VSCode")
    a.vscode_chat("hi", project_path="/Users/me/Projects/superpower")
    assert rec.calls[0][0] == ["open", "-a", "Visual Studio Code", "/Users/me/Projects/superpower"]
    assert PALETTE in scripts(rec)


def test_frontmost_app_is_read():
    a, _ = make(front="Visual Studio Code")
    assert "Visual Studio Code" in a.frontmost_app()


def typed_or_pressed(rec):
    return [c for c, _ in rec.calls if c == ["pbcopy"] or (c[0] == "osascript" and ("keystroke" in c[2] or "key code" in c[2]))]


def test_typing_into_a_named_app_brings_it_forward_first():
    a, rec = make(front_id="com.apple.TextEdit")
    assert a.type_text("سلام", True, app="TextEdit") == "Typed it and pressed Enter."
    assert rec.calls[0][0] == ["open", "-a", "TextEdit"]


def test_typing_is_refused_when_another_app_is_in_front():
    # what really happened: TextEdit never came forward, VS Code stayed in front, and the text was sent into its chat
    a, rec = make(front_id="com.microsoft.VSCode")
    reply = a.type_text("سلام", True, app="TextEdit")
    assert reply.startswith("Couldn't") and "TextEdit" in reply
    assert typed_or_pressed(rec) == [], "nothing may be pasted or pressed into the wrong app"


def test_pressing_keys_is_refused_when_another_app_is_in_front():
    a, rec = make(front_id="com.microsoft.VSCode")
    assert a.press_keys("enter", app="TextEdit").startswith("Couldn't")
    assert typed_or_pressed(rec) == []


def test_an_unknown_target_app_types_nothing():
    a, rec = make()
    assert a.type_text("hi", True, app="NoSuchApp").startswith("Couldn't")
    assert typed_or_pressed(rec) == []


def test_a_failed_action_is_reported_as_failed_not_done():
    a, _ = make(fail=True)
    for reply in (a.open_app("Nope"), a.type_text("x"), a.press_keys("enter"), a.vscode_chat("hi")):
        assert reply.startswith("Couldn't"), reply
