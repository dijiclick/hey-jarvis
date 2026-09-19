from pathlib import Path

import pytest

from jarvis.guard import classify, make_guard_hook

P = Path("/Users/me/Projects/app")


def bash(cmd, branch="feature", cwd=P):
    return classify("Bash", {"command": cmd}, cwd, lambda _: branch)


@pytest.mark.parametrize("cmd", [
    "npm test", "git status", "git push origin feature", "git push", "rm -rf node_modules",
    "rm dist/a.js", "rm -rf ./build/*", "vercel", "psql -h localhost -c 'insert into t values (1)'",
    "echo 'rm -rf is dangerous'", "git commit -m 'deploy docs'",
    "curl https://api.telegram.org/bot123:abc/sendMessage -d text=hi",
])
def test_allowed_commands(cmd):
    assert bash(cmd) is None


@pytest.mark.parametrize("cmd,cat", [
    ("git push origin main", "git_push"),
    ("git push -f", "git_push"),
    ("git push --force-with-lease origin feat", "git_push"),
    ("git push origin +feat", "git_push"),
    ("gh pr merge 12 --squash", "git_push"),
    ("rm -rf ~/Documents/old", "delete"),
    ("rm -rf /tmp/../Users/me/x", "delete"),
    ("rm -rf ../other", "delete"),
    ("rm -rf $HOME/x", "delete"),
    ("cd x && rm -rf /", "delete"),
    ("sudo rm -rf /Users/me/Projects/app", "delete"),
    ("vercel --prod", "deploy"),
    ("vercel deploy --prod --yes", "deploy"),
    ("fly deploy", "deploy"),
    ("docker push me/img", "deploy"),
    ("npm publish", "deploy"),
    ("psql $DATABASE_URL -c 'DELETE FROM users'", "db_write"),
    ("npx prisma migrate deploy", "db_write"),
])
def test_blocked_commands(cmd, cat):
    risk = bash(cmd)
    assert risk is not None and risk.category == cat


def test_plain_push_on_main_confirms():
    assert bash("git push", branch="main").category == "git_push"


def test_home_project_recursive_rm_confirms():
    assert bash("rm -rf Downloads/x", cwd=Path.home()).category == "delete"


@pytest.mark.parametrize("tool,cat", [
    ("mcp__claude_ai_Vercel__buy_domain", "payment"),
    ("mcp__claude_ai_Vercel__deploy_to_vercel", "deploy"),
])
def test_blocked_tools(tool, cat):
    assert classify(tool, {}, P, lambda _: None).category == cat


@pytest.mark.parametrize("tool", [
    "mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__search_threads",
    "mcp__claude_ai_Vercel__get_purchase_quote", "mcp__claude_ai_Vercel__get_deployment",
    "Read", "Edit", "mcp__chrome__click",
    "mcp__claude_ai_Gmail__send_message", "mcp__claude_ai_Gmail__reply", "mcp__claude_ai_Gmail__forward",
    "mcp__slack__post_message",
])
def test_allowed_tools(tool):
    assert classify(tool, {"file_path": "/Users/me/Projects/app/a.ts"}, P, lambda _: None) is None


async def test_hook_denies_when_user_says_no():
    asked = []

    async def confirm(summary):
        asked.append(summary)
        return False

    hook = make_guard_hook(P, confirm, branch_of=lambda _: "feature")
    out = await hook({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(P)}, "t1", None)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "main" in asked[0]


async def test_hook_allows_on_yes_and_passes_safe_calls():
    async def confirm(summary):
        return True

    hook = make_guard_hook(P, confirm, branch_of=lambda _: "feature")
    out = await hook({"tool_name": "Bash", "tool_input": {"command": "vercel --prod"}, "cwd": str(P)}, "t1", None)
    assert out["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert await hook({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": str(P)}, "t2", None) == {}


def at(level, tool, tool_input=None):
    return classify(tool, tool_input or {}, P, lambda _: "feature", level=level)


def test_balanced_is_the_default_and_unchanged():
    assert at("balanced", "Bash", {"command": "git push origin main"}).category == "git_push"
    assert at("balanced", "Bash", {"command": "git push origin feature"}) is None
    assert at("balanced", "mcp__claude_ai_Gmail__send_message") is None


@pytest.mark.parametrize("tool,tool_input", [
    ("Bash", {"command": "git push origin main"}),
    ("Bash", {"command": "vercel --prod"}),
    ("Bash", {"command": "rm -rf ~/Documents/old"}),
    ("mcp__claude_ai_Vercel__deploy_to_vercel", {}),
])
def test_full_auto_never_asks(tool, tool_input):
    assert at("full", tool, tool_input) is None


def test_full_auto_still_asks_before_paying():
    assert at("full", "mcp__claude_ai_Vercel__buy_domain").category == "payment"


@pytest.mark.parametrize("tool,tool_input,cat", [
    ("Bash", {"command": "git push origin feature"}, "git_push"),
    ("Bash", {"command": "git push"}, "git_push"),
    ("mcp__claude_ai_Gmail__send_message", {}, "message"),
    ("mcp__claude_ai_Gmail__reply", {}, "message"),
    ("mcp__claude_ai_Gmail__forward", {}, "message"),
    ("mcp__slack__post_message", {}, "message"),
])
def test_careful_also_asks_before_any_push_and_before_sending(tool, tool_input, cat):
    assert at("careful", tool, tool_input).category == cat


@pytest.mark.parametrize("tool,tool_input", [
    ("Bash", {"command": "npm test"}),
    ("Bash", {"command": "git commit -m 'x'"}),
    ("mcp__claude_ai_Gmail__create_draft", {}),
    ("mcp__claude_ai_Gmail__search_threads", {}),
])
def test_careful_leaves_safe_work_alone(tool, tool_input):
    assert at("careful", tool, tool_input) is None


async def test_hook_reads_the_level_on_every_call():
    asked = []

    async def confirm(summary):
        asked.append(summary)
        return True

    level = {"value": "balanced"}
    hook = make_guard_hook(P, confirm, branch_of=lambda _: "feature", level=lambda: level["value"])
    call = {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}, "cwd": str(P)}
    await hook(call, None, None)
    assert len(asked) == 1
    level["value"] = "full"
    assert await hook(call, None, None) == {}
    assert len(asked) == 1
