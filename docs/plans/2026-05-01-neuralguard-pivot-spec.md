---
title: NeuralGuard pivot — local AI agent security monitor in Synthia
date: 2026-05-01
status: draft
owner: Mark Middo
---

# NeuralGuard pivot — design spec

## Pivot narrative

Original NeuralGuard scope (github.com/markmiddo/neuralguard): cloud
platform for automated AI red-team testing — prompt injection, model
extraction, data poisoning. Targets API endpoints; enterprise-facing.

Synthia today: local voice assistant + AI agent monitor. Tracks running
Claude Code / OpenCode / Kimi / Codex agents on the user's machine, reads
their session logs, can kill them.

Pivot framing for the grant:

> NeuralGuard is becoming the **runtime security layer for local AI
> coding agents**. Where the original scope tested AI endpoints from
> outside, we now monitor and constrain AI agents from inside the
> developer's workstation — exactly where the agent has the most power
> (filesystem, shell, secrets, network) and the least supervision.

This reuses every Synthia capability we already shipped and adds three
new components.

## Why this is defensible

1. **Real attack surface.** AI coding agents now run with shell + file
   access. Prompt injection from a fetched URL, MCP tool, or pasted
   issue can pivot into `rm -rf`, `curl | sh`, exfil of `~/.ssh/*`, or
   silent config edits. No mainstream tool monitors this on-host.
2. **Observable.** Synthia already reads the same jsonl session logs
   Claude writes; we know every tool call after the fact and (via
   PreToolUse hooks) before it runs.
3. **Local first.** Lines up with the Synthia identity — runs on the
   developer's box, no SaaS dependency, privacy-preserving.

## MVP scope (Phase 1 — ship for the grant demo)

Three deliverables. All rules-based, no LLM calls, fully local.

### 1. Risk-scored agent feed

Reuses `snapshot_session` in `gui/src-tauri/src/lib.rs`. Adds a rule
engine that scores each `tool_use` event when the jsonl is parsed.

**Rule categories** (start with ~15 rules):

| Category               | Example trigger                              | Default severity |
|------------------------|----------------------------------------------|------------------|
| Destructive shell      | `rm -rf /`, `rm -rf ~`, `dd of=/dev/`        | critical         |
| Pipe-to-shell          | `curl ... \| sh`, `wget ... \| bash`         | critical         |
| Privilege escalation   | `sudo`, `chmod +s`, `setcap`                 | high             |
| Secret read            | reads `~/.ssh/id_*`, `~/.aws/credentials`,   | high             |
|                        | `~/.gnupg/`, `.env`                          |                  |
| Secret exfil           | secret pattern in arg + network call         | critical         |
| Shell-rc tamper        | writes to `~/.bashrc`, `~/.zshrc`, `~/.profile` | high          |
| Git config tamper      | `git config user.email`, remote rewrite      | medium           |
| Untrusted fetch        | `curl`/`wget` to non-allowlisted host        | medium           |
| Base64 + exec pattern  | `base64 -d \| sh` or similar                 | critical         |
| Mass file delete       | `find ... -delete`, `rm -r` on >N files      | high             |
| Process kill spree     | `pkill -f`, `kill -9` on system procs        | medium           |
| MCP-injected text      | "ignore previous instructions" in tool result| high             |

Severity → numeric score. Per-agent shown as max severity in last
N events; per-event detail panel lists every match with the rule name
and the matched substring.

UI:
- Color the agent row dot/border by current risk (green / yellow /
  orange / red).
- Add a fourth status next to active/idle/stale: `flagged`.
- Detail panel grows a "Security events" section: list of rule hits
  with timestamp, rule, snippet, severity.
- Sidebar gets a top-level **Security** tab — global feed across all
  agents, filterable by severity.

Storage: events emitted to `~/.config/synthia/security/events.jsonl`
(append-only, rotated daily). Same data the GUI reads. Survives
restarts; gives us a grant-ready audit trail.

### 2. Policy gate via Claude Code PreToolUse hooks

Synthia ships a hook script that Claude invokes before any tool runs.
Hook reads the proposed tool call, runs it through the rule engine,
consults `~/.config/synthia/security/policy.yaml`, and decides:

- `allow` — return 0, agent proceeds.
- `deny`  — return non-zero with stderr explaining; Claude aborts.
- `prompt` — push a notification to the Synthia GUI, block until user
  clicks Allow / Deny in a modal. Timeout → deny.

Policy file:
```yaml
default: allow
rules:
  - name: block-recursive-rm
    match: command_regex: 'rm\s+-rf?\s+(/|~|\$HOME)'
    action: deny
  - name: confirm-sudo
    match: command_regex: '\bsudo\b'
    action: prompt
  - name: deny-ssh-key-read
    match: file_path_regex: '^~?/\.ssh/id_'
    action: deny
  - name: confirm-env-write
    match: { tool: Write, file_path_regex: '\.env$' }
    action: prompt
allowed_hosts:
  - github.com
  - api.anthropic.com
  - api.openai.com
```

Install: `synthia security install-hooks` writes the hook entry into
`~/.claude/settings.json` (PreToolUse). Idempotent. `synthia security
uninstall-hooks` removes it.

Same hook can sit in front of OpenCode/Kimi/Codex once those CLIs
expose equivalent hooks; for now claude-only.

