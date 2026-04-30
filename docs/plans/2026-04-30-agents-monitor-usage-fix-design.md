# Agents Monitor + Usage Widget Fix — Design

**Date:** 2026-04-30
**Status:** Approved, awaiting implementation plan
**Scope:** Synthia Tauri GUI (`gui/`)

## Goal

Replace the Tasks/Kanban section with a Claude Code agents monitor, and fix the Claude Usage widget so its numbers match the official OAuth `usage` endpoint (the same source the statusline uses).

## Motivation

- The local Kanban board is no longer used.
- The current Usage widget scans local JSONL files and applies guessed tier multipliers, producing numbers that disagree with the statusline (which reads the official endpoint). The statusline is "always bang on" — make the GUI match it.
- Mark routinely runs multiple Claude Code sessions in parallel and needs a single-pane view of which agents are alive and what they are working on.

## Scope

### Remove

- Tasks/Kanban section in `gui/src/App.tsx`:
  - `Section` enum value `"tasks"`
  - All `tasks` state hooks (`tasks`, `showAddTask`, `editingTask`, `newTaskTitle`, `newTaskDesc`, `newTaskTags`, `newTaskDue`, `draggedTaskId`, `dragOverTaskId`)
  - `Task` interface
  - `loadTasks`, `handleAddTask`, `handleUpdateTask`, `handleMoveTask`, `handleDeleteTask`, drag-drop handlers, `handleReorderTasks`
  - Sidebar nav entry for Tasks
  - Tasks render block and modals
  - Default initial section currently `"tasks"` → switch to `"agents"`
- Rust in `gui/src-tauri/src/lib.rs`:
  - Tauri commands: `list_tasks`, `add_task`, `update_task`, `move_task`, `delete_task`, `reorder_tasks`
  - `Task` struct, `TaskStatus`, `sort_order` field
  - Tasks JSON file path / load / save helpers
  - Registrations in `invoke_handler!`
- On-disk: leave `tasks.json` alone (do not delete user data); just stop reading/writing it.

### Add — Agents section

Sidebar entry "Agents", placed where Tasks used to be.

**Rust command `list_active_agents` returns `Vec<AgentInfo>` where:**

```rust
struct AgentInfo {
    pid: u32,
    cwd: String,
    project_name: String,        // basename of cwd
    branch: Option<String>,      // git branch in cwd, if any
    status: AgentStatus,         // Active | Idle | Stale
    started_at: String,          // ISO
    last_activity: Option<String>, // ISO from JSONL mtime
    last_user_msg: Option<String>, // last 200 chars
    last_action: Option<String>,   // last tool name + brief target
    session_id: Option<String>,
    jsonl_path: Option<String>,
}

enum AgentStatus { Active, Idle, Stale }
```

**Detection algorithm:**

1. Run `ps -eo pid,etime,args` (or read `/proc` directly).
2. Keep rows whose argv contains the `claude` binary path. Exclude:
   - Lines containing `grep`
   - The Synthia GUI process itself
   - Statusline scripts (filenames ending in `.sh`)
3. For each surviving pid:
   - Read `/proc/<pid>/cwd` (symlink) → real path
   - Encode cwd to project dir name using Claude Code's scheme: replace `/` with `-`, drop leading `-` (verify against an existing dir under `~/.claude/projects/`)
   - Locate `~/.claude/projects/<encoded>/` and pick the newest `.jsonl`
   - Read last ~200 lines of that JSONL; extract:
     - Most recent `type: "user"` message text
     - Most recent assistant `tool_use` entry (name + first 60 chars of input target)
     - File mtime → `last_activity`
   - Status: `Active` if mtime within 30s, `Idle` if within 5min, else `Stale`
   - `started_at`: parse `etime` from `ps` against now
   - `branch`: `git -C <cwd> branch --show-current` (best effort)

**Frontend `AgentsSection`:**

- Auto-refresh: `setInterval(loadAgents, 5000)`; clear on unmount or section change
- Row layout (one line each):
  - Status dot (●) — green/amber/grey
  - Project name + branch (if any) in muted color
  - Elapsed time since `started_at`
  - One-line `last_action` (truncate)
