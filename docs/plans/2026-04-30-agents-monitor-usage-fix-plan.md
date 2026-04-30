# Agents Monitor + Usage Widget Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the unused Tasks/Kanban section in the Synthia GUI with a Claude Code agents monitor, and fix the Claude Usage widget to use the official OAuth `usage` endpoint instead of guessed local-JSONL estimates.

**Architecture:** Tauri Rust backend (`gui/src-tauri/src/lib.rs`) exposes two new commands (`list_active_agents`, `kill_agent`) and one rewritten command (`get_usage_stats`). React frontend (`gui/src/App.tsx`) drops Tasks state/handlers/render and adds an `AgentsSection`. Process discovery via `/proc` + `ps`, current-session context via newest JSONL under `~/.claude/projects/<encoded-cwd>/`. Usage stats hit `https://api.anthropic.com/oauth/usage` directly with token from `~/.claude/.credentials.json` (15-min token cache, 60-s response cache).

**Tech Stack:** Rust (Tauri 2), React 19 + TypeScript (Vite). New crates: `reqwest` (blocking, rustls). Existing: `tokio`, `serde`, `chrono`, `dirs`, `regex`.

**Spec:** `docs/plans/2026-04-30-agents-monitor-usage-fix-design.md`

**Working file landmarks (verify before editing — line numbers may drift):**
- `gui/src-tauri/src/lib.rs`
  - Tasks code: ~lines 1968–2135 (`Task`, `TasksData`, file helpers, all 6 commands)
  - Usage code: ~lines 2137–2366 (`UsageStats`, `Credentials*`, `get_usage_stats`, BASE constants)
  - `invoke_handler!`: ~line 3060+ (registrations for both)
- `gui/src/App.tsx`
  - `Section` type: ~line 324
  - `Task` interface: ~line 338
  - Default section: ~line 362 (`useState<Section>("tasks")`)
  - Tasks state hooks: ~lines 443–453
  - Tasks effects: ~lines 528–529
  - Task handlers: ~lines 1072–1160
  - Tasks nav item: ~lines 1480–1485
  - Usage widget JSX: ~lines 1531–1595
  - `usageBarColor`: ~line 1466
  - Section render switch: ~lines 3763–3769
  - `renderTasksSection`: ~lines 3043–3450

---

## Task 0: Branch + worktree setup

**Files:** none

- [ ] **Step 1: Confirm clean working tree**

```bash
cd /home/markmiddo/dev/misc/synthia
git status
```

Expected: only the design doc just committed (already on `development`). If other untracked files exist (`docs/plans/2026-02-*`, etc.), leave them — they are unrelated.

- [ ] **Step 2: Create feature branch off development**

```bash
cd /home/markmiddo/dev/misc/synthia
git checkout -b feature/agents-monitor-usage-fix development
```

Expected: switched to new branch.

- [ ] **Step 3: Add reqwest dependency**

Edit `gui/src-tauri/Cargo.toml`. After the existing `[dependencies]` section, add:

```toml
reqwest = { version = "0.12", features = ["blocking", "json", "rustls-tls"], default-features = false }
```

- [ ] **Step 4: Verify it compiles**

```bash
cd /home/markmiddo/dev/misc/synthia/gui/src-tauri
cargo check
```

Expected: success (downloads reqwest). If it fails on TLS, retry once — flaky network. If still fails, capture the error and stop.

- [ ] **Step 5: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock
git commit -m "chore(gui): add reqwest dep for OAuth usage API"
```

---

## Task 1: Remove Tasks Rust backend

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Remove `Task` struct, `TasksData`, file helpers, and all six commands**

Delete the contiguous block from the line `#[derive(Deserialize, Serialize, Debug, Clone)]` immediately preceding `struct Task {` through the end of `fn reorder_tasks(...)` (closing `}`). This is roughly lines 1968–2135 — verify by searching for `struct Task {` and locating the end of `reorder_tasks`.

Specifically remove:
- `struct Task { ... }`
- `struct TasksData { ... }`
- `fn get_tasks_file()`
- `fn load_tasks()` (the file loader, NOT `load_tasks_for_session` near line 473 — that one stays)
- `fn save_tasks()`
- `#[tauri::command] fn list_tasks()`
- `#[tauri::command] fn add_task()`
- `#[tauri::command] fn update_task()`
- `#[tauri::command] fn delete_task()`
- `#[tauri::command] fn move_task()`
- `#[tauri::command] fn reorder_tasks()`

Keep the `// === USAGE COMMANDS ===` divider that immediately follows; replace the removed section with `// === (Tasks/Kanban code removed — superseded by agents monitor) ===`.

- [ ] **Step 2: Remove handler registrations**

In the `invoke_handler!` macro near line 3060+, remove these entries:
- `list_tasks,`
- `add_task,`
- `update_task,`
- `delete_task,`
- `move_task,`
- `reorder_tasks,`

- [ ] **Step 3: Verify it compiles**

```bash
cd /home/markmiddo/dev/misc/synthia/gui/src-tauri
cargo check
```

