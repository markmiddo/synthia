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


# Bash rules are scoped to a specific binary so they only fire when that
# program is actually being invoked at a shell-segment boundary, not when
# the same string appears inside an `echo`/`gh`/`git commit` quoted arg.
#
# (rule, severity, binaries, arg_pattern)
#   - binaries: list of basenames; "*" matches any.
#   - arg_pattern: regex tested against the joined args (or whole segment
#     when binaries == "*").
BASH_RULES = [
    (
        "destructive-rm",
        CRITICAL,
        ["rm"],
        _re(r"-[rR]f?\b.*(?:^|\s)(/|~|\$home|--no-preserve-root)"),
    ),
    ("dd-block-device", CRITICAL, ["dd"], _re(r"of=/dev/(sd|nvme|hd)")),
    ("setuid-bit", HIGH, ["chmod"], _re(r"\+s\b")),
    ("setcap", HIGH, ["setcap"], None),
    (
        "ssh-key-access",
        HIGH,
        ["cat", "less", "more", "head", "tail", "cp", "mv", "rm"],
        _re(r"~?/?\.ssh/(id_|authorized_keys|known_hosts)"),
    ),
    (
        "gpg-access",
        HIGH,
        ["cat", "less", "more", "head", "tail", "cp", "mv", "rm", "tar", "zip"],
        _re(r"~?/?\.gnupg/"),
    ),
    (
        "aws-credentials",
        HIGH,
        ["cat", "less", "more", "head", "tail", "cp", "mv"],
        _re(r"~?/?\.aws/credentials"),
    ),
    (
        "secret-exfil",
        CRITICAL,
        ["curl", "wget", "scp", "rsync"],
        _re(r"(\.ssh|\.aws|\.gnupg|credentials|secret|token|api[_-]?key)"),
    ),
    ("mass-kill", MEDIUM, ["pkill", "killall"], _re(r"-9\b")),
    (
        "git-remote-rewrite",
        MEDIUM,
        ["git"],
        _re(r"\bremote\s+(set-url|add)\s+\S+\s+(https?:|git@)"),
    ),
    ("history-tamper", MEDIUM, ["history"], _re(r"-c\b")),
]


