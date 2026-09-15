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
    ("curl https://api.telegram.org/bot123:abc/sendMessage -d text=hi", "message"),
])
def test_blocked_commands(cmd, cat):
    risk = bash(cmd)
    assert risk is not None and risk.category == cat


def test_plain_push_on_main_confirms():
    assert bash("git push", branch="main").category == "git_push"


def test_home_project_recursive_rm_confirms():
    assert bash("rm -rf Downloads/x", cwd=Path.home()).category == "delete"


@pytest.mark.parametrize("tool,cat", [
    ("mcp__claude_ai_Gmail__send_message", "message"),
    ("mcp__claude_ai_Gmail__reply", "message"),
    ("mcp__claude_ai_Gmail__forward", "message"),
    ("mcp__slack__post_message", "message"),
    ("mcp__claude_ai_Vercel__buy_domain", "payment"),
    ("mcp__claude_ai_Vercel__deploy_to_vercel", "deploy"),
])
def test_blocked_tools(tool, cat):
    assert classify(tool, {}, P, lambda _: None).category == cat


@pytest.mark.parametrize("tool", [
    "mcp__claude_ai_Gmail__create_draft", "mcp__claude_ai_Gmail__search_threads",
    "mcp__claude_ai_Vercel__get_purchase_quote", "mcp__claude_ai_Vercel__get_deployment",
    "Read", "Edit", "mcp__chrome__click",
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
