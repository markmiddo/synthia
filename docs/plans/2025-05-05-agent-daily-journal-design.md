# Agent Daily Journal — Design Document

**Date:** 2025-05-05  
**Status:** Approved  
**Related:** Agent monitoring, task tracking

---

## 1. Overview

Agents (Claude Code, OpenCode, Kilo CLI, Codex) maintain a daily journal of completed task lists. Each time an agent finishes all todos in a task list, an entry is written to that day's journal file. The GUI shows the last 7 days of entries inside the existing Agents panel as a second tab.

## 2. Goals

- Track what agents accomplish even when sessions are closed abruptly
- Provide a human-readable history of agent activity
- Keep 7 days of history, auto-pruning older entries
- Support all four agent types equally

## 3. Non-Goals

- Detailed per-tool-call logging (already in session jsonls)
- Cross-device sync
- Export/sharing functionality
- Editable journal entries

## 4. Architecture

```
~/.config/synthia/journal/
├── 2025-05-05.json
├── 2025-05-06.json
├── 2025-05-07.json
└── ... (max 7 files)
```

### Components

| Component | Language | File | Purpose |
|-----------|----------|------|---------|
| Journal storage | Rust | `gui/src-tauri/src/commands/journal.rs` | File I/O, commands |
| Multi-agent capture | Rust | `gui/src-tauri/src/commands/journal.rs` | Detect task completion across all agent types |
| GUI tab | TypeScript | `gui/src/App.tsx` | Journal tab in Agents panel |

## 5. Data Model

Each `YYYY-MM-DD.json` contains:

```json
[
  {
    "timestamp": "2025-05-05T14:23:17Z",
    "agent_name": "Atlas",
    "agent_kind": "claude",
    "agent_role": "Developer",
    "project_name": "synthia",
    "branch": "feature/journal",
    "task_summary": "Implement agent daily journal with JSON storage",
    "files_touched": ["src/journal.rs", "gui/src/App.tsx"],
    "activity": "Writing journal.rs",
    "session_id": "abc123...",
    "trigger": "task_list_completed"
  }
]
```

**Fields:**

| Field | Type | Description |
|-------|------|-------------|
| `timestamp` | ISO 8601 | When task list reached all-completed |
| `agent_name` | string | Friendly name (Atlas, Beckett, etc.) |
| `agent_kind` | string | claude / opencode / kimi / codex |
| `agent_role` | string | Developer, Architect, etc. |
| `project_name` | string | Repo directory name |
| `branch` | string | Git branch |
| `task_summary` | string | Concatenated todo content or first user message |
| `files_touched` | string[] | Up to 10 file paths from session |
| `activity` | string | Last known activity verb |
| `session_id` | string | Session identifier for deep-linking |
| `trigger` | string | "task_list_completed" or "session_exit" |

## 6. Capture Mechanism

### Multi-Agent Detection

| Agent Type | Detection Method |
|------------|-----------------|
| Claude Code | Monitor `~/.claude/todos/{sessionId}-agent-*.json` files |
| OpenCode | Scan `~/.opencode/threads/` for session/task files |
| Kilo CLI | Scan `~/.kimi/` or project-local session files |
| Codex | Monitor project directory session artifacts |

### Capture Flow

1. Poll active agents every 30 seconds (leverage existing `list_active_agents`)
2. For each agent, read current task/todo state
3. Compare against last known state (in-memory cache)
4. If transition: has pending/in_progress → all completed:
   - Write journal entry with `trigger: "task_list_completed"`
   - Include up to 10 most-touched files from session snapshot
5. 5-minute dedupe window prevents double-capture of same list

### Fallback

If an agent lacks structured todos, capture on session exit (PID disappears) with `trigger: "session_exit"` and available summary data.

## 7. UI Design

### Location

Inside the existing **Agents** panel, add a second tab:

```
Active Agents | Journal
```

### Journal Tab Layout

- **Filter bar** (top): "All" | "Claude" | "OpenCode" | "Kilo" | "Codex" | "Today" | "7 days"
- **Date groups**: Entries grouped by day with headers:
  - "Today" / "Yesterday" / "May 3" / etc.
- **Entry cards**:
  ```
  2:23 PM | Atlas 🧑‍💻 | synthia | feature/journal
  ✓ Implement agent daily journal with JSON storage
  → journal.rs, App.tsx
  ```
- **Empty state**: "No journal entries yet. Complete a task list to see it here."
- **Tab badge**: Shows today's entry count (e.g., "Journal (3)")

### Status Bar

Small indicator showing total entries across all visible agents.

## 8. Retention

- Keep exactly 7 days of journal files
- On write: delete files older than 7 days
- On read: ignore files older than 7 days (graceful)

## 9. Error Handling

| Scenario | Behavior |
|----------|----------|
| Missing journal dir | Auto-create on first write |
| Corrupt JSON | Log warning, skip file, continue loading |
| Permission denied | Log error, show "Journal unavailable" in UI |
| Race condition (concurrent writes) | Atomic write-then-rename |
| Agent detection failure | Skip gracefully, don't crash |
| No active agents | Show empty state |

## 10. Testing

### Rust Unit Tests

- JSON serialization round-trip
- Date-based file operations (create, read, prune)
- Multi-agent detection logic (mock process data)
- Dedupe logic (same completion not captured twice)

### Integration Tests

- Simulate Claude todo completion → verify entry written
- Simulate session exit → verify fallback entry
- Verify 7-day retention (old files pruned)
- Verify filter by agent kind works

### GUI Tests

- Tab switching between Active Agents and Journal
- Empty state renders correctly
- Filter pills update displayed entries
- Entry cards show correct data

## 11. Open Questions

- Should we include a "copy to clipboard" or "export" button for individual entries?
- Should journal entries be clickable to open the associated worktree/session?
- Do we want to track estimated time spent (from session duration)?

## 12. Implementation Order

1. Rust journal module with file I/O commands
2. Multi-agent capture logic (extend existing agent detection)
3. GUI Journal tab in Agents panel
4. Retention/cleanup logic
5. Tests
6. Polish (filters, badges, empty states)
