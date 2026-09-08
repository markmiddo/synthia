# Mobile Voice Brain ("Jarvis") — Design

**Date:** 2026-09-09
**Status:** Approved for planning

## Problem

Mark wants to hold a spoken conversation with Claude from his phone during his morning walk and have it
act: run the morning briefing, plan the day, dispatch builds or Eva Core tasks, and answer free questions
about eventflo. Two things exist today and neither does this:

- The Synthia Telegram bot accepts voice notes, transcribes them, and types the text into a Claude Code
  terminal on the desktop. Text reply only, desktop must be awake, no job tracking.
- Eva Core's Telegram integration dispatches tasks, text only, and runs Kimi via OpenCode with its own
  narrow prompt. It does not "feel smart" because it is not the same brain.

The intelligence Mark gets on the desktop is not a model, it is Claude Code running in `~/dev/eventflo`
with everything that folder pulls in: global and project `CLAUDE.md`, `mark-brain.md`, ~40 skills, the
eventflo memory folder, and the MCP connectors (Gmail, Calendar, Notion, Drive, Eva Core, Tavily). Any
mobile brain must be *that* session, not a new prompt.

## Decisions (locked)

- **Path C:** push-to-talk (Telegram voice notes) first; brain designed so a live, interruptible voice
  transport drops in later without brain changes.
- **Brain lives on middo247**, not the desktop. Always on. Desktop stays the dev environment.
- **Approach 2: warm concierge + workers.** One long-lived Claude Agent SDK session talks; long jobs run as
  headless Claude Code worker subprocesses and report back through an event queue.
- **Brain is Claude Code itself** (same model, same config, same working directory). Eva Core is a tool
  the brain can call, not the brain.
- **Day-one scope:** morning briefing, plan my day, dispatch work and report when done, free chat about
  eventflo.
- **Speech:** Google Cloud STT + TTS (server has no GPU). Piper as offline fallback only.
- **Sync:** Syncthing for the Claude config/memory folders, git pull on a timer for repos.
- **Safety:** no `bypassPermissions`. Allowlist + permission callback + voice confirmation for risky calls.

## Architecture

```
phone ──voice note──> Telegram ──> [telegram adapter] ──text──> [brain] ──> Claude Agent SDK session
                                        ▲                          │            cwd ~/dev/eventflo
                                        │ text stream + events     │
                                        └──────────────────────────┤
                                                                   ├── job tools (MCP, in-process)
                                                                   │      └── [job manager] ── claude -p workers
                                                                   └── permission callback ── security gate
```

Four units, each independently testable:

| Unit | One-line purpose | Depends on |
|------|------------------|------------|
| `brain` | Owns the concierge session. `send(text)` streams reply text, `events()` yields job results, `interrupt()`. | Agent SDK, job manager, permission gate |
| `jobs` | Runs headless Claude Code workers, tracks state, emits completion events. | subprocess, filesystem |
| `speech` | `transcribe(ogg) -> text`, `speak(text) -> ogg`. | Synthia `Transcriber` / `TTS` (Google backends) |
| `transports/telegram` | Voice note in, voice note out, pushes events. | brain, speech, python-telegram-bot |

Transports only ever see the brain's three calls. Live voice later is a second transport, same brain.

Package layout: `src/synthia/brain/` (`concierge.py`, `jobs.py`, `speech.py`, `persona.py`,
`transports/telegram.py`, `cli.py` for the text REPL). Entry point `synthia-brain`.

## Section 1: Brain (concierge)

- One `ClaudeSDKClient` per process, `ClaudeAgentOptions`:
  - `cwd="~/dev/eventflo"` (expanded), `setting_sources=["user", "project", "local"]` so global
    `CLAUDE.md`, eventflo `CLAUDE.md`, hooks, skills, memory, and `.mcp.json` load exactly as in the CLI.
  - `skills="all"`, `include_partial_messages=True`, `mcp_servers={"jobs": <in-process server>}`
    (not strict, so `.mcp.json` connectors still load).
  - `resume=<saved session id>` when present; session id persisted to
    `~/.local/share/synthia/brain/session.json`.
