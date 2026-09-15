import asyncio
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    ResultMessage,
    TextBlock,
    ToolUseBlock,
    create_sdk_mcp_server,
    tool,
)

from .guard import make_guard_hook
from .projects import Project
from .store import Store

log = logging.getLogger("jarvis.worker")

# pinned so npx serves it from cache instead of checking the registry on every start
CHROME_MCP = "chrome-devtools-mcp@1.9.0"

SYSTEM_APPEND = """
You are being driven by voice through Jarvis. The user hears a short spoken summary, not your screen output.
- You have full access to this Mac: shell, osascript, `open`, files, the user's real logged-in Chrome through the
  chrome MCP tools, and the user's MCP connectors (Gmail, Calendar, Drive, Vercel, ...). Work autonomously.
- To open or control macOS apps use `open -a "App"` or osascript. For web tasks prefer the chrome MCP tools.
- Nobody is at the keyboard. Never run anything that waits for typed input. `sudo` works without a password,
  SSH keys and GitHub credentials are already loaded, and SSH accepts new hosts. Always use non-interactive flags
  (`-y`, `--yes`, `--non-interactive`, `DEBIAN_FRONTEND=noninteractive`, `GIT_TERMINAL_PROMPT=0`, `ssh -o BatchMode=yes`).
- Before sending any message or email, or paying/purchasing anything through a browser or app, call
  mcp__jarvis__confirm_with_user and continue only if it returns "approved".
- If an action is denied by the user, don't retry it; mention it was skipped.
- Verify before you report. Finishing without an error is not proof it worked: check the actual result (read the
  file back, run the test, query the row, load the page) and say what you observed. If you could not verify, say so
  plainly instead of saying it is done.
- Finish every task with a final reply of 1-3 plain sentences: what you did and the outcome (e.g. whether tests
  pass). No markdown, no code, no long paths. If you need information from the user, end with one clear question.
"""


def describe_tool(name: str, tool_input: dict[str, Any]) -> str:
    def base(key: str) -> str:
        return os.path.basename(str(tool_input.get(key, "")))

    if name == "Bash":
        return "Running: " + str(tool_input.get("command", ""))[:100]
    if name in ("Edit", "MultiEdit"):
        return "Editing " + base("file_path")
    if name == "Write":
        return "Writing " + base("file_path")
    if name == "Read":
        return "Reading " + base("file_path")
    if name.startswith("mcp__chrome__"):
        return "Browser: " + name.removeprefix("mcp__chrome__").replace("_", " ")
    return name


def make_browser_arm_hook(arm: Callable[[], None]):
    """PreToolUse hook: a browser tool is about to connect to Chrome, so watch for its permission prompt."""
    async def hook(hook_input: dict[str, Any], tool_use_id: str | None, context: Any) -> dict[str, Any]:
        if str(hook_input.get("tool_name", "")).startswith("mcp__chrome__"):
            arm()
        return {}

    return hook


def _user_profile() -> str:
    """Facts the user told Jarvis, plus the surveyed projects, so Claude knows them too."""
    from .config import HOME
    from .profile import full_knowledge_block

    return full_knowledge_block(HOME)


class WorkerError(Exception):
    pass


class ClaudeWorker:
    def __init__(self, project: Project, store: Store, confirm: Callable[[str], Awaitable[bool]], *,
                 model: str | None = None, browser: bool = True, hook_timeout_s: float = 150,
                 on_browser_tool: Callable[[], None] | None = None):
        self.project = project
        self.store = store
        self.confirm = confirm
        self.model = model
        self.browser = browser
        self.hook_timeout_s = hook_timeout_s
        self.on_browser_tool = on_browser_tool if browser else None
        self._client: ClaudeSDKClient | None = None
        self._connect_lock = asyncio.Lock()

    def _options(self, resume: str | None) -> ClaudeAgentOptions:
        @tool("confirm_with_user",
              "Ask the user by voice to approve a sensitive action such as sending a message or paying. "
              "Returns 'approved' or 'denied'.",
              {"action": str})
        async def confirm_with_user(args: dict[str, Any]) -> dict[str, Any]:
            ok = await self.confirm(str(args.get("action", "an action")))
            return {"content": [{"type": "text", "text": "approved" if ok else "denied"}]}

        mcp: dict[str, Any] = {"jarvis": create_sdk_mcp_server("jarvis", tools=[confirm_with_user])}
        if self.browser:
            mcp["chrome"] = {"type": "stdio", "command": "npx", "args": ["-y", CHROME_MCP, "--autoConnect"]}
        hooks = [make_guard_hook(self.project.path, self.confirm)]
        if self.on_browser_tool is not None:
            hooks.insert(0, make_browser_arm_hook(self.on_browser_tool))
        return ClaudeAgentOptions(
            cwd=str(self.project.path),
            permission_mode="bypassPermissions",
            setting_sources=["user", "project", "local"],
            system_prompt={"type": "preset", "preset": "claude_code",
                           "append": SYSTEM_APPEND + _user_profile()},
            mcp_servers=mcp,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=hooks, timeout=self.hook_timeout_s)]},
            resume=resume,
            model=self.model,
            # browsing and log-reading jobs blew past the 1 MB default and died with CLIJSONDecodeError
            max_buffer_size=32 * 1024 * 1024,
        )

    async def _connect(self) -> ClaudeSDKClient:
        async with self._connect_lock:
            if self._client is not None:
                return self._client
            resume = self.store.get_session(self.project.name)
            if self.on_browser_tool is not None:
                self.on_browser_tool()  # the browser MCP may attach while the session starts
            client = ClaudeSDKClient(self._options(resume))
            try:
                await client.connect()
            except Exception:
                if resume is None:
                    raise
                log.warning("resume of %s failed; starting a fresh session", self.project.name)
                client = ClaudeSDKClient(self._options(None))
                await client.connect()
            self._client = client
            return client

    async def warm(self) -> None:
        """Start Claude Code and its MCP servers ahead of the first job."""
        await self._connect()

    async def run(self, prompt: str) -> AsyncIterator[tuple[str, str]]:
        client = await self._connect()
        await client.query(prompt)
        last_text = ""
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text.strip():
                        last_text = block.text.strip()
                        yield "progress", last_text[:300]
                    elif isinstance(block, ToolUseBlock):
                        yield "progress", describe_tool(block.name, block.input)
            elif isinstance(msg, ResultMessage):
                if msg.session_id:
                    self.store.set_session(self.project.name, msg.session_id)
                if msg.is_error:
                    raise WorkerError(msg.result or msg.subtype)
                yield "result", (msg.result or last_text or "Done.")

    async def interrupt(self) -> None:
        if self._client is not None:
            await self._client.interrupt()

    async def close(self) -> None:
        if self._client is not None:
            client, self._client = self._client, None
            await client.disconnect()
