import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext

from synthia.brain.gate import classify, describe, make_can_use_tool


@pytest.mark.parametrize(
    "tool,inp,expected",
    [
        ("Bash", {"command": "ls -la"}, "allow"),
        ("Bash", {"command": "rm -rf /"}, "deny"),
        ("Bash", {"command": "git push origin main"}, "confirm"),
        ("Bash", {"command": "git push --force origin feat/x"}, "confirm"),
        ("Bash", {"command": "ssh server 'sudo systemctl restart eva-core'"}, "confirm"),
        ("Bash", {"command": "mongosh prod --eval 'db.users.deleteMany({})'"}, "confirm"),
        ("Bash", {"command": "gh pr merge 123"}, "confirm"),
        ("Write", {"file_path": "/home/markmiddo/dev/eventflo/README.md"}, "allow"),
        ("Write", {"file_path": "/home/markmiddo/.ssh/authorized_keys"}, "deny"),
        ("Read", {"file_path": "/home/markmiddo/dev/eventflo/x.py"}, "allow"),
        ("Bash", {"command": "cargo build --release"}, "allow"),
        ("Bash", {"command": "systemctl --user restart eva-core.service"}, "confirm"),
        ("Bash", {"command": 'git commit -m "revert git push behavior"'}, "allow"),
        ("Bash", {"command": "echo git push origin main"}, "allow"),
        ("Bash", {"command": "git status && git push"}, "confirm"),
        ("Bash", {"command": "npm run deploy"}, "confirm"),
        ("Bash", {"command": "./deploy.sh production"}, "confirm"),
        ("Bash", {"command": "rm -rf node_modules"}, "confirm"),
        ("Bash", {"command": "gh release create v1.2"}, "confirm"),
        ("mcp__claude_ai_Gmail__send_message", {}, "confirm"),
        ("mcp__claude_ai_Gmail__search_threads", {}, "allow"),
        ("mcp__claude_ai_Notion__notion-update-page", {}, "confirm"),
        ("mcp__claude_ai_Google_Drive__share_file", {}, "confirm"),
        ("mcp__eva-core__task_dispatch", {}, "confirm"),
        ("mcp__eva-core__job_list", {}, "allow"),
        ("mcp__jobs__dispatch_job", {}, "allow"),
        ("TodoWrite", {"todos": []}, "allow"),
    ],
)
def test_classify(tool, inp, expected):
    decision, _reason = classify(tool, inp)
    assert decision == expected


def test_describe_bash_and_write():
    assert describe("Bash", {"command": "git push origin main"}) == "run git push origin main"
    assert describe("Write", {"file_path": "/a/b.py"}) == "write /a/b.py"
    assert describe("Edit", {"file_path": "/a/b.py"}) == "edit /a/b.py"
    assert describe("Weird", {"x": 1}) == "use Weird"


def test_describe_truncates_long_commands():
    spoken = describe("Bash", {"command": "echo " + "x" * 400})
    assert len(spoken) <= len("run ") + 120
    assert spoken.endswith("\u2026")


def test_describe_mcp_strips_the_prefix():
    assert describe("mcp__claude_ai_Gmail__send_message", {}) == "use claude_ai_Gmail send_message"


async def test_can_use_tool_paths():
    asked: list[str] = []

    async def say_yes(q):
        asked.append(q)
        return True

    async def say_no(q):
        asked.append(q)
        return False

    ctx = ToolPermissionContext()
    allow = make_can_use_tool(say_yes)
    assert isinstance(await allow("Bash", {"command": "ls"}, ctx), PermissionResultAllow)
    assert asked == []
    assert isinstance(await allow("Bash", {"command": "rm -rf /"}, ctx), PermissionResultDeny)
    assert asked == []
    res = await allow("Bash", {"command": "git push origin main"}, ctx)
    assert isinstance(res, PermissionResultAllow)
    assert asked == ["run git push origin main"]

    deny = make_can_use_tool(say_no)
    res = await deny("Bash", {"command": "git push origin main"}, ctx)
    assert isinstance(res, PermissionResultDeny)
    assert "not confirmed" in res.message
