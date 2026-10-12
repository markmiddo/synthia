import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from synthia.hooks import memory_recall_log as hook

NOW = datetime(2026, 10, 13, 8, 21, 5, 123000, tzinfo=timezone.utc)


@pytest.fixture
def env(tmp_path):
    home = tmp_path / "home"
    mem = home / ".claude" / "projects" / "-home-me-proj" / "memory"
    mem.mkdir(parents=True)
    (mem / "feedback_rules.md").write_text(
        "---\nname: Never use Codex\ndescription: x\n---\nbody\n"
    )
    (mem / "plain.md").write_text("no frontmatter\n")
    (mem / "MEMORY.md").write_text("# index\n")
    return home, mem, tmp_path / "log" / "recalls.jsonl"


def run(env, tool, path, **extra):
    home, _, log = env
    payload = {
        "tool_name": tool,
        "tool_input": {"file_path": str(path)},
        "cwd": "/work",
        "session_id": "s1",
        **extra,
    }
    return hook.log_recall(payload, home=str(home), log_path=str(log), now=NOW, pane="w1:p2")


def lines(log):
    return [json.loads(x) for x in log.read_text().splitlines()]


def test_memory_read_is_logged(env):
    _, mem, log = env
    assert run(env, "Read", mem / "feedback_rules.md")
    (entry,) = lines(log)
    assert entry == {
        "at": "2026-10-13T08:21:05.123Z",
        "kind": "read",
        "file": str(mem / "feedback_rules.md"),
        "title": "Never use Codex",
        "cwd": "/work",
        "session_id": "s1",
        "pane": "w1:p2",
    }


def test_memory_write_and_edit_are_logged_as_writes(env):
    _, mem, log = env
    assert run(env, "Write", mem / "plain.md")
    assert run(env, "Edit", mem / "feedback_rules.md")
    got = lines(log)
    assert [e["kind"] for e in got] == ["write", "write"]
    assert got[0]["title"] == "plain"  # no frontmatter name: the filename


def test_other_paths_and_tools_are_ignored(env, tmp_path):
    home, mem, log = env
    outside = tmp_path / "notes.md"
    outside.write_text("x")
    assert not run(env, "Read", outside)
    assert not run(env, "Read", home / ".claude" / "projects" / "-p" / "notes.md")
    assert not run(env, "Read", mem / "nested" / "deep.md")
    assert not run(env, "Read", mem / "feedback_rules.txt")
    assert not run(env, "Bash", mem / "feedback_rules.md")
    assert not run(env, "Grep", mem / "feedback_rules.md")
    assert not log.exists()


def test_memory_index_is_ignored(env):
    _, mem, log = env
    assert not run(env, "Read", mem / "MEMORY.md")
    assert not log.exists()


def test_path_traversal_does_not_count_as_a_memory(env):
    home, mem, log = env
    sneaky = mem / ".." / ".." / ".." / ".." / "etc" / "passwd.md"
    assert not run(env, "Read", sneaky)
    assert not log.exists()


def test_rotation_keeps_one_old_file(env):
    _, mem, log = env
    log.parent.mkdir(parents=True)
    log.write_text("x" * 100)
    hook.rotate(str(log), max_bytes=50)
    assert not log.exists()
    assert Path(str(log) + ".1").read_text() == "x" * 100
    # Under the limit: untouched. A second rotation replaces the old copy.
    log.write_text("small")
    hook.rotate(str(log), max_bytes=50)
    assert log.read_text() == "small"
    log.write_text("y" * 100)
    hook.rotate(str(log), max_bytes=50)
    assert Path(str(log) + ".1").read_text() == "y" * 100


def test_logging_rotates_when_the_log_is_big(env):
    _, mem, log = env
    log.parent.mkdir(parents=True)
    log.write_bytes(b"z" * (hook.MAX_LOG_BYTES + 1))
    assert run(env, "Read", mem / "plain.md")
    assert len(lines(log)) == 1
    assert Path(str(log) + ".1").exists()


def test_script_is_silent_and_exits_zero_on_bad_input(tmp_path):
    script = Path(hook.__file__)
    env = {**os.environ, "HOME": str(tmp_path)}
    for stdin in [
        "not json",
        "",
        "[]",
        '{"tool_name": 5}',
        '{"tool_name": "Read", "tool_input": "x"}',
    ]:
        r = subprocess.run(
            [sys.executable, str(script)],
            input=stdin,
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert r.returncode == 0
        assert r.stdout == "" and r.stderr == ""
    assert not (tmp_path / ".local").exists()


def test_script_logs_a_real_memory_read_end_to_end(tmp_path):
    mem = tmp_path / ".claude" / "projects" / "-p" / "memory"
    mem.mkdir(parents=True)
    f = mem / "project_x.md"
    f.write_text("---\nname: X project\n---\n")
    payload = {
        "tool_name": "Read",
        "tool_input": {"file_path": str(f)},
        "cwd": "/w",
        "session_id": "s",
    }
    env = {**os.environ, "HOME": str(tmp_path), "HERDR_PANE_ID": "w2:p9"}
    r = subprocess.run(
        [sys.executable, hook.__file__],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )
    assert r.returncode == 0 and r.stdout == ""
    (entry,) = [
        json.loads(x)
        for x in (tmp_path / ".local/share/synthia/brain/recalls.jsonl").read_text().splitlines()
    ]
    assert entry["pane"] == "w2:p9" and entry["title"] == "X project" and entry["kind"] == "read"
