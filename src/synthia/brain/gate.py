"""Permission gate: Synthia security-gate rules plus voice confirmation for risky calls."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Literal

from claude_agent_sdk import CanUseTool, PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext

from synthia.hooks.security_gate import (
    CRITICAL,
    HIGH,
    SEV_RANK,
    _binary_of,
    _split_pipeline_stages,
    _split_statements,
    evaluate,
)

Decision = Literal["allow", "deny", "confirm"]
Confirmer = Callable[[str], Awaitable[bool]]

# A confirmation is read aloud, so a long command becomes an unlistenable voice note.
SPOKEN_COMMAND_LIMIT = 120

# MCP connector actions that only read. Anything else on a connector mutates something
# Mark cares about (send mail, update a page, share a file, dispatch a task), so it needs
# a spoken yes rather than the default-allow the gate gives unmodelled built-in tools.
SAFE_MCP_ACTION_PREFIXES = (
    "get",
    "list",
    "search",
    "fetch",
    "read",
    "query",
    "ping",
    "whats_running",
    "job_",
    "kb_get",
    "kb_list",
    "kb_search",
    "sales_summary",
    "suggest_time",
    "download",
    "notion-search",
    "notion-fetch",
    "notion-list",
    "notion-get",
    "notion-query",
    "notion-ai-search",
    "tavily_",
)

# The brain's own in-process job server; its tools are the brain's own API.
_OWN_MCP_SERVER = "jobs"


def _mcp_parts(tool_name: str) -> tuple[str, str] | None:
    """Split `mcp__<server>__<action>` into (server, action), or None if not an MCP tool."""
    parts = tool_name.split("__")
    if parts[0] != "mcp" or len(parts) < 3:
        return None
    return parts[1], parts[-1]


def _truncate_spoken(text: str, limit: int = SPOKEN_COMMAND_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


def describe(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        cmd = _truncate_spoken(str(tool_input.get("command", "") or ""))
        return f"run {cmd}".strip()
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        verb = "write" if tool_name == "Write" else "edit"
        return f"{verb} {tool_input.get('file_path', '') or ''}".strip()
    parts = _mcp_parts(tool_name)
    if parts is not None:
        server, action = parts
        return f"use {server} {action}"
    return f"use {tool_name}"


def risky_action(cmd: str) -> str | None:
    """Check if a bash command matches any risky action pattern.

    Properly parses statements and pipeline stages, avoiding false positives
    from quoted arguments (e.g. commit messages or echo strings).

    Returns the matched rule name (e.g. "git-push") or None.
    """
    for stmt in _split_statements(cmd):
        # Check each pipeline stage
        for stage in _split_pipeline_stages(stmt):
            binary, args = _binary_of(stage)
            if not binary:
                continue

            # Skip quoting binaries that don't have risky subcommands (e.g. echo).
            # But don't skip git/gh/etc at the top level; check them for risky actions.
            if binary in (
                "echo",
                "printf",
                "jq",
                "awk",
                "sed",
                "python",
                "python3",
                "node",
                "ruby",
                "perl",
            ):
                continue

            # Handle command prefixes like sudo - extract the real command
            if binary in ("sudo", "sudo -u", "su", "su -"):
                if args:
                    # Recursively check the rest of the command
                    real_cmd = " ".join(args)
                    result = risky_action(real_cmd)
                    if result:
                        return result
                continue

            joined_args = " ".join(args)

            # Per-binary rules
            if binary == "git":
                if re.search(r"^push\b", joined_args):
                    return "git-push"
                if re.search(r"^(reset\s+--hard|clean\s+-[a-zA-Z]*f|branch\s+-D)\b", joined_args):
                    return "git-destructive"
            elif binary == "gh":
                if re.search(r"^pr\s+merge\b", joined_args):
                    return "pr-merge"
                if re.search(r"^release\s+(create|delete|upload)\b", joined_args):
                    return "deploy"
            elif binary == "systemctl":
                if re.search(r"\b(restart|stop|disable)\b", joined_args):
                    return "service-restart"
            elif binary == "rm":
                if re.search(r"(^|\s)-[a-zA-Z]*r", joined_args):
                    return "recursive-delete"
            elif binary in ("mongosh", "mongo"):
                if re.search(r"(deleteMany|deleteOne|updateMany|drop\(|dropDatabase)", joined_args):
                    return "db-write"
            elif binary in ("npm", "yarn", "pnpm"):
                if re.search(r"^run\s+deploy\b", joined_args):
                    return "deploy"
            elif "deploy" in binary:
                # e.g. ./deploy.sh, deploy-prod
                return "deploy"
            elif binary == "ssh" and len(args) > 1:
                # Recursively check the remote command
                remote_cmd = " ".join(args[1:]).strip()
                # Strip surrounding quotes if present
                if (remote_cmd.startswith("'") and remote_cmd.endswith("'")) or (
                    remote_cmd.startswith('"') and remote_cmd.endswith('"')
                ):
                    remote_cmd = remote_cmd[1:-1]
                result = risky_action(remote_cmd)
                if result:
                    return result

    return None


def classify(tool_name: str, tool_input: dict[str, Any]) -> tuple[Decision, str]:
    hits = evaluate(tool_name, tool_input)
    if hits:
        top = max(hits, key=lambda h: SEV_RANK.get(h["severity"], 0))
        if top["severity"] == CRITICAL:
            return "deny", f"blocked by rule {top['rule']}"
        if top["severity"] == HIGH:
            return "confirm", f"flagged by rule {top['rule']}"
    if tool_name == "Bash":
        cmd = tool_input.get("command", "") or ""
        action = risky_action(cmd)
        if action:
            return "confirm", f"risky action {action}"
    parts = _mcp_parts(tool_name)
    if parts is not None:
        server, action = parts
        if server != _OWN_MCP_SERVER and not action.startswith(SAFE_MCP_ACTION_PREFIXES):
            return "confirm", f"connector action {action}"
    return "allow", "ok"


def make_can_use_tool(confirm: Confirmer) -> CanUseTool:
    async def can_use_tool(
        tool_name: str, tool_input: dict[str, Any], context: ToolPermissionContext
    ) -> PermissionResultAllow | PermissionResultDeny:
        decision, reason = classify(tool_name, tool_input)
        if decision == "allow":
            return PermissionResultAllow(updated_input=tool_input)
        if decision == "deny":
            return PermissionResultDeny(message=f"Denied: {reason}.")
        if await confirm(describe(tool_name, tool_input)):
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=f"Denied: {reason}, not confirmed by Mark.")

    return can_use_tool