- **Persona appendix** (`persona.py`, passed as `system_prompt` append): replies are spoken aloud; two to
  four sentences; no markdown, lists, code, or paths; numbers as words; for anything expected to take
  longer than about thirty seconds, say one line ("on it, briefing in a few minutes") and dispatch a job
  rather than doing it inline; when a job event arrives, summarise it in one breath.
- **Session rollover:** a new session is started at the first message of each calendar day (local time).
  The previous day's session gets one final turn asking for a five-line handover, which is prepended to
  the new session's first message. Keeps context small and first-token latency low. Long-term memory is
  the synced memory folder, unchanged.
- **Streaming contract:** `send(text)` is an async generator yielding text deltas from `StreamEvent`
  messages, ending when `ResultMessage` arrives. Transports decide how to buffer (Telegram waits for the
  full reply; live voice will speak sentence by sentence).
- **Events:** `events()` is an async generator over an internal queue. The job manager puts
  `JobFinished(name, summary, ok)` on it. The brain injects the event into the session as a user turn
  (`[job event] morning-briefing finished: <summary>`) **only when the session is idle**; while a reply is
  streaming, events wait. The resulting spoken reply is yielded on `events()` for the transport to push.
- **Interrupt:** `interrupt()` calls `client.interrupt()` then drains `receive_response()` before the
  next `send`, per SDK contract.
- **Restart safety:** systemd `Restart=always`. On start: git pull repos, resume session, replay any
  `JobFinished` events persisted but not yet delivered.

**Open question (first spike):** whether the Agent SDK on middo247 can authenticate with Mark's Claude Max
login (as the CLI does) or requires `ANTHROPIC_API_KEY` (pay per token at Fable rates). This is resolved
before any other work; if API key is required, the model default becomes a cost decision Mark makes.

## Section 2: Jobs

- In-process MCP server (`create_sdk_mcp_server`) exposing four tools to the concierge:
  `dispatch_job(name, prompt)`, `job_status(name)`, `list_jobs()`, `cancel_job(name)`.
- **Worker:** `claude -p "<prompt>" --output-format json` subprocess, `cwd` = eventflo root, same settings
  sources, `--permission-mode acceptEdits` plus the same allowlist as the concierge. `morning` is simply
  the prompt `/morning`. Workers that touch git must use a worktree (the `/build` skill already does).
- **State:** one JSON file per job under `~/.local/share/synthia/brain/jobs/<id>.json` with
  `name, prompt, pid, started, finished, ok, summary, log_path`. Stdout/stderr to `<id>.log`.
- **Concurrency:** max two running workers; further dispatches queue. Timeout 30 minutes, then killed and
  reported as failed.
- **Completion:** job manager extracts the worker's final `result` text, truncates to ~600 chars for the
  summary, marks the event `delivered=false`, puts `JobFinished` on the brain queue. Marked delivered once
  the transport has pushed the spoken reply.
- **Rule of thumb in persona:** under ~30 s inline (calendar shuffle, task adds, lookups); over that,
  dispatch. Eva Core dispatch needs no new code: the `eva-core` MCP tools already exist in eventflo's
  config.

## Section 3: Speech

- `speech.py` wraps Synthia's existing `Transcriber` (Google backend) and `TTS` (Google backend).
- STT: phrase hints list in brain config (`eventflo`, `Eva`, `Barry`, `FloSale`, `Vishal`, `Corey`,
  plus a free-form list). Input: Telegram `.ogg` → ffmpeg → 16 kHz mono wav (existing bot code path).
- TTS: one configured Google neural voice (`brain.voice`), output wav → ffmpeg → `.ogg` opus for Telegram
  voice messages. Replies over ~3000 chars are split at sentence boundaries into multiple notes.
- Fallback: if Google is unreachable, Piper for TTS and a spoken "cloud speech is down" text reply;
  STT has no offline fallback on the server (no GPU) — the transport replies with text asking to type.
