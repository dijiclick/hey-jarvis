import os
import subprocess

import pytest

from jarvis.projects import Project
from jarvis.store import Store
from jarvis.worker import ClaudeWorker, describe_tool, make_browser_arm_hook


def test_options_carry_the_user_profile(tmp_path, monkeypatch):
    import jarvis.worker as worker_module

    monkeypatch.setattr(worker_module, "_user_profile",
                        lambda: "\n\nWhat you already know about the user:\n- lives in Lisbon")

    async def never(summary):
        return False

    worker = ClaudeWorker(Project("p", tmp_path), Store(tmp_path / "j.db"), never, browser=False)
    append = worker._options(None).system_prompt["append"]
    assert "lives in Lisbon" in append
    assert "Never run anything that waits for typed input" in append


def test_system_prompt_forbids_interactive_commands():
    from jarvis.worker import SYSTEM_APPEND

    assert "Never run anything that waits for typed input" in SYSTEM_APPEND
    assert "BatchMode=yes" in SYSTEM_APPEND and "confirm_with_user" in SYSTEM_APPEND


async def test_browser_arm_hook_only_reacts_to_chrome_tools():
    armed = []
    hook = make_browser_arm_hook(lambda: armed.append(True))
    assert await hook({"tool_name": "mcp__chrome__list_pages"}, "t1", None) == {}
    assert await hook({"tool_name": "Bash", "tool_input": {"command": "ls"}}, "t2", None) == {}
    assert armed == [True]

slow = pytest.mark.skipif(not os.environ.get("JARVIS_SLOW"), reason="set JARVIS_SLOW=1 for real Claude calls")


def test_describe_tool():
    assert describe_tool("Bash", {"command": "npm test"}) == "Running: npm test"
    assert describe_tool("Edit", {"file_path": "/a/b/c.ts"}) == "Editing c.ts"
    assert describe_tool("Write", {"file_path": "/a/new.md"}) == "Writing new.md"
    assert describe_tool("Read", {"file_path": "/a/x.py"}) == "Reading x.py"
    assert describe_tool("mcp__chrome__navigate_page", {"url": "https://x.com"}) == "Browser: navigate page"
    assert describe_tool("Grep", {"pattern": "foo"}) == "Grep"


@slow
async def test_worker_runs_task_and_keeps_session(tmp_path):
    store = Store(tmp_path / "j.db")
    proj_dir = tmp_path / "proj"
    proj_dir.mkdir()

    async def never(summary):
        raise AssertionError(f"unexpected confirmation: {summary}")

    w = ClaudeWorker(Project("proj", proj_dir), store, never, model="haiku", browser=False)
    events = [e async for e in w.run("Create a file named hello.txt containing exactly the word jarvis. Then reply 'created'.")]
    assert (proj_dir / "hello.txt").read_text().strip() == "jarvis"
    assert events[-1][0] == "result"
    assert any(k == "progress" for k, _ in events)
    assert store.get_session("proj")
    events2 = [e async for e in w.run("What is the name of the file you just created? Reply with only the file name.")]
    assert "hello.txt" in events2[-1][1]
    await w.close()


@slow
async def test_worker_guard_blocks_push_to_main(tmp_path):
    store = Store(tmp_path / "j.db")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    asked = []

    async def deny(summary):
        asked.append(summary)
        return False

    w = ClaudeWorker(Project("repo", repo), store, deny, model="haiku", browser=False)
    events = [e async for e in w.run("Run exactly this bash command: git push origin main. Then reply with what happened.")]
    assert asked and "main" in asked[0]
    assert events[-1][0] == "result"
    await w.close()
