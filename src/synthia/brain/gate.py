"""Permission gate: Synthia security-gate rules plus voice confirmation for risky calls."""

from __future__ import annotations

import re
from typing import Any, Awaitable, Callable, Literal

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny
from claude_agent_sdk.types import ToolPermissionContext

from synthia.hooks.security_gate import CRITICAL, HIGH, SEV_RANK, evaluate

Decision = Literal["allow", "deny", "confirm"]
Confirmer = Callable[[str], Awaitable[bool]]

# Actions that are legitimate but must be confirmed by voice first.
RISKY_BASH = [
    ("git-push", re.compile(r"\bgit\s+push\b")),
    ("pr-merge", re.compile(r"\bgh\s+pr\s+merge\b")),
    ("service-restart", re.compile(r"\bsystemctl\s+(restart|stop|disable)\b")),
    ("deploy", re.compile(r"\b(deploy|release)\b", re.IGNORECASE)),
    ("db-write", re.compile(r"\b(deleteMany|deleteOne|updateMany|drop\(|dropDatabase)\b")),
    ("git-destructive", re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-f|branch\s+-D)\b")),
    ("recursive-delete", re.compile(r"\brm\s+-[a-zA-Z]*r")),
]


def describe(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "Bash":
        return f"run {tool_input.get('command', '')}".strip()
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        verb = "write" if tool_name == "Write" else "edit"
        return f"{verb} {tool_input.get('file_path', '')}".strip()
    return f"use {tool_name}"


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
        for name, pat in RISKY_BASH:
            if pat.search(cmd):
                return "confirm", f"risky action {name}"
    return "allow", "ok"


def make_can_use_tool(confirm: Confirmer) -> Callable[..., Awaitable[Any]]:
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
