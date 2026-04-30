#!/usr/bin/env python3
"""
NeuralGuard PreToolUse / PostToolUse security gate.

Reads Claude Code hook JSON from stdin, evaluates the proposed (or just-run)
tool call against builtin rules + ~/.config/synthia/security/policy.yaml,
records an event, and decides allow / deny / prompt.

PreToolUse exit codes:
  0  -> allow
  2  -> deny (Claude shows stderr to the model)

For 'prompt' decisions, this writes a pending request to
~/.config/synthia/security/pending-prompts/<id>.json and polls for the
matching response file; on timeout the action defaults to deny.

Drop-in: register in ~/.claude/settings.json under PreToolUse and PostToolUse.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

SECURITY_DIR = Path(os.environ.get("HOME", "/tmp")) / ".config" / "synthia" / "security"
EVENTS_PATH = SECURITY_DIR / "events.jsonl"
POLICY_PATH = SECURITY_DIR / "policy.yaml"
RUNTIME_PATH = Path(os.environ.get("HOME", "/tmp")) / ".config" / "synthia" / "runtime.json"
PROMPTS_DIR = SECURITY_DIR / "pending-prompts"
RESPONSES_DIR = SECURITY_DIR / "prompt-responses"

PROMPT_TIMEOUT_S = 30


# ---- rule engine (mirror of Rust security.rs; keep in sync) ----

CRITICAL = "critical"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"
INFO = "info"

SEV_RANK = {INFO: 0, LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4}


def _re(pattern: str):
    return re.compile(pattern, re.IGNORECASE)


BASH_RULES = [
    ("destructive-rm", CRITICAL, _re(r"rm\s+-rf?\s+(/|~|\$home|--no-preserve-root)")),
    ("dd-block-device", CRITICAL, _re(r"\bdd\b.+of=/dev/(sd|nvme|hd)")),
    ("pipe-to-shell", CRITICAL, _re(r"(curl|wget|fetch)[^|]*\|\s*(sh|bash|zsh|fish)\b")),
    ("base64-exec", CRITICAL, _re(r"base64\s+(-d|--decode)[^|]*\|\s*(sh|bash|python|node)")),
    ("sudo", HIGH, _re(r"\bsudo\b")),
    ("setuid-bit", HIGH, _re(r"chmod\s+\+s\b")),
    ("setcap", HIGH, _re(r"\bsetcap\b")),
    ("shell-rc-tamper", HIGH, _re(r">+\s*~?/?\.(bashrc|zshrc|profile|bash_profile|zprofile)\b")),
    ("ssh-key-access", HIGH, _re(r"~?/?\.ssh/(id_|authorized_keys|known_hosts)")),
    ("gpg-access", HIGH, _re(r"~?/?\.gnupg/")),
    ("aws-credentials", HIGH, _re(r"~?/?\.aws/credentials")),
    (
        "secret-exfil",
        CRITICAL,
        _re(r"(curl|wget|scp|rsync)[^|;&\n]*(\.ssh|\.aws|\.gnupg|credentials|secret|token)"),
    ),
    ("mass-kill", MEDIUM, _re(r"\bpkill\s+-9\b|\bkillall\s+-9\b")),
    ("git-remote-rewrite", MEDIUM, _re(r"git\s+remote\s+(set-url|add)\s+\S+\s+(http|git@)")),
    ("history-tamper", MEDIUM, _re(r"history\s+-c|>\s*~?/?\.(bash_history|zsh_history)")),
]

WRITE_RULES = [
    ("ssh-key-write", CRITICAL, _re(r"\.ssh/(id_|authorized_keys)")),
    ("shell-rc-write", HIGH, _re(r"\.(bashrc|zshrc|profile|bash_profile|zprofile)$")),
    ("env-file-write", MEDIUM, _re(r"\.env(\.|$)")),
    ("system-config-write", HIGH, _re(r"^/etc/")),
]

READ_RULES = [
    ("ssh-key-read", HIGH, _re(r"\.ssh/(id_|authorized_keys)")),
    ("credentials-read", HIGH, _re(r"\.aws/credentials|\.gnupg/")),
]

FETCH_RULES = [
    ("fetch-ip-literal", MEDIUM, _re(r"^https?://\d+\.\d+\.\d+\.\d+")),
    ("fetch-onion", HIGH, _re(r"\.onion/")),
]

INJECTION_RULES = [
    ("injection-ignore-previous", HIGH, _re(r"ignore\s+(all\s+)?previous\s+instructions")),
    (
        "injection-roleplay",
        HIGH,
        _re(r"you\s+are\s+now\s+(a\s+)?[a-z\s]{0,30}(jailbreak|developer\s*mode|dan)"),
    ),
    ("injection-system-marker", MEDIUM, _re(r"\[SYSTEM\]|<system>|###\s*system\s*###")),
]


def evaluate(tool: str, tool_input: dict) -> list[dict]:
    hits: list[dict] = []
    if tool == "Bash":
        cmd = tool_input.get("command", "") or ""
        for name, sev, pat in BASH_RULES:
            m = pat.search(cmd)
            if m:
                hits.append({"rule": name, "severity": sev, "matched": m.group(0)})
    elif tool in ("Write", "Edit", "NotebookEdit"):
        path = tool_input.get("file_path", "") or ""
        for name, sev, pat in WRITE_RULES:
            m = pat.search(path)
            if m:
                hits.append({"rule": name, "severity": sev, "matched": path})
    elif tool == "Read":
        path = tool_input.get("file_path", "") or ""
        for name, sev, pat in READ_RULES:
            m = pat.search(path)
            if m:
                hits.append({"rule": name, "severity": sev, "matched": path})
    elif tool == "WebFetch":
        url = tool_input.get("url", "") or ""
        for name, sev, pat in FETCH_RULES:
            m = pat.search(url)
            if m:
                hits.append({"rule": name, "severity": sev, "matched": url})
    return hits


def evaluate_injection(text: str) -> list[dict]:
    hits: list[dict] = []
    if not text:
        return hits
    for name, sev, pat in INJECTION_RULES:
        m = pat.search(text)
        if m:
            hits.append({"rule": name, "severity": sev, "matched": m.group(0)})
    # zero-width / unicode tag chars
    if any(0x200B <= ord(c) <= 0x200F or 0xE0000 <= ord(c) <= 0xE007F for c in text):
        hits.append(
            {"rule": "injection-hidden-unicode", "severity": HIGH, "matched": "zero-width chars"}
        )
    return hits


# ---- policy ----


def load_policy() -> dict:
    """Load policy.yaml; falls back to permissive defaults.

    Tries PyYAML if available, otherwise minimal manual parse for the
    `default:`, `mode:` and `block_on:` top-level keys.
    """
    if not POLICY_PATH.exists():
        return {"default": "allow", "mode": "permissive", "block_on": ["critical"]}
    text = POLICY_PATH.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        return data
    except Exception:
        out: dict = {}
        for line in text.splitlines():
            if ":" not in line or line.strip().startswith("#"):
                continue
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip("\"'")
        return out


def is_paused() -> bool:
    try:
        with open(RUNTIME_PATH, encoding="utf-8") as f:
            return bool(json.load(f).get("security_paused", False))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


# ---- event recording ----


def append_event(event: dict) -> None:
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    with EVENTS_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


def make_event(hit: dict, tool: str, raw: dict, decision: str, actor: str, ctx: dict) -> dict:
    return {
        "id": f"evt_{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "agent_pid": os.getppid(),
        "agent_kind": "claude",
        "agent_cwd": ctx.get("cwd"),
        "session_id": ctx.get("session_id"),
        "tool": tool,
        "rule": hit["rule"],
        "severity": hit["severity"],
        "matched": hit["matched"],
        "raw": raw,
        "decision": decision,
        "actor": actor,
    }


# ---- prompt-and-wait flow ----


def request_user_decision(events: list[dict], tool: str, raw: dict) -> str:
    """Write a pending prompt and wait for the GUI to drop a response file.

    Returns 'allow' or 'deny'. Defaults to deny on timeout.
    """
    PROMPTS_DIR.mkdir(parents=True, exist_ok=True)
    RESPONSES_DIR.mkdir(parents=True, exist_ok=True)
    req_id = uuid.uuid4().hex
    payload = {
        "id": req_id,
        "ts": datetime.now(timezone.utc).isoformat(),
        "tool": tool,
        "raw": raw,
        "events": events,
        "agent_pid": os.getppid(),
        "timeout_s": PROMPT_TIMEOUT_S,
    }
    (PROMPTS_DIR / f"{req_id}.json").write_text(json.dumps(payload), encoding="utf-8")

    response_file = RESPONSES_DIR / f"{req_id}.json"
    deadline = time.monotonic() + PROMPT_TIMEOUT_S
    while time.monotonic() < deadline:
        if response_file.exists():
            try:
                resp = json.loads(response_file.read_text(encoding="utf-8"))
                response_file.unlink(missing_ok=True)
                (PROMPTS_DIR / f"{req_id}.json").unlink(missing_ok=True)
                return "allow" if resp.get("decision") == "allow" else "deny"
            except Exception:
                break
        time.sleep(0.25)
    # timeout: clean up request and deny
    (PROMPTS_DIR / f"{req_id}.json").unlink(missing_ok=True)
    return "deny"


# ---- entrypoint ----


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0  # don't block claude on parse errors

    hook_event = payload.get("hook_event_name") or payload.get("event") or "PreToolUse"
    tool = payload.get("tool_name") or payload.get("tool", "")
    tool_input = payload.get("tool_input", {}) or {}
    tool_output = payload.get("tool_response") or payload.get("tool_output", "")
    ctx = {
        "cwd": payload.get("cwd"),
        "session_id": payload.get("session_id"),
    }

    if hook_event == "PostToolUse":
        text = tool_output if isinstance(tool_output, str) else json.dumps(tool_output)
        hits = evaluate_injection(text)
        for h in hits:
            append_event(
                make_event(h, tool, {"output_excerpt": text[:500]}, "observed", "rule-engine", ctx)
            )
        return 0

    # PreToolUse path
    hits = evaluate(tool, tool_input)
    if not hits:
        return 0

    policy = load_policy()
    block_on = policy.get("block_on", ["critical"])
    if isinstance(block_on, str):
        block_on = [block_on]
    mode = policy.get("mode", "permissive")
    paused = is_paused()

    max_rank = max(SEV_RANK.get(h["severity"], 0) for h in hits)
    severity_max = next(name for name, r in SEV_RANK.items() if r == max_rank)
    should_block = severity_max in block_on or (mode == "strict" and max_rank >= SEV_RANK[MEDIUM])
    should_prompt = mode == "prompt" or (severity_max == HIGH and "high" not in block_on)

    if paused:
        for h in hits:
            append_event(make_event(h, tool, tool_input, "observed", "rule-engine", ctx))
        return 0

    if should_block:
        for h in hits:
            append_event(make_event(h, tool, tool_input, "denied", "policy-default", ctx))
        sys.stderr.write(
            f"NeuralGuard blocked {tool} call. Rule(s): "
            + ", ".join(h["rule"] for h in hits)
            + ". Edit ~/.config/synthia/security/policy.yaml to adjust.\n"
        )
        return 2

    if should_prompt:
        decision = request_user_decision(hits, tool, tool_input)
        for h in hits:
            append_event(
                make_event(
                    h, tool, tool_input, "allowed" if decision == "allow" else "denied", "user", ctx
                )
            )
        if decision == "deny":
            sys.stderr.write("NeuralGuard: user denied this tool call.\n")
            return 2
        return 0

    # observe-only path
    for h in hits:
        append_event(make_event(h, tool, tool_input, "observed", "rule-engine", ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main())