### 3. Prompt-injection scanner over tool results

Same hook also runs on `PostToolUse` results (e.g. fetched web pages,
issue bodies, MCP tool outputs). Scans for known injection signatures:

- "Ignore previous instructions"
- "You are now ..."
- Hidden Unicode tags / zero-width chars / direction overrides
- Markdown link with `javascript:` href
- Embedded `<system>` / `[SYSTEM]` markers
- Tool result claiming auth tokens / asking to exfil files

On match → emit security event severity `high`, optionally annotate the
tool result with a warning banner (still passes through; we surface
not censor in MVP).

## Phase 2 (post-grant, only if budget for tokens)

- **LLM classifier pass.** Same hook input fed to Haiku for ambiguous
  cases ("is this command suspicious given the conversation goal?").
  Toggle in policy.yaml. Caches results.
- **Sandbox profiles.** Wrap Bash via `firejail`/`bubblewrap` profile
  per project (read-only outside repo, no network unless allowlisted).
- **Egress monitor.** eBPF or `lsof` poll on the agent PID; alert on
  unexpected outbound connections.
- **Cross-machine fleet view.** Optional cloud sync for teams (this is
  where the original NeuralGuard SaaS reappears).

## Architecture

```
+-----------------------+        +---------------------------+
|  Claude Code agent    |  hook  |  synthia-security daemon  |
|  (PreToolUse stdin)   +------->+  - rule engine            |
+-----------------------+        |  - policy.yaml            |
                                 |  - events.jsonl writer    |
                                 +-------------+-------------+
                                               |
                                               | UNIX socket
                                               v
+-----------------------+        +---------------------------+
|  jsonl session log    +------->+  Synthia GUI (Tauri)      |
|  (~/.claude/projects) | scan   |  - Security tab           |
+-----------------------+        |  - Risk badges per agent  |
                                 |  - Approve/deny modal     |
                                 +---------------------------+
```

Two ingest paths because we want both retro-detection (jsonl scan,
catches stuff that already ran) and prevention (hook, blocks before
it runs).

## Data model

`security_event`:
```jsonc
{
  "id": "evt_...",
  "ts": "2026-05-01T07:55:12.314Z",
  "agent_pid": 5184,
  "agent_kind": "claude",
  "agent_cwd": "/home/.../eventflo",
  "session_id": "...",
  "tool": "Bash",
  "rule": "destructive-shell",
  "severity": "critical",
  "matched": "rm -rf ~/dev",
  "raw": { "command": "rm -rf ~/dev" },
  "decision": "denied" | "allowed" | "prompted" | "observed",
  "actor": "rule-engine" | "user" | "policy-default"
}
```

`policy.yaml`: as shown above.

`runtime.json` gains `security_paused: bool` so user can globally pause
enforcement (still logs, doesn't block) for noisy days.

## UX sketch

- **Sidebar:** new "Security" entry between Agents and Knowledge,
  badge count = unresolved high+ events.
- **Security page:** event feed, filter chips (severity, kind, rule),
  click event → expand to full raw input, "open in agent" jumps to the
  source agent row.
- **Approve/deny modal:** triggered by `prompt` action; shows command,
  matched rule, agent + cwd, 30s countdown, two buttons. Audit trail
  of decisions.
- **Per-agent badge:** small shield icon next to the kind badge; green
  / yellow / red.

## Acceptance criteria for Phase 1

1. Hook installed via one CLI command; uninstall reverses cleanly.
2. Running `rm -rf ~/test` from a Claude session blocks before
   execution and surfaces a denial event in the GUI within 1 second.
3. Reading `~/.ssh/id_rsa` blocks; event recorded.
4. `sudo apt update` triggers prompt modal; Allow → command runs and
   event marked `allowed`. Deny → blocked.
5. Fetching a webpage that contains "Ignore previous instructions"
   produces a `high` event, does not block, banner appears in agent
   detail.
6. Security tab lists last 200 events, sortable, persists across GUI
   restarts.
7. Disabling `security_paused` stops blocking but events still log.

## Out of scope (MVP)

- Sandboxed execution
- LLM-based classification
- Multi-host / fleet
- Per-tenant policy
- Anything that talks to a remote service

## Open questions

1. Approve/deny prompt UX — modal in GUI vs system notification? Modal
   wins for grant demo (visible). System notification wins for users
   not staring at the GUI.
2. Default policy — ship strict (block by default) or permissive (log
   only)? Recommend permissive default + opt-in strict mode, so first-
   run doesn't break anyone's workflow.
3. Hook compatibility for OpenCode/Kimi/Codex — research before Phase 1
   ends so we can credibly say "multi-agent" in grant copy.

## Estimate

Rough: 1 week of focused build for Phase 1 across:
- ~2 days: rule engine + events.jsonl writer + Tauri commands
- ~2 days: hook script + policy parser + install/uninstall CLI
- ~2 days: Security tab UI + approve/deny modal + per-agent badge
- ~1 day:  test pass, documentation, demo recording for grant

## Naming

Keep "NeuralGuard" as the brand for this layer inside Synthia. UI
label: "NeuralGuard Security". Marketing/grant copy can call the whole
thing NeuralGuard with Synthia as the host runtime.