# Whole-segment rules — match across the segment string, not bound to one
# binary. Used for shell features (pipes, redirections) that don't have a
# single binary owner.
SEGMENT_RULES = [
    (
        "pipe-to-shell",
        CRITICAL,
        _re(r"(?:^|[\s;&|])(curl|wget|fetch)\b[^|]*\|\s*(sh|bash|zsh|fish)\b"),
    ),
    ("base64-exec", CRITICAL, _re(r"\bbase64\s+(-d|--decode)\b[^|]*\|\s*(sh|bash|python|node)\b")),
    ("shell-rc-tamper", HIGH, _re(r">>?\s*~?/?\.(bashrc|zshrc|profile|bash_profile|zprofile)\b")),
    ("history-redir-tamper", MEDIUM, _re(r">\s*~?/?\.(bash_history|zsh_history)\b")),
    ("sudo", HIGH, _re(r"(?:^|[\s;&|])sudo\b")),
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


STATEMENT_SPLIT = re.compile(r"\s*(?:;|&&|\|\|)\s*")
PIPE_SPLIT = re.compile(r"\s*\|(?!\|)\s*")
ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _split_statements(cmd: str) -> list[str]:
    return [s.strip() for s in STATEMENT_SPLIT.split(cmd) if s.strip()]


def _split_pipeline_stages(stmt: str) -> list[str]:
    return [s.strip() for s in PIPE_SPLIT.split(stmt) if s.strip()]


def _binary_of(segment: str) -> tuple[str | None, list[str]]:
    """Return (basename, argv) for a shell segment.

    Skips leading VAR=val env assignments. Falls back to whitespace split
    if shlex chokes (e.g. unbalanced quote in an arg).
    """
    import shlex

    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        tokens = segment.split()
    while tokens and ENV_ASSIGN.match(tokens[0]):
        tokens = tokens[1:]
    if not tokens:
        return None, []
    bin_name = tokens[0]
    # strip path
    if "/" in bin_name:
        bin_name = bin_name.rsplit("/", 1)[-1]
    return bin_name, tokens[1:]


QUOTING_BINARIES = {
    "echo",
    "printf",
    "gh",
    "git",
    "jq",
    "awk",
    "sed",
    "python",
    "python3",
    "node",
    "ruby",
    "perl",
}


def _evaluate_bash(cmd: str) -> list[dict]:
    hits: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def emit(rule: str, sev: str, matched: str) -> None:
        key = (rule, matched)
        if key in seen:
            return
        seen.add(key)
        hits.append({"rule": rule, "severity": sev, "matched": matched})

    for stmt in _split_statements(cmd):
        # Statement-level rules see the full pipeline (curl ... | sh) and
        # any redirections.
        for name, sev, pat in SEGMENT_RULES:
            m = pat.search(stmt)
            if m:
                emit(name, sev, m.group(0))

        # If the statement starts with a quoting/reporting binary (echo, gh,
        # git commit, etc.), its quoted args are not real commands — skip
        # binary-bound rules entirely for the whole statement.
        head_bin, _ = _binary_of(stmt)
        if head_bin in QUOTING_BINARIES:
            continue

        # Otherwise iterate pipeline stages — only the binary-bound rules
        # for the actual program in each stage fire.
        for stage in _split_pipeline_stages(stmt):
            binary, args = _binary_of(stage)
            if not binary:
                continue
            if binary in QUOTING_BINARIES:
                continue
            joined = " ".join(args)
            for name, sev, bins, pat in BASH_RULES:
                if bins != "*" and binary not in bins:
                    continue
                if pat is None:
                    matched = binary
                else:
                    m = pat.search(joined)
                    if not m:
                        continue
                    matched = m.group(0)
                emit(name, sev, matched)

    return hits


def evaluate(tool: str, tool_input: dict) -> list[dict]:
    hits: list[dict] = []
    if tool == "Bash":
        cmd = tool_input.get("command", "") or ""
        hits.extend(_evaluate_bash(cmd))
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


# ---- LLM classifier (optional second-pass intent check) ----

LLM_CACHE_PATH = SECURITY_DIR / "llm_cache.json"
LLM_CACHE_TTL_S = 3600
LLM_DEFAULT_MODEL = "claude-haiku-4-5-20251001"
LLM_TIMEOUT_S = 6


def _llm_cache_load() -> dict:
    try:
        data = json.loads(LLM_CACHE_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _llm_cache_save(data: dict) -> None:
    SECURITY_DIR.mkdir(parents=True, exist_ok=True)
    LLM_CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")


def _llm_cache_key(tool: str, tool_input: dict) -> str:
    import hashlib

    blob = json.dumps({"tool": tool, "input": tool_input}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _read_oauth_token() -> str | None:
    try:
        creds = json.loads(
            (Path.home() / ".claude" / ".credentials.json").read_text(encoding="utf-8")
        )
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    return (creds.get("claudeAiOauth") or {}).get("accessToken")


def llm_classify(
    tool: str, tool_input: dict, hits: list[dict], cfg: dict
) -> tuple[str, str] | None:
    """Second-pass LLM intent check.

    Returns (severity, reason) or None when classification is unavailable
    or skipped (no creds, library missing, cached miss, etc).
    """
    if not cfg.get("enabled"):
        return None
    threshold = cfg.get("threshold", "medium")
    threshold_rank = SEV_RANK.get(threshold, SEV_RANK[MEDIUM])
    max_rank = max((SEV_RANK.get(h["severity"], 0) for h in hits), default=0)
    if max_rank < threshold_rank:
        return None

    cache = _llm_cache_load()
    key = _llm_cache_key(tool, tool_input)
    now = time.time()
    cached = cache.get(key)
    if cached and now - cached.get("ts", 0) < LLM_CACHE_TTL_S:
        return cached.get("severity"), cached.get("reason", "")

    api_key = os.environ.get("ANTHROPIC_API_KEY") or _read_oauth_token()
    if not api_key:
        return None

    try:
        import anthropic  # type: ignore
    except Exception:
        return None

    model = cfg.get("model", LLM_DEFAULT_MODEL)
    rule_summary = ", ".join(f"{h['rule']}({h['severity']})" for h in hits)
    user_block = json.dumps({"tool": tool, "input": tool_input}, indent=2)[:2000]

    prompt = (
        "You are a security analyst auditing a tool call about to be run "
        "by a developer's local AI coding agent. Local rules already "
        f"flagged this call (rule hits: {rule_summary}). Decide if this "
        "is genuinely malicious / dangerous given the visible intent, or "
        "a benign developer action that the static rules over-flagged. "
        "Reply with strict JSON only: "
        '{"severity":"info|low|medium|high|critical","reason":"<one short sentence>"}'
    )

    try:
        kwargs: dict = {"timeout": LLM_TIMEOUT_S}
        if api_key.startswith("sk-ant-oat"):
            # OAuth token from Claude Code
            client = anthropic.Anthropic(auth_token=api_key, **kwargs)
        else:
            client = anthropic.Anthropic(api_key=api_key, **kwargs)
        msg = client.messages.create(
            model=model,
            max_tokens=200,
            system=prompt,
            messages=[{"role": "user", "content": f"Tool call:\n{user_block}"}],
        )
    except Exception:
        return None

    text = "".join(
        getattr(b, "text", "") for b in msg.content if getattr(b, "type", "") == "text"
    ).strip()
    sev = MEDIUM
    reason = ""
    try:
        # Tolerate fenced code or stray prose
        m = re.search(r"\{[^{}]*\"severity\"[^{}]*\}", text, re.DOTALL)
        data = json.loads(m.group(0) if m else text)
        sev = (data.get("severity") or MEDIUM).lower()
        if sev not in SEV_RANK:
            sev = MEDIUM
        reason = (data.get("reason") or "").strip()
    except Exception:
        return None

    cache[key] = {"ts": now, "severity": sev, "reason": reason}
    _llm_cache_save(cache)
    return sev, reason


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

    # Optional second-pass: ask Claude Haiku whether the static-rule
    # flags really look malicious. Result can DOWNGRADE (treat as info,
    # let the call through) or UPGRADE (force a deny on a high hit).
    llm_cfg = policy.get("llm_classifier") or {}
    llm_result = llm_classify(tool, tool_input, hits, llm_cfg) if not paused else None
    llm_severity, llm_reason = llm_result if llm_result else (None, None)

    max_rank = max(SEV_RANK.get(h["severity"], 0) for h in hits)
    if llm_severity is not None:
        llm_rank = SEV_RANK.get(llm_severity, max_rank)
        # Always defer to LLM verdict when it is available (it has more
        # context than the regex). Annotate every hit with the new
        # severity so the event log reflects the verdict.
        max_rank = llm_rank
        for h in hits:
            h["severity"] = llm_severity
            h["matched"] = (h.get("matched", "") + f"  [llm: {llm_reason}]").strip()
    severity_max = next(name for name, r in SEV_RANK.items() if r == max_rank)
    should_block = severity_max in block_on or (mode == "strict" and max_rank >= SEV_RANK[MEDIUM])
    should_prompt = mode == "prompt" or (severity_max == HIGH and "high" not in block_on)

    actor = "llm-classifier" if llm_severity is not None else "rule-engine"

    if paused:
        for h in hits:
            append_event(make_event(h, tool, tool_input, "observed", "rule-engine", ctx))
        return 0

    if should_block:
        for h in hits:
            append_event(make_event(h, tool, tool_input, "denied", actor, ctx))
        suffix = f" — {llm_reason}" if llm_reason else ""
        sys.stderr.write(
            f"NeuralGuard blocked {tool} call. Rule(s): "
            + ", ".join(h["rule"] for h in hits)
            + suffix
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