- Click row → expanded detail panel inline:
  - Full last user message (preserve newlines)
  - Last 3 tool actions
  - Session id, full cwd, pid
  - Kill button → confirm dialog → `kill_agent(pid)` Tauri command sends SIGTERM
- Empty state: centered "No Claude Code agents running"
- Loading state on first fetch only; subsequent refreshes silent

### Fix — Usage widget

Rewrite `get_usage_stats` to call the OAuth usage API directly.

**New Rust returned shape:**

```rust
struct UsageStats {
    five_hour_pct: f64,
    five_hour_resets_at: String,    // ISO
    five_hour_resets_in: String,    // "Xh Ym" or "Xm"
    seven_day_pct: f64,
    seven_day_resets_at: String,
    seven_day_resets_in: String,
    seven_day_opus_pct: Option<f64>,
    seven_day_opus_resets_at: Option<String>,
    seven_day_opus_resets_in: Option<String>,
    subscription_type: Option<String>,
    error: Option<String>,          // populated on failure
}
```

**Implementation:**

1. Read token from `~/.claude/.credentials.json` → `.claudeAiOauth.accessToken`. If missing, return `error: "No Claude credentials found"`.
2. Cache token 15 min in a `Mutex<Option<(String, Instant)>>`.
3. Cache full response 60 s in a `Mutex<Option<(UsageStats, Instant)>>` to avoid hammering the API on 5 s widget refreshes.
4. HTTP GET `https://api.anthropic.com/oauth/usage` with headers:
   - `authorization: Bearer <token>`
   - `anthropic-beta: oauth-2025-04-20`
   - `accept: application/json`
   - `user-agent: synthia-gui/<version>`
5. Parse `five_hour`, `seven_day`, `seven_day_opus` (latter optional). Each has `utilization` (0–100, may be float) and `resets_at` (ISO string).
6. Compute `resets_in` strings from `resets_at - now`.
7. On non-2xx or network failure: return cached value if <10 min old, else return `error` populated.

**Frontend widget:**

- Title: "Claude Usage" (drop "(est.)")
- Three blocks, each with a bar + label:
  - "5-hour" — `five_hour_pct`% — "Resets in {five_hour_resets_in}"
  - "7-day" — `seven_day_pct`% — "Resets in {seven_day_resets_in}"
  - "7-day Opus" — only render when `seven_day_opus_pct` is Some
- Bar color thresholds match existing `usageBarColor` (green <50, amber <80, red ≥80)
- On `error`: render "Usage unavailable" muted text, no bars
- Subscription badge: render only when `subscription_type` present

## Data flow

```
ps + /proc + JSONL tail  ──▶  list_active_agents  ──▶  AgentsSection (5s poll)
~/.claude/.credentials   ──▶  get_usage_stats     ──▶  UsageWidget    (5s poll, 60s server cache)
                             (token cache 15m)
```

No new dependencies expected: `reqwest` is already pulled in by Tauri's HTTP plugin (verify); use `tokio::process::Command` for `ps`. If `reqwest` isn't already a workspace dep, add it.

## Error handling

| Failure | Behavior |
|---|---|
| `ps` fails / `/proc` unreadable | Return empty agent list; log error |
| Project dir lookup fails | Return agent w/ `last_*` fields as `None` |
| JSONL parse fails on a line | Skip line, continue tailing |
| OAuth token missing | Usage shows "Usage unavailable — sign in to Claude" |
| OAuth API non-2xx | Use cached value if recent, else error |
| Kill agent fails | Toast "Failed to kill agent: <err>" |

## Testing

Out of scope for this design — covered by the implementation plan. Manual verification at minimum: launch 2 Claude Code sessions, confirm both appear; confirm usage numbers match statusline output to within ±1%.

## Out of scope

- Logging/persisting agent history
- Cross-machine agent monitoring
- Replacing the statusline itself
- Migrating existing `tasks.json` data anywhere

## Open questions

None at design time. Implementation may surface details around `ps` argv parsing on this system that the plan should address.