Expected: success. If errors mention `Task` or `tasks` other than `WorktreeTask` (line 207 in App.tsx — that's frontend) or `load_tasks_for_session` (worktree code), investigate before proceeding. If a warning appears about unused `dirs` import — leave it; will be needed elsewhere.

- [ ] **Step 4: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src-tauri/src/lib.rs
git commit -m "refactor(gui): remove tasks/kanban backend commands"
```

---

## Task 2: Remove Tasks frontend

**Files:**
- Modify: `gui/src/App.tsx`

- [ ] **Step 1: Remove `Task` interface**

Find the standalone `interface Task { ... }` block (near line 338). Remove the entire block. **Do not remove `interface WorktreeTask` (near line 207) — it is unrelated.**

- [ ] **Step 2: Update `Section` type**

Find (near line 324):

```ts
type Section = "worktrees" | "knowledge" | "tasks" | "voice" | "memory" | "config" | "github";
```

Replace with:

```ts
type Section = "worktrees" | "knowledge" | "agents" | "voice" | "memory" | "config" | "github";
```

- [ ] **Step 3: Change default section**

Find:

```ts
const [currentSection, setCurrentSection] = useState<Section>("tasks");
```

Replace with:

```ts
const [currentSection, setCurrentSection] = useState<Section>("agents");
```

- [ ] **Step 4: Remove tasks state hooks**

Remove the contiguous block (~lines 443–453) starting from the comment `// Tasks state` through the line `const [dragOverTaskId, setDragOverTaskId] = useState<string | null>(null);`. That's:

```ts
  // Tasks state
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showAddTask, setShowAddTask] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskDesc, setNewTaskDesc] = useState("");
  const [newTaskTags, setNewTaskTags] = useState<string[]>([]);
  const [newTaskDue, setNewTaskDue] = useState("");
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverTaskId, setDragOverTaskId] = useState<string | null>(null);
```

- [ ] **Step 5: Remove tasks load effect**

Remove the block (~line 528):

```ts
    if (currentSection === "tasks") {
      loadTasks();
    }
```

- [ ] **Step 6: Remove all task handlers**

Remove these functions in their entirety (they are contiguous around lines 1072–1160):
- `loadTasks`
- `handleAddTask`
- `handleUpdateTask`
- `handleMoveTask`
- `handleDeleteTask`
- `handleReorderTask` (and any related drag/drop handler functions: `handleDragStart`, `handleDragOver`, `handleDragLeave`, `handleDrop`, `handleDragEnd` — verify each only touches tasks; if any are shared with worktrees or knowledge, KEEP that one)

Search for each function name first to confirm it has no other callers outside the Tasks section.

- [ ] **Step 7: Remove tasks nav item**

Remove this `button` element near line 1480:

```tsx
<button
  className={`nav-item ${currentSection === "tasks" ? "active" : ""}`}
  onClick={() => { setCurrentSection("tasks"); loadTasks(); }}
>
  ...
  Tasks
</button>
```

The exact JSX may differ — match by `Tasks` label and `currentSection === "tasks"`.

- [ ] **Step 8: Remove tasks render in switch**

Remove from the section switch (~line 3766):

```tsx
{currentSection === "tasks" && renderTasksSection()}
```

- [ ] **Step 9: Remove `renderTasksSection`**

Remove the entire `function renderTasksSection() { ... }` definition (from ~line 3043 to its closing brace, approx. 400 lines). It ends just before `function renderKnowledgeSection()`.

- [ ] **Step 10: Type-check**

```bash
cd /home/markmiddo/dev/misc/synthia/gui
npx tsc --noEmit
```

Expected: zero errors. If errors mention `Task`, `tasks`, or any task-related identifier you missed, remove the offender. If errors mention `WorktreeTask` something is wrong — restore it.

- [ ] **Step 11: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src/App.tsx
git commit -m "refactor(gui): remove tasks/kanban frontend"
```

---

## Task 3: Add agents discovery — Rust core

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Add types and module-level helpers**

After the `// === (Tasks/Kanban code removed ...) ===` marker (or wherever the Tasks code used to live), insert:

```rust
// === AGENTS COMMANDS ===

#[derive(Serialize, Debug, Clone)]
struct AgentInfo {
    pid: u32,
    cwd: String,
    project_name: String,
    branch: Option<String>,
    status: String, // "active" | "idle" | "stale"
    started_at: String,
    last_activity: Option<String>,
    last_user_msg: Option<String>,
    last_action: Option<String>,
    session_id: Option<String>,
    jsonl_path: Option<String>,
}

/// Encode an absolute filesystem path the same way Claude Code does:
/// replace `/` with `-`. Leading slash → leading `-`.
/// e.g. "/home/markmiddo/dev/misc/synthia" → "-home-markmiddo-dev-misc-synthia"
fn encode_project_dir(cwd: &str) -> String {
    cwd.replace('/', "-")
}

/// Read /proc/<pid>/cwd symlink. Returns None on permission error.
fn read_proc_cwd(pid: u32) -> Option<String> {
    let link = format!("/proc/{}/cwd", pid);
    fs::read_link(&link).ok().and_then(|p| p.to_str().map(|s| s.to_string()))
}

/// Parse `ps -eo etime` (e.g. "01:23", "1-02:03:04", "1234:56") into seconds.
fn parse_etime(etime: &str) -> u64 {
    let etime = etime.trim();
    let (days, rest) = match etime.split_once('-') {
        Some((d, r)) => (d.parse::<u64>().unwrap_or(0), r),
        None => (0, etime),
    };
    let parts: Vec<&str> = rest.split(':').collect();
    let (h, m, s) = match parts.as_slice() {
        [h, m, s] => (h.parse().unwrap_or(0), m.parse().unwrap_or(0), s.parse().unwrap_or(0)),
        [m, s] => (0u64, m.parse().unwrap_or(0), s.parse().unwrap_or(0)),
        _ => (0, 0, 0),
    };
    days * 86400 + h * 3600 + m * 60 + s
}
```

- [ ] **Step 2: Add `ps` runner**

Below the helpers, add:

```rust
/// Returns Vec of (pid, etime_seconds, full_argv).
/// Uses `ps` rather than walking /proc to keep argv assembly simple.
fn list_claude_processes(self_pid: u32) -> Vec<(u32, u64, String)> {
    use std::process::Command;
    let output = match Command::new("ps")
        .args(["-eo", "pid=,etime=,args="])
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => return Vec::new(),
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut out = Vec::new();
    for line in stdout.lines() {
        let line = line.trim_start();
        if line.is_empty() {
            continue;
        }
        // pid<sp>etime<sp>argv
        let mut parts = line.splitn(3, char::is_whitespace).filter(|s| !s.is_empty());
        let pid: u32 = match parts.next().and_then(|s| s.parse().ok()) {
            Some(p) => p,
            None => continue,
        };
        if pid == self_pid {
            continue;
        }
        let etime_str = match parts.next() { Some(s) => s, None => continue };
        let argv = match parts.next() { Some(s) => s.to_string(), None => continue };

        // Filter: must look like the Claude Code CLI, not grep, not statusline shell, not synthia itself.
        let argv_lc = argv.to_lowercase();
        if argv_lc.contains("grep ") || argv_lc.contains("statusline") {
            continue;
        }
        // Heuristic: argv contains "claude" as a token AND is node-driven OR the binary basename is `claude`.
        // Accept if the first token's basename is `claude`, OR argv contains "/claude/cli.js" style.
        let first = argv.split_whitespace().next().unwrap_or("");
        let first_base = std::path::Path::new(first).file_name().and_then(|s| s.to_str()).unwrap_or("");
        let looks_like_claude = first_base == "claude"
            || argv.contains("/claude/cli")
            || argv.contains("@anthropic-ai/claude-code");
        if !looks_like_claude {
            continue;
        }

        out.push((pid, parse_etime(etime_str), argv));
    }
    out
}
```

- [ ] **Step 3: Add JSONL tail parser**

Add:

```rust
#[derive(Default)]
struct SessionSnapshot {
    last_user_msg: Option<String>,
    last_action: Option<String>,
    session_id: Option<String>,
    last_activity: Option<String>,
}

/// Read up to the last ~400 lines of a JSONL file and pull out:
/// - last user message (text, truncated to 200 chars)
/// - last assistant tool_use (name + first 60 chars of a relevant input field)
/// - sessionId (from any line that has it)
/// - latest entry timestamp
fn snapshot_session(jsonl_path: &std::path::Path) -> SessionSnapshot {
    let content = match fs::read_to_string(jsonl_path) {
        Ok(c) => c,
        Err(_) => return SessionSnapshot::default(),
    };
    let lines: Vec<&str> = content.lines().collect();
    let start = lines.len().saturating_sub(400);
    let tail = &lines[start..];

    let mut snap = SessionSnapshot::default();
    for line in tail {
        let v: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if snap.session_id.is_none() {
            if let Some(sid) = v.get("sessionId").and_then(|s| s.as_str()) {
                snap.session_id = Some(sid.to_string());
            }
        }
        if let Some(ts) = v.get("timestamp").and_then(|s| s.as_str()) {
            snap.last_activity = Some(ts.to_string());
        }
        let msg_type = v.get("type").and_then(|s| s.as_str()).unwrap_or("");
        if msg_type == "user" {
            let text = v.get("message")
                .and_then(|m| m.get("content"))
                .and_then(|c| {
                    if let Some(s) = c.as_str() { return Some(s.to_string()); }
                    if let Some(arr) = c.as_array() {
                        for item in arr {
                            if item.get("type").and_then(|t| t.as_str()) == Some("text") {
                                if let Some(t) = item.get("text").and_then(|t| t.as_str()) {
                                    return Some(t.to_string());
                                }
                            }
                        }
                    }
                    None
                });
            if let Some(t) = text {
                let trimmed = t.trim();
                if !trimmed.is_empty() && !trimmed.starts_with("<") {
                    let truncated: String = trimmed.chars().take(200).collect();
                    snap.last_user_msg = Some(truncated);
                }
            }
        } else if msg_type == "assistant" {
            if let Some(content) = v.get("message").and_then(|m| m.get("content")).and_then(|c| c.as_array()) {
                for item in content {
                    if item.get("type").and_then(|t| t.as_str()) == Some("tool_use") {
                        let name = item.get("name").and_then(|s| s.as_str()).unwrap_or("tool");
                        let input = item.get("input").cloned().unwrap_or(serde_json::Value::Null);
                        let target = input.get("file_path").and_then(|s| s.as_str())
                            .or_else(|| input.get("command").and_then(|s| s.as_str()))
                            .or_else(|| input.get("pattern").and_then(|s| s.as_str()))
                            .or_else(|| input.get("description").and_then(|s| s.as_str()))
                            .unwrap_or("");
                        let target_short: String = target.chars().take(60).collect();
                        snap.last_action = Some(if target_short.is_empty() {
                            name.to_string()
                        } else {
                            format!("{}: {}", name, target_short)
                        });
                    }
                }
            }
        }
    }
    snap
}
```

- [ ] **Step 4: Add JSONL locator**

Add:

```rust
/// Find newest .jsonl file under ~/.claude/projects/<encoded-cwd>/.
/// Returns (path, mtime) on success.
fn newest_session_jsonl(cwd: &str) -> Option<(PathBuf, std::time::SystemTime)> {
    let claude_dir = get_claude_dir();
    let project_dir = claude_dir.join("projects").join(encode_project_dir(cwd));
    if !project_dir.is_dir() {
        return None;
    }
    let mut newest: Option<(PathBuf, std::time::SystemTime)> = None;
    if let Ok(entries) = fs::read_dir(&project_dir) {
        for e in entries.flatten() {
            let p = e.path();
            if p.extension().and_then(|s| s.to_str()) != Some("jsonl") { continue; }
            if let Ok(meta) = p.metadata() {
                if let Ok(m) = meta.modified() {
                    match &newest {
                        Some((_, prev)) if *prev >= m => {}
                        _ => newest = Some((p, m)),
                    }
                }
            }
        }
    }
    newest
}
```

- [ ] **Step 5: Add status classifier and started_at helper**

Add:

```rust
fn classify_status(mtime: Option<std::time::SystemTime>) -> &'static str {
    let now = std::time::SystemTime::now();
    match mtime.and_then(|m| now.duration_since(m).ok()) {
        Some(d) if d.as_secs() < 30 => "active",
        Some(d) if d.as_secs() < 300 => "idle",
        _ => "stale",
    }
}

fn started_at_from_etime(etime_secs: u64) -> String {
    let started = chrono::Local::now() - chrono::Duration::seconds(etime_secs as i64);
    started.to_rfc3339()
}
```

- [ ] **Step 6: Add the `list_active_agents` command**

Add:

```rust
#[tauri::command]
fn list_active_agents() -> Vec<AgentInfo> {
    let self_pid = std::process::id();
    let mut agents = Vec::new();

    for (pid, etime_secs, _argv) in list_claude_processes(self_pid) {
        let cwd = match read_proc_cwd(pid) {
            Some(c) => c,
            None => continue, // permissions or process gone
        };
        let project_name = std::path::Path::new(&cwd)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();

        let branch = std::process::Command::new("git")
            .args(["-C", &cwd, "branch", "--show-current"])
            .output()
            .ok()
            .and_then(|o| if o.status.success() {
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if s.is_empty() { None } else { Some(s) }
            } else { None });

        let (jsonl_path, snap, mtime) = match newest_session_jsonl(&cwd) {
            Some((p, m)) => {
                let snap = snapshot_session(&p);
                (Some(p.to_string_lossy().to_string()), snap, Some(m))
            }
            None => (None, SessionSnapshot::default(), None),
        };

        agents.push(AgentInfo {
            pid,
            cwd,
            project_name,
            branch,
            status: classify_status(mtime).to_string(),
            started_at: started_at_from_etime(etime_secs),
            last_activity: snap.last_activity,
            last_user_msg: snap.last_user_msg,
            last_action: snap.last_action,
            session_id: snap.session_id,
            jsonl_path,
        });
    }

    // Sort: active first, then idle, then stale; within each group newest started_at first.
    agents.sort_by(|a, b| {
        let order = |s: &str| match s { "active" => 0, "idle" => 1, _ => 2 };
        order(&a.status).cmp(&order(&b.status))
            .then(b.started_at.cmp(&a.started_at))
    });
    agents
}
```

- [ ] **Step 7: Add `kill_agent` command**

Add:

```rust
#[tauri::command]
fn kill_agent(pid: u32) -> Result<(), String> {
    let status = std::process::Command::new("kill")
        .arg(pid.to_string())
        .status()
        .map_err(|e| format!("Failed to spawn kill: {}", e))?;
    if !status.success() {
        return Err(format!("kill exited with status {:?}", status.code()));
    }
    Ok(())
}
```

- [ ] **Step 8: Register commands**

In `invoke_handler!`, add `list_active_agents,` and `kill_agent,`.

- [ ] **Step 9: Inline unit test for `parse_etime` and `encode_project_dir`**

At the bottom of `lib.rs` (or in an existing `#[cfg(test)] mod tests` block — create one if absent):

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn etime_parses_mm_ss() {
        assert_eq!(parse_etime("01:23"), 83);
    }

    #[test]
    fn etime_parses_hh_mm_ss() {
        assert_eq!(parse_etime("1:02:03"), 3723);
    }

    #[test]
    fn etime_parses_days() {
        assert_eq!(parse_etime("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5);
    }

    #[test]
    fn encodes_project_dir() {
        assert_eq!(
            encode_project_dir("/home/markmiddo/dev/misc/synthia"),
            "-home-markmiddo-dev-misc-synthia"
        );
    }
}
```

If a `mod tests` already exists, append these test functions inside it instead.

- [ ] **Step 10: Run tests**

```bash
cd /home/markmiddo/dev/misc/synthia/gui/src-tauri
cargo test --lib
```

Expected: 4 new tests pass (existing tests, if any, also pass).

- [ ] **Step 11: Build succeeds**

```bash
cd /home/markmiddo/dev/misc/synthia/gui/src-tauri
cargo check
```

Expected: success, no warnings about unused `AgentInfo` etc.

- [ ] **Step 12: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add list_active_agents and kill_agent commands"
```

---

## Task 4: Rewrite `get_usage_stats` to use OAuth API

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Replace existing `UsageStats` struct and constants**

Locate the block from `// === USAGE COMMANDS ===` through the end of `fn get_usage_stats()`. Delete the entire block including:
- `BASE_SESSION_LIMIT`, `BASE_WEEKLY_LIMIT`, `BASE_SONNET_WEEKLY_LIMIT`
- `parse_tier_multiplier`
- `Credentials`, `CredentialsOAuth` (we'll redefine)
- `UsageStats` struct
- `get_usage_stats` body

Replace with the new implementation in the next steps.

- [ ] **Step 2: Insert new types**

Insert at the same location:

```rust
// === USAGE COMMANDS ===

#[derive(Serialize, Debug, Clone, Default)]
struct UsageStats {
    five_hour_pct: f64,
    five_hour_resets_at: String,
    five_hour_resets_in: String,
    seven_day_pct: f64,
    seven_day_resets_at: String,
    seven_day_resets_in: String,
    seven_day_opus_pct: Option<f64>,
    seven_day_opus_resets_at: Option<String>,
    seven_day_opus_resets_in: Option<String>,
    subscription_type: Option<String>,
    error: Option<String>,
}

#[derive(Deserialize, Debug)]
struct CredsFile {
    #[serde(rename = "claudeAiOauth")]
    claude_ai_oauth: Option<CredsOAuth>,
}

#[derive(Deserialize, Debug)]
struct CredsOAuth {
    #[serde(rename = "accessToken")]
    access_token: Option<String>,
    #[serde(rename = "subscriptionType")]
    subscription_type: Option<String>,
}

#[derive(Deserialize, Debug)]
struct UsageResponse {
    five_hour: Option<UsageWindow>,
    seven_day: Option<UsageWindow>,
    seven_day_opus: Option<UsageWindow>,
}

#[derive(Deserialize, Debug)]
struct UsageWindow {
    utilization: Option<f64>,
    resets_at: Option<String>,
}
```

- [ ] **Step 3: Add caches**

Below the types, add:

```rust
use std::sync::Mutex;
use std::time::{Duration, Instant};

static USAGE_TOKEN_CACHE: Mutex<Option<(String, Instant)>> = Mutex::new(None);
static USAGE_RESPONSE_CACHE: Mutex<Option<(UsageStats, Instant)>> = Mutex::new(None);

const TOKEN_TTL: Duration = Duration::from_secs(900);   // 15 min
const RESPONSE_TTL: Duration = Duration::from_secs(60); // 60 s
const STALE_OK: Duration = Duration::from_secs(600);    // 10 min on error
```

If `Mutex` / `Instant` / `Duration` are already imported elsewhere in the file, drop the redundant `use`.

- [ ] **Step 4: Add helpers**

```rust
fn read_oauth_token_cached() -> Option<(String, Option<String>)> {
    {
        let cache = USAGE_TOKEN_CACHE.lock().ok()?;
        if let Some((tok, when)) = cache.as_ref() {
            if when.elapsed() < TOKEN_TTL {
                return Some((tok.clone(), None));
            }
        }
    }
    let creds_path = get_claude_dir().join(".credentials.json");
    let content = fs::read_to_string(&creds_path).ok()?;
    let creds: CredsFile = serde_json::from_str(&content).ok()?;
    let oauth = creds.claude_ai_oauth?;
    let token = oauth.access_token?;
    if let Ok(mut cache) = USAGE_TOKEN_CACHE.lock() {
        *cache = Some((token.clone(), Instant::now()));
    }
    Some((token, oauth.subscription_type))
}

fn humanize_duration_until(iso: &str) -> String {
    let target = match chrono::DateTime::parse_from_rfc3339(iso) {
        Ok(t) => t,
        Err(_) => return String::new(),
    };
    let now = chrono::Utc::now();
    let delta = target.with_timezone(&chrono::Utc) - now;
    let secs = delta.num_seconds();
    if secs <= 0 {
        return "now".to_string();
    }
    let h = secs / 3600;
    let m = (secs % 3600) / 60;
    if h > 0 {
        format!("{}h {}m", h, m)
    } else {
        format!("{}m", m)
    }
}
```

- [ ] **Step 5: Implement `get_usage_stats`**

```rust
#[tauri::command]
fn get_usage_stats() -> UsageStats {
    // Serve from response cache when fresh
    if let Ok(cache) = USAGE_RESPONSE_CACHE.lock() {
        if let Some((stats, when)) = cache.as_ref() {
            if when.elapsed() < RESPONSE_TTL {
                return stats.clone();
            }
        }
    }

    let (token, subscription_type) = match read_oauth_token_cached() {
        Some(v) => v,
        None => {
            return UsageStats {
                error: Some("No Claude credentials found".to_string()),
                ..Default::default()
            };
        }
    };

    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(5))
        .build()
    {
        Ok(c) => c,
        Err(e) => return UsageStats {
            error: Some(format!("HTTP client error: {}", e)),
            ..Default::default()
        },
    };

    let resp = client
        .get("https://api.anthropic.com/oauth/usage")
        .header("authorization", format!("Bearer {}", token))
        .header("anthropic-beta", "oauth-2025-04-20")
        .header("accept", "application/json")
        .header("user-agent", "synthia-gui/0.1")
        .send();

    let body: UsageResponse = match resp {
        Ok(r) if r.status().is_success() => match r.json::<UsageResponse>() {
            Ok(b) => b,
            Err(e) => return cached_or_error(format!("parse error: {}", e)),
        },
        Ok(r) => return cached_or_error(format!("HTTP {}", r.status())),
        Err(e) => return cached_or_error(format!("network: {}", e)),
    };

    let mut stats = UsageStats {
        subscription_type,
        ..Default::default()
    };

    if let Some(w) = body.five_hour {
        stats.five_hour_pct = w.utilization.unwrap_or(0.0);
        if let Some(r) = w.resets_at {
            stats.five_hour_resets_in = humanize_duration_until(&r);
            stats.five_hour_resets_at = r;
        }
    }
    if let Some(w) = body.seven_day {
        stats.seven_day_pct = w.utilization.unwrap_or(0.0);
        if let Some(r) = w.resets_at {
            stats.seven_day_resets_in = humanize_duration_until(&r);
            stats.seven_day_resets_at = r;
        }
    }
    if let Some(w) = body.seven_day_opus {
        stats.seven_day_opus_pct = w.utilization;
        if let Some(r) = w.resets_at {
            stats.seven_day_opus_resets_in = Some(humanize_duration_until(&r));
            stats.seven_day_opus_resets_at = Some(r);
        }
    }

    if let Ok(mut cache) = USAGE_RESPONSE_CACHE.lock() {
        *cache = Some((stats.clone(), Instant::now()));
    }
    stats
}

fn cached_or_error(err: String) -> UsageStats {
    if let Ok(cache) = USAGE_RESPONSE_CACHE.lock() {
        if let Some((stats, when)) = cache.as_ref() {
            if when.elapsed() < STALE_OK {
                let mut s = stats.clone();
                s.error = Some(format!("{} (showing cached)", err));
                return s;
            }
        }
    }
    UsageStats { error: Some(err), ..Default::default() }
}
```

- [ ] **Step 6: Verify it compiles**

```bash
cd /home/markmiddo/dev/misc/synthia/gui/src-tauri
cargo check
```

Expected: success. If `Mutex<Option<(UsageStats, Instant)>>` complains about not implementing `Send`, ensure `UsageStats` derives `Clone` (it does in step 2).

- [ ] **Step 7: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): rewrite get_usage_stats to use OAuth usage API"
```

---

## Task 5: Build Agents section UI

**Files:**
- Modify: `gui/src/App.tsx`
- Modify: `gui/src/App.css`

- [ ] **Step 1: Add `AgentInfo` type**

Near the other interfaces in `App.tsx` (around where `Task` used to live, ~line 338):

```ts
interface AgentInfo {
  pid: number;
  cwd: string;
  project_name: string;
  branch: string | null;
  status: "active" | "idle" | "stale";
  started_at: string;
  last_activity: string | null;
  last_user_msg: string | null;
  last_action: string | null;
  session_id: string | null;
  jsonl_path: string | null;
}
```

- [ ] **Step 2: Add agents state**

Inside the main component (where Tasks state used to be, near line 443), insert:

```ts
  // Agents state
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [expandedAgentPid, setExpandedAgentPid] = useState<number | null>(null);
  const [agentsLoading, setAgentsLoading] = useState(true);
```

- [ ] **Step 3: Add load function and polling effect**

Add the loader near other load functions:

```ts
  async function loadAgents() {
    try {
      const result = await invoke<AgentInfo[]>("list_active_agents");
      setAgents(result);
    } catch (e) {
      console.error("Failed to load agents:", e);
    } finally {
      setAgentsLoading(false);
    }
  }

  async function handleKillAgent(pid: number) {
    if (!confirm(`Send SIGTERM to agent ${pid}?`)) return;
    try {
      await invoke("kill_agent", { pid });
      loadAgents();
    } catch (e) {
      alert(`Failed to kill agent: ${e}`);
    }
  }
```

Add a polling `useEffect` near the section's other effects:

```ts
  useEffect(() => {
    if (currentSection !== "agents") return;
    loadAgents();
    const id = setInterval(loadAgents, 5000);
    return () => clearInterval(id);
  }, [currentSection]);
```

- [ ] **Step 4: Add nav button**

Where the Tasks nav button used to be (~line 1480), insert:

```tsx
<button
  className={`nav-item ${currentSection === "agents" ? "active" : ""}`}
  onClick={() => setCurrentSection("agents")}
>
  <span className="nav-icon">⚙</span>
  Agents
</button>
```

If existing nav buttons use a different icon convention (e.g. SVG component, lucide-react), match that style. Check sibling nav items in the file.

- [ ] **Step 5: Add render switch entry**

In the section switch (~line 3766), insert:

```tsx
{currentSection === "agents" && renderAgentsSection()}
```

- [ ] **Step 6: Implement `renderAgentsSection`**

Add this function in the same place `renderTasksSection` used to live (~line 3043, which is now empty):

```tsx
  function renderAgentsSection() {
    function elapsedSince(iso: string): string {
      const then = new Date(iso).getTime();
      const now = Date.now();
      const secs = Math.max(0, Math.floor((now - then) / 1000));
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      if (h > 0) return `${h}h ${m}m`;
      if (m > 0) return `${m}m ${s}s`;
      return `${s}s`;
    }

    return (
      <div className="agents-section">
        <div className="agents-header">
          <h2>Claude Code Agents</h2>
          <span className="agents-count">
            {agents.length} {agents.length === 1 ? "agent" : "agents"} running
          </span>
        </div>

        {agentsLoading && agents.length === 0 ? (
          <div className="agents-loading">Scanning…</div>
        ) : agents.length === 0 ? (
          <div className="agents-empty">No Claude Code agents running</div>
        ) : (
          <ul className="agents-list">
            {agents.map((a) => {
              const expanded = expandedAgentPid === a.pid;
              return (
                <li
                  key={a.pid}
                  className={`agent-row agent-${a.status} ${expanded ? "expanded" : ""}`}
                >
                  <button
                    className="agent-summary"
                    onClick={() => setExpandedAgentPid(expanded ? null : a.pid)}
                  >
                    <span className={`agent-status-dot status-${a.status}`} />
                    <span className="agent-project">{a.project_name}</span>
                    {a.branch && <span className="agent-branch">{a.branch}</span>}
                    <span className="agent-elapsed">{elapsedSince(a.started_at)}</span>
                    <span className="agent-last-action">
                      {a.last_action ?? "—"}
                    </span>
                  </button>
                  {expanded && (
                    <div className="agent-detail">
                      {a.last_user_msg && (
                        <div className="agent-detail-block">
                          <div className="agent-detail-label">Last message</div>
                          <pre className="agent-detail-msg">{a.last_user_msg}</pre>
                        </div>
                      )}
                      {a.last_action && (
                        <div className="agent-detail-block">
                          <div className="agent-detail-label">Last action</div>
                          <code>{a.last_action}</code>
                        </div>
                      )}
                      <div className="agent-detail-block agent-meta">
                        <div>PID: {a.pid}</div>
                        <div>cwd: {a.cwd}</div>
                        {a.session_id && <div>session: {a.session_id}</div>}
                      </div>
                      <button
                        className="agent-kill-btn"
                        onClick={() => handleKillAgent(a.pid)}
                      >
                        Kill agent
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }
```

- [ ] **Step 7: Add styles**

Append to `gui/src/App.css`:

```css
/* Agents section */
.agents-section { padding: 1.5rem; }
.agents-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 1rem; }
.agents-header h2 { margin: 0; font-size: 1.25rem; }
.agents-count { color: var(--text-muted, #888); font-size: 0.875rem; }
.agents-loading, .agents-empty {
  padding: 2rem; text-align: center; color: var(--text-muted, #888);
}
.agents-list { list-style: none; padding: 0; margin: 0; }
.agent-row { border-bottom: 1px solid var(--border, #2a2a2a); }
.agent-row.expanded { background: var(--surface-2, #1a1a1a); }
.agent-summary {
  display: grid;
  grid-template-columns: 16px 1fr auto auto 2fr;
  gap: 0.75rem;
  align-items: center;
  width: 100%;
  padding: 0.75rem 0.5rem;
  background: none;
  border: none;
  color: inherit;
  text-align: left;
  cursor: pointer;
  font-size: 0.9rem;
}
.agent-summary:hover { background: var(--surface-2, #1a1a1a); }
.agent-status-dot {
  width: 10px; height: 10px; border-radius: 50%;
  display: inline-block;
}
.status-active { background: #4ade80; box-shadow: 0 0 6px #4ade80aa; }
.status-idle   { background: #fbbf24; }
.status-stale  { background: #555; }
.agent-project { font-weight: 600; }
.agent-branch  { color: var(--text-muted, #888); font-family: monospace; font-size: 0.85em; }
.agent-elapsed { color: var(--text-muted, #888); font-size: 0.85em; min-width: 5em; }
.agent-last-action {
  color: var(--text-muted, #aaa);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.agent-detail {
  padding: 0.5rem 1rem 1rem 1.75rem;
  display: flex; flex-direction: column; gap: 0.75rem;
}
.agent-detail-label {
  font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: var(--text-muted, #888); margin-bottom: 0.25rem;
}
.agent-detail-msg {
  background: var(--surface-3, #0d0d0d);
  padding: 0.5rem; border-radius: 4px;
  font-size: 0.85rem; white-space: pre-wrap; word-break: break-word;
  max-height: 12em; overflow: auto;
}
.agent-meta { font-size: 0.8rem; color: var(--text-muted, #888); }
.agent-meta > div { font-family: monospace; }
.agent-kill-btn {
  align-self: flex-start;
  background: #7f1d1d; color: #fff; border: none;
  padding: 0.4rem 0.8rem; border-radius: 4px; cursor: pointer;
  font-size: 0.85rem;
}
.agent-kill-btn:hover { background: #991b1b; }
```

- [ ] **Step 8: Type-check**

```bash
cd /home/markmiddo/dev/misc/synthia/gui
npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 9: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src/App.tsx gui/src/App.css
git commit -m "feat(gui): add Claude Code agents monitor section"
```

---

## Task 6: Update usage widget frontend

**Files:**
- Modify: `gui/src/App.tsx`
- Modify: `gui/src/App.css`

- [ ] **Step 1: Update `usageStats` type**

Find the existing `useState<{...}>` declaration for `usageStats` (~line 460) and replace its type annotation with:

```ts
  const [usageStats, setUsageStats] = useState<{
    five_hour_pct: number;
    five_hour_resets_at: string;
    five_hour_resets_in: string;
    seven_day_pct: number;
    seven_day_resets_at: string;
    seven_day_resets_in: string;
    seven_day_opus_pct: number | null;
    seven_day_opus_resets_at: string | null;
    seven_day_opus_resets_in: string | null;
    subscription_type: string | null;
    error: string | null;
  } | null>(null);
```

Note: Rust `Option<f64>` serializes as `null` (matching `f64 | null`). `Option<String>` likewise. The unset numeric `f64` defaults to `0.0` (not null) — use the field directly.

- [ ] **Step 2: Replace usage widget JSX**

Find the block starting `{usageStats && (` near line 1531 and ending at the closing `)}`. Replace the entire block with:

```tsx
{usageStats && (
  <div className="usage-widget">
    <div className="usage-header">
      <span className="usage-title">Claude Usage</span>
      {usageStats.subscription_type && (
        <span className="usage-badge">{usageStats.subscription_type}</span>
      )}
    </div>

    {usageStats.error ? (
      <div className="usage-error">
        Usage unavailable
        <div className="usage-error-detail">{usageStats.error}</div>
      </div>
    ) : (
      <>
        <div className="usage-section">
          <div className="usage-label">5-hour</div>
          <div className="usage-bar-row">
            <div className="usage-bar">
              <div
                className="usage-bar-fill"
                style={{
                  width: `${Math.min(100, usageStats.five_hour_pct)}%`,
                  background: usageBarColor(usageStats.five_hour_pct),
                }}
              />
            </div>
            <span className="usage-pct">
              {Math.round(usageStats.five_hour_pct)}%
            </span>
          </div>
          {usageStats.five_hour_resets_in && (
            <div className="usage-meta">
              Resets in {usageStats.five_hour_resets_in}
            </div>
          )}
        </div>

        <div className="usage-section">
          <div className="usage-label">7-day</div>
          <div className="usage-bar-row">
            <div className="usage-bar">
              <div
                className="usage-bar-fill"
                style={{
                  width: `${Math.min(100, usageStats.seven_day_pct)}%`,
                  background: usageBarColor(usageStats.seven_day_pct),
                }}
              />
            </div>
            <span className="usage-pct">
              {Math.round(usageStats.seven_day_pct)}%
            </span>
          </div>
          {usageStats.seven_day_resets_in && (
            <div className="usage-meta">
              Resets in {usageStats.seven_day_resets_in}
            </div>
          )}
        </div>

        {usageStats.seven_day_opus_pct !== null && (
          <div className="usage-section">
            <div className="usage-label">7-day Opus</div>
            <div className="usage-bar-row">
              <div className="usage-bar">
                <div
                  className="usage-bar-fill"
                  style={{
                    width: `${Math.min(100, usageStats.seven_day_opus_pct ?? 0)}%`,
                    background: usageBarColor(usageStats.seven_day_opus_pct ?? 0),
                  }}
                />
              </div>
              <span className="usage-pct">
                {Math.round(usageStats.seven_day_opus_pct ?? 0)}%
              </span>
            </div>
            {usageStats.seven_day_opus_resets_in && (
              <div className="usage-meta">
                Resets in {usageStats.seven_day_opus_resets_in}
              </div>
            )}
          </div>
        )}
      </>
    )}
  </div>
)}
```

- [ ] **Step 3: Confirm `usageBarColor` already handles 0–100**

Check the function near line 1466 — it's reused as-is. No change needed unless thresholds were token-count-based; if so, change to:

```ts
function usageBarColor(pct: number): string {
  if (pct >= 80) return "#ef4444";
  if (pct >= 50) return "#f59e0b";
  return "#22c55e";
}
```

- [ ] **Step 4: Add error styles**

Append to `gui/src/App.css`:

```css
.usage-error {
  padding: 0.75rem; color: var(--text-muted, #888); font-size: 0.85rem;
}
.usage-error-detail {
  font-size: 0.7rem; opacity: 0.6; margin-top: 0.25rem;
  font-family: monospace; word-break: break-all;
}
.usage-meta {
  font-size: 0.7rem; color: var(--text-muted, #888); margin-top: 0.15rem;
}
```

- [ ] **Step 5: Type-check**

```bash
cd /home/markmiddo/dev/misc/synthia/gui
npx tsc --noEmit
```

Expected: zero errors.

- [ ] **Step 6: Commit**

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src/App.tsx gui/src/App.css
git commit -m "feat(gui): rewire usage widget to OAuth API fields"
```

---

## Task 7: Build, install, manual verification

**Files:** none (runtime checks)

- [ ] **Step 1: Kill any running Synthia GUI**

```bash
pkill -f "synthia-gui" || true
sleep 1
```

- [ ] **Step 2: Build the .deb**

```bash
cd /home/markmiddo/dev/misc/synthia/gui
npm run tauri build -- --bundles deb
```

Expected: a `.deb` produced under `gui/src-tauri/target/release/bundle/deb/`. Note the exact filename.

- [ ] **Step 3: Install the .deb**

```bash
DEB=$(ls -t /home/markmiddo/dev/misc/synthia/gui/src-tauri/target/release/bundle/deb/*.deb | head -1)
sudo dpkg -i "$DEB"
```

- [ ] **Step 4: Clear webview cache**

(Per CLAUDE.md memory note — frontend changes won't appear otherwise.)

```bash
rm -rf /home/markmiddo/.local/share/com.synthia.gui/storage
```

- [ ] **Step 5: Launch and capture logs**

```bash
nohup /usr/bin/synthia-gui > /home/markmiddo/dev/misc/synthia/synthia.log 2>&1 &
sleep 3
```

- [ ] **Step 6: Verify Agents section**

Open the GUI. Open a separate terminal and start a Claude Code session somewhere (`cd ~/some-project && claude`). Within ~5s the Synthia GUI Agents section should show that agent with its project name, branch, and status dot. Click the row → details expand. Send a message in the Claude Code session → within 5s the `last_action` should update.

If the agent does not appear, run from a terminal:

```bash
ps -eo pid,etime,args | grep -E "claude" | grep -v grep
```

Verify the argv shape matches what `list_claude_processes` filters for. Adjust the heuristic in `lib.rs` if needed (most likely fix: extend the `looks_like_claude` check), rebuild, and re-test.

- [ ] **Step 7: Verify Usage widget matches statusline**

In the same Claude Code session, look at the bottom statusline (e.g. `5h 2% (4h 47m) · 7d 24% (1h 7m)`). The Synthia GUI usage widget should show the same percentages within ±1% and the same reset windows within ~1 minute.

If the widget shows "Usage unavailable", check `synthia.log` for the error string. Common causes:
- `~/.claude/.credentials.json` missing or unreadable → ensure user is signed in.
- `403`/`401` → token expired, run any Claude Code command to refresh, retry.
- Network timeout → check connectivity.

- [ ] **Step 8: Confirm Tasks section is gone**

The sidebar should no longer show a "Tasks" entry. The default landing section should be Agents.

- [ ] **Step 9: Commit any fixes from steps 6–7**

If you tweaked the process-detection heuristic or any other code:

```bash
cd /home/markmiddo/dev/misc/synthia
git add gui/src-tauri/src/lib.rs
git commit -m "fix(gui): adjust agent detection heuristic for actual ps argv"
```

If no changes were needed, skip.

---

## Task 8: Merge and deploy

**Files:** none

- [ ] **Step 1: Push branch**

```bash
cd /home/markmiddo/dev/misc/synthia
git push -u origin feature/agents-monitor-usage-fix
```

- [ ] **Step 2: Open PR to development**

```bash
cd /home/markmiddo/dev/misc/synthia
gh pr create --base development --title "feat(gui): replace Tasks with Agents monitor; fix usage widget" --body "$(cat <<'EOF'
## Summary
- Removes unused Tasks/Kanban section (frontend + Rust commands)
- Adds Claude Code Agents monitor section (auto-refreshing 5s) backed by ps + JSONL tail
- Rewrites Claude Usage widget to call the official OAuth usage endpoint, matching the statusline

## Test plan
- [ ] Build .deb, install, clear webview cache
- [ ] Verify Agents section shows running Claude Code sessions with project, branch, last action
- [ ] Verify clicking a row shows last user message + last 3 actions
- [ ] Verify Usage widget percentages match statusline within ±1%
- [ ] Confirm Tasks sidebar entry removed
EOF
)"
```

- [ ] **Step 3: Confirm CI passes**

CI gates per `CLAUDE.md`: `lint`, `typecheck`, `test (3.12)`. The Synthia repo's CI runs against the Python core in `src/synthia/` — GUI changes should not break those, but watch for any cross-cutting hits.

- [ ] **Step 4: Merge to development**

After CI green and review (or self-merge if no reviewers required):

```bash
cd /home/markmiddo/dev/misc/synthia
gh pr merge --squash --delete-branch
```

- [ ] **Step 5: PR development → main (production deploy)**

```bash
cd /home/markmiddo/dev/misc/synthia
git checkout development && git pull
gh pr create --base main --head development --title "Release: agents monitor + usage fix" --body "Includes agents monitor + usage widget fix. See feature PR for details."
```

After CI green, merge.

- [ ] **Step 6: Final reinstall from main**

```bash
cd /home/markmiddo/dev/misc/synthia
git checkout main && git pull
pkill -f "synthia-gui" || true
cd gui && npm run tauri build -- --bundles deb
DEB=$(ls -t src-tauri/target/release/bundle/deb/*.deb | head -1)
sudo dpkg -i "$DEB"
rm -rf /home/markmiddo/.local/share/com.synthia.gui/storage
nohup /usr/bin/synthia-gui > /home/markmiddo/dev/misc/synthia/synthia.log 2>&1 &
```

Done.
