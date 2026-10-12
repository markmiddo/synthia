import json
import subprocess

import pytest

from synthia import herdr


class Runner:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        out, code, err = reply if isinstance(reply, tuple) else (reply, 0, "")
        return subprocess.CompletedProcess(
            cmd, code, json.dumps(out) if out is not None else "", err
        )


def ok(result):
    return {"id": "x", "result": result}


@pytest.fixture
def run(monkeypatch):
    def install(*replies):
        r = Runner(replies)
        monkeypatch.setattr(herdr.subprocess, "run", r)
        return r

    return install


def test_agent_list(run):
    r = run(ok({"agents": [{"pane_id": "w1:p1", "name": "a"}]}))
    assert herdr.agent_list() == [{"pane_id": "w1:p1", "name": "a"}]
    cmd, kw = r.calls[0]
    assert cmd == ["herdr", "agent", "list"]
    assert kw["timeout"] > 0 and "shell" not in kw


def test_error_carries_herdr_message(run):
    run(({"error": {"code": "agent_not_found", "message": "no such agent"}}, 1, ""))
    with pytest.raises(herdr.HerdrError, match="no such agent"):
        herdr.agent_read("nope")


def test_stderr_used_when_not_json(run):
    run((None, 2, "boom"))
    with pytest.raises(herdr.HerdrError, match="boom"):
        herdr.close_pane("w1:p9")


def test_timeout_and_missing_binary(run):
    run(subprocess.TimeoutExpired("herdr", 1), FileNotFoundError())
    with pytest.raises(herdr.HerdrError, match="timed out"):
        herdr.agent_list()
    with pytest.raises(herdr.HerdrError, match="not installed"):
        herdr.agent_list()


def test_prompt_wait_flags(run):
    r = run(ok({}))
    herdr.agent_prompt("a", "hello", wait=True, timeout_ms=5000)
    assert r.calls[0][0] == [
        "herdr",
        "agent",
        "prompt",
        "a",
        "hello",
        "--wait",
        "--timeout",
        "5000",
    ]


def test_start_claude_args(run):
    r = run(ok({}))
    herdr.start_claude("growth-director", "w1:p3", "claude-opus-5-5", "growth-director")
    assert r.calls[0][0] == [
        "herdr", "agent", "start", "growth-director", "--kind", "claude", "--pane", "w1:p3",
        "--", "--model", "claude-opus-5-5", "--agent", "growth-director",
        "--permission-mode", "bypassPermissions",
    ]  # fmt: skip


def test_start_claude_rejects_bad_name(run):
    run()
    with pytest.raises(herdr.HerdrError, match="invalid agent name"):
        herdr.start_claude("Bad Name", "w1:p3")


def test_split_and_close(run):
    r = run(ok({"pane": {"pane_id": "w1:p7"}}), ok({}))
    assert herdr.split("w1:p3", "right", "/work") == "w1:p7"
    assert r.calls[0][0] == [
        "herdr", "pane", "split", "--pane", "w1:p3", "--direction", "right",
        "--cwd", "/work", "--no-focus",
    ]  # fmt: skip
    herdr.close_pane("w1:p7")
    assert r.calls[1][0] == ["herdr", "pane", "close", "w1:p7"]


def test_pick_direction_by_columns(run):
    def layout(xs):
        return ok(
            {"layout": {"panes": [{"pane_id": str(i), "rect": {"x": x}} for i, x in enumerate(xs)]}}
        )

    run(layout([0, 50]), layout([0, 50, 100]), layout([0, 0, 50]))
    assert herdr.pick_direction("p") == "right"
    assert herdr.pick_direction("p") == "down"
    assert herdr.pick_direction("p") == "right"


def test_ensure_workspace_creates(run):
    r = run(ok({"workspaces": [{"label": "eventflo", "workspace_id": "w1"}]}),
            ok({"root_pane": {"pane_id": "w2:p1"}}))  # fmt: skip
    assert herdr.ensure_workspace("squads", "/work") == "w2:p1"
    assert r.calls[1][0] == [
        "herdr",
        "workspace",
        "create",
        "--label",
        "squads",
        "--no-focus",
        "--cwd",
        "/work",
    ]


def test_ensure_workspace_existing_prefers_agentless_pane(run):
    run(ok({"workspaces": [{"label": "squads", "workspace_id": "w2"}]}),
        ok({"panes": [{"pane_id": "w2:p1", "agent": "claude"}, {"pane_id": "w2:p2"}]}))  # fmt: skip
    assert herdr.ensure_workspace("squads") == "w2:p2"


def test_rename_uses_report_metadata(run):
    r = run(ok({}))
    herdr.rename("w1:p2", "Growth: Writer")
    assert r.calls[0][0] == [
        "herdr",
        "pane",
        "report-metadata",
        "w1:p2",
        "--source",
        "synthia",
        "--title",
        "Growth: Writer",
    ]


def test_agent_read_extracts_text(run):
    run(ok({"read": {"text": "hello"}}))
    assert herdr.agent_read("a", 10) == "hello"
