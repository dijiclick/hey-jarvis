from jarvis.projects import ProjectResolver
from jarvis.store import Store
from jarvis.voice import JarvisTools


class FakeActions:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def act(*args, **kwargs):
            self.calls.append((name, args))
            return f"{name} done."
        return act


class NoAsking:
    """A broker that must never be consulted: small actions don't ask the user."""

    def __getattr__(self, name):
        raise AssertionError(f"the fast lane consulted the approval broker ({name})")


def tools(tmp_path):
    actions = FakeActions()
    t = JarvisTools(None, ProjectResolver(tmp_path), Store(tmp_path / "j.db"), broker=NoAsking(), actions=actions)
    return t, actions


def test_typing_and_pressing_enter_never_asks(tmp_path):
    t, actions = tools(tmp_path)
    t.type_text("send this", True)
    t.press_keys("enter")
    assert actions.calls == [("type_text", ("send this", True)), ("press_keys", ("enter",))]


def test_every_fast_action_reaches_the_mac(tmp_path):
    (tmp_path / "superpower").mkdir()
    (tmp_path / "superpower" / ".git").mkdir()
    t, actions = tools(tmp_path)
    t.open_app("Safari")
    t.open_url("github.com")
    t.vscode_chat("hi")
    t.vscode_chat("hi", "superpower")
    t.open_project("superpower")
    t.frontmost_app()
    assert [name for name, _ in actions.calls] == [
        "open_app", "open_url", "vscode_chat", "vscode_chat", "open_project", "frontmost_app"
    ]


def test_the_voice_can_call_the_fast_lane(tmp_path):
    from livekit.agents.llm.tool_context import get_function_info

    from jarvis.voice import JarvisAgent

    t, _ = tools(tmp_path)
    names = {get_function_info(tool).name for tool in JarvisAgent(None, t, []).tools}
    assert {"open_app", "open_project", "open_url", "type_text", "press_keys", "frontmost_app", "vscode_chat"} <= names


def test_every_fast_action_is_logged_with_its_result(tmp_path, caplog):
    # a fast action that fails silently is how "write it in the VS Code chat" did nothing without a trace
    t, _ = tools(tmp_path)
    with caplog.at_level("INFO", logger="jarvis.voice"):
        t.press_keys("enter")
        t.vscode_chat("hi")
    assert "press_keys" in caplog.text and "press_keys done." in caplog.text
    assert "vscode_chat" in caplog.text and "vscode_chat done." in caplog.text