- Latency budget per turn (push-to-talk): STT ≤2 s, first token 3–5 s, full reply ≤10 s, TTS ≤2 s,
  upload ≤1 s. Target under 20 s end to end.

## Section 4: Telegram transport

- Runs inside the `synthia-brain` process as the first transport. Own bot token (Synthia bot), **not**
  the Eva Core bot. `allowed_users` whitelist; anything else is ignored silently.
- Voice note → `speech.transcribe` → `brain.send` → buffer full reply → `speech.speak` → send voice
  message with the reply text as caption. Text messages take the same path minus STT.
- A "typing"/"recording voice" chat action is sent while the brain works so the phone shows activity.
- Events from `brain.events()` are spoken and pushed as voice notes to the whitelisted chat.
- Commands: `/new` (force session rollover), `/stop` (interrupt), `/jobs` (list with status).
- The existing desktop bot mode (types into terminal) is untouched; this is a separate entry point.

## Section 5: Sync (desktop ↔ middo247)

- **Syncthing**, bidirectional, explicit folders only:
  - `~/.claude/skills`, `~/.claude/agents`, `~/.claude/plugins`, `~/.claude/settings.json`,
    `~/.claude/CLAUDE.md`, `~/.claude/projects/-home-markmiddo-dev-eventflo/memory`.
  - Ignore: `projects/*/` session transcripts, `.credentials.json`, `statsig`, caches, `*.bak*`.
- Same username (`markmiddo`) and same repo path (`~/dev/eventflo`) on both machines, so the memory
  folder name matches. Already true.
- **Repos:** systemd timer `git pull --ff-only` every 15 min for each eventflo repo, plus a pull at brain
  session start. Pull failures are logged, never block the brain.
- **Secrets:** `.mcp.json` API keys, Google credentials, bot token copied once by hand into an env file
  on the server. Never synced.

## Section 6: Safety

- `permission_mode="default"`; `allowed_tools` covers Read/Glob/Grep, Skill, the job tools, and the
  read-side MCP connector tools. Bash and writes fall through to `can_use_tool`.
- `can_use_tool` reuses Synthia's security gate rules (`src/synthia/hooks/security_gate.py`): denied
  patterns deny outright; "risky" patterns (git push, prod DB writes, deletes, deploys) request **voice
  confirmation**: the brain says what it wants to do, the transport waits up to two minutes for a reply
  containing an explicit yes, otherwise deny. Confirmation applies to that one call only.
- Workers inherit the same allowlist and gate (as a PreToolUse hook), run in worktrees, never on the
  concierge's checkout.
- Server has no inbound ports for this; Telegram is outbound long-polling. Bot token and keys live in
  `~/.config/synthia/brain.env` (mode 600), loaded by the systemd unit.
- Logs: one line per turn (transcript, reply length, latency) to journald; never log audio.

## Testing

- **Text REPL** (`synthia-brain repl`): drive the brain from the desktop keyboard before any voice work.
- **Unit tests** (pytest, mocked SDK): job manager state machine and concurrency; event queue idle-gating;
  session rollover date logic; permission callback allow/deny/confirm paths; Telegram adapter against a
  fake brain (voice in → voice out, event push, commands).
- **Speech smoke test:** one recorded note round-trips through STT → TTS.
- **Integration:** manual, on middo247: `/morning` dispatched from a voice note completes and is pushed
  back as a voice note.

## Build order

1. Spike: Agent SDK auth on middo247 (Max login vs API key). Throwaway.
2. Brain + jobs + REPL, tested from desktop.
3. Speech + Telegram transport.
4. Server install: systemd unit, Syncthing folders, git-pull timer, env file.
5. First walk.

## Out of scope (this spec)

- Live/streaming voice transport (phone call via Vonage or LiveKit/Pipecat). Designed for, not built.
- Any change to Eva Core.
- Desktop hotkey/voice paths in Synthia.
