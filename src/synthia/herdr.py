"""Thin wrapper around the herdr CLI.

Synchronous, `subprocess.run` with a timeout, never a shell. Every call parses herdr's JSON
and raises `HerdrError` carrying herdr's own message on failure. The installed `herdr`
binary is the authority on syntax; see `herdr agent`, `herdr pane`, `herdr workspace`.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

HERDR_BIN = "herdr"
DEFAULT_TIMEOUT_S = 30.0
START_TIMEOUT_S = 60.0
MAX_COLUMNS = 3
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


class HerdrError(RuntimeError):
    """herdr failed, timed out, or is not installed."""


def valid_name(name: str) -> bool:
    return bool(NAME_RE.match(name))


def _error_message(payload: Any, stderr: str, stdout: str) -> str:
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            msg = err.get("message") or err.get("code")
            if msg:
                return str(msg)
        elif err:
            return str(err)
    return (stderr or stdout).strip() or "herdr failed"


def run(args: list[str], timeout: float = DEFAULT_TIMEOUT_S) -> dict[str, Any]:
    """Run `herdr <args>` and return the `result` object of its JSON reply."""
    cmd = [HERDR_BIN, *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError as exc:
        raise HerdrError("herdr is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} timed out after {timeout:.0f}s") from exc
    payload: Any = None
    try:
        payload = json.loads(proc.stdout) if proc.stdout.strip() else None
    except json.JSONDecodeError:
        payload = None
    failed = proc.returncode != 0 or (isinstance(payload, dict) and payload.get("error"))
    if failed:
        raise HerdrError(_error_message(payload, proc.stderr, proc.stdout))
    if isinstance(payload, dict):
        result = payload.get("result")
        return result if isinstance(result, dict) else payload
    return {}


def _pane_id(value: Any) -> str:
    """A pane reference is either an id string or an object holding `pane_id`."""
    if isinstance(value, dict):
        value = value.get("pane_id")
    if not isinstance(value, str) or not value:
        raise HerdrError("herdr did not return a pane id")
    return value


def _text_of(result: dict[str, Any]) -> str:
    for key in ("text", "output", "content"):
        if isinstance(result.get(key), str):
            return str(result[key])
    for value in result.values():
        if isinstance(value, dict):
            inner = _text_of(value)
            if inner:
                return inner
    return ""


# ---- agents ----


def agent_list() -> list[dict[str, Any]]:
    agents = run(["agent", "list"]).get("agents", [])
    return [a for a in agents if isinstance(a, dict)] if isinstance(agents, list) else []


def agent_name(agent: dict[str, Any]) -> str | None:
    name = agent.get("name") or agent.get("agent_name")
    return str(name) if name else None


def agent_read(target: str, lines: int = 80) -> str:
    result = run(
        ["agent", "read", target, "--source", "recent-unwrapped", "--lines", str(max(1, lines))]
    )
    return _text_of(result) or json.dumps(result)


def agent_wait(target: str, timeout_ms: int = 120000) -> dict[str, Any]:
    return run(
        ["agent", "wait", target, "--timeout", str(timeout_ms)], timeout=timeout_ms / 1000 + 15
    )


def agent_prompt(
    target: str, text: str, wait: bool = False, timeout_ms: int | None = None
) -> dict[str, Any]:
    args = ["agent", "prompt", target, text]
    timeout = DEFAULT_TIMEOUT_S
    if wait:
        args.append("--wait")
    if timeout_ms is not None:
        args += ["--timeout", str(timeout_ms)]
        timeout = max(timeout, timeout_ms / 1000 + 15)
    return run(args, timeout=timeout)


def start_claude(
    name: str, pane_id: str, model: str | None = None, agent: str | None = None
) -> dict[str, Any]:
    """Start Claude Code in a free shell pane under `name` (bypassPermissions, headless desk)."""
    if not valid_name(name):
        raise HerdrError(f"invalid agent name {name!r}; use [a-z][a-z0-9_-]{{0,31}}")
    args = ["agent", "start", name, "--kind", "claude", "--pane", pane_id, "--"]
    if model:
        args += ["--model", model]
    if agent:
        args += ["--agent", agent]
    args += ["--permission-mode", "bypassPermissions"]
    return run(args, timeout=START_TIMEOUT_S)


# ---- panes and workspaces ----


def pane_ids() -> set[str]:
    panes = run(["pane", "list"]).get("panes", [])
    return {p["pane_id"] for p in panes if isinstance(p, dict) and "pane_id" in p}


def close_pane(pane_id: str) -> None:
    run(["pane", "close", pane_id])


def rename(pane_id: str, title: str) -> None:
    run(["pane", "report-metadata", pane_id, "--source", "synthia", "--title", title])


def ensure_workspace(label: str, cwd: str | None = None) -> str:
    """Find the workspace labelled `label`, else create it; return a pane to build on.

    For an existing workspace that is a pane with no agent in it if there is one,
    otherwise its last pane. For a new workspace it is the empty root pane.
    """
    for ws in run(["workspace", "list"]).get("workspaces", []):
        if isinstance(ws, dict) and ws.get("label") == label:
            return _workspace_anchor(str(ws["workspace_id"]))
    args = ["workspace", "create", "--label", label, "--no-focus"]
    if cwd:
        args += ["--cwd", cwd]
    return _pane_id(run(args).get("root_pane"))


def _workspace_anchor(workspace_id: str) -> str:
    panes = [
        p
        for p in run(["pane", "list", "--workspace", workspace_id]).get("panes", [])
        if isinstance(p, dict) and p.get("pane_id")
    ]
    if not panes:
        raise HerdrError(f"workspace {workspace_id} has no panes")
    for p in panes:
        if not p.get("agent"):
            return str(p["pane_id"])
    return str(panes[-1]["pane_id"])


def pick_direction(pane_id: str) -> str:
    """`right` while the tab has fewer than three columns, else `down`."""
    layout = run(["pane", "layout", "--pane", pane_id]).get("layout", {})
    panes = layout.get("panes", []) if isinstance(layout, dict) else []
    columns = {
        p["rect"]["x"] for p in panes if isinstance(p, dict) and isinstance(p.get("rect"), dict)
    }
    return "right" if len(columns) < MAX_COLUMNS else "down"


def split(pane_id: str, direction: str, cwd: str) -> str:
    """Split `pane_id`, keeping the user's focus where it is; return the new pane id."""
    if direction not in ("right", "down"):
        raise HerdrError(f"bad split direction {direction!r}")
    result = run(
        ["pane", "split", "--pane", pane_id, "--direction", direction, "--cwd", cwd, "--no-focus"],
    )
    return _pane_id(result.get("pane"))
