# GUI Consolidation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate the TUI dashboard into the Tauri GUI, adding worktree management with proper task detection from Claude Code's new task system.

**Architecture:** Add sidebar navigation to the existing React app. Build new Rust backend commands for worktree/task scanning. Reorganize voice features into a section.

**Tech Stack:** Tauri 2, React 19, TypeScript, Rust, vanilla CSS

---

## Task 1: Add Rust Worktree Types and Config Reader

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src-tauri/src/lib.rs`

**Step 1: Add struct definitions after line 77**

Add these structs after the `InboxItem` struct:

```rust
#[derive(Deserialize, Serialize, Debug, Clone)]
struct WorktreeTask {
    id: String,
    subject: String,
    status: String,
    #[serde(rename = "activeForm")]
    active_form: Option<String>,
    #[serde(rename = "blockedBy")]
    blocked_by: Vec<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct WorktreeInfo {
    path: String,
    branch: String,
    issue_number: Option<u32>,
    session_id: Option<String>,
    tasks: Vec<WorktreeTask>,
}

#[derive(Deserialize, Debug)]
struct WorktreesConfig {
    repos: Option<Vec<String>>,
}

#[derive(Deserialize, Debug)]
struct SessionEntry {
    #[serde(rename = "sessionId")]
    session_id: String,
    #[serde(rename = "projectPath")]
    project_path: String,
}

#[derive(Deserialize, Debug)]
struct SessionsIndex {
    entries: Vec<SessionEntry>,
}
```

**Step 2: Add helper function to get worktrees config path**

```rust
fn get_worktrees_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
    PathBuf::from(home).join(".config/synthia/worktrees.yaml")
}

fn get_claude_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
    PathBuf::from(home).join(".claude")
}
```

**Step 3: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add worktree and task types for consolidation"
```

---

## Task 2: Add Rust Task Loading Function

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src-tauri/src/lib.rs`

**Step 1: Add function to load tasks from new format**

Add this function after the helper functions from Task 1:

```rust
fn load_tasks_for_session(session_id: &str) -> Vec<WorktreeTask> {
    let tasks_dir = get_claude_dir().join("tasks").join(session_id);

    if !tasks_dir.exists() {
        return Vec::new();
    }

    let mut tasks = Vec::new();

    if let Ok(entries) = fs::read_dir(&tasks_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().map(|e| e == "json").unwrap_or(false) {
                if let Ok(content) = fs::read_to_string(&path) {
                    if let Ok(task) = serde_json::from_str::<WorktreeTask>(&content) {
                        tasks.push(task);
                    }
                }
            }
        }
    }

    // Sort by ID numerically
    tasks.sort_by(|a, b| {
        a.id.parse::<u32>().unwrap_or(0).cmp(&b.id.parse::<u32>().unwrap_or(0))
    });

    tasks
}
```

**Step 2: Add function to find session for a project path**

```rust
fn find_session_for_path(project_path: &str) -> Option<String> {
    let projects_dir = get_claude_dir().join("projects");

    if !projects_dir.exists() {
        return None;
    }

    let normalized_path = PathBuf::from(project_path).canonicalize().ok()?;

    for entry in fs::read_dir(&projects_dir).ok()?.flatten() {
        if !entry.path().is_dir() {
            continue;
        }

        let index_file = entry.path().join("sessions-index.json");
        if !index_file.exists() {
            continue;
        }

        if let Ok(content) = fs::read_to_string(&index_file) {
            if let Ok(index) = serde_json::from_str::<SessionsIndex>(&content) {
                for session in index.entries {
                    if let Ok(entry_path) = PathBuf::from(&session.project_path).canonicalize() {
                        if entry_path == normalized_path {
                            return Some(session.session_id);
                        }
                    }
                }
            }
        }
    }

    None
}
```

**Step 3: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add task loading from new Claude Code format"
```

---

## Task 3: Add Rust Worktree Scanning Command

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src-tauri/src/lib.rs`

**Step 1: Add issue number extraction function**

```rust
fn extract_issue_number(branch: &str) -> Option<u32> {
    use std::str::FromStr;

    let patterns = [
        r"feature/(\d+)-",
        r"issue-(\d+)-",
        r"fix/(\d+)-",
        r"bugfix/(\d+)-",
        r"hotfix/(\d+)-",
        r"(\d+)-",
    ];

    for pattern in patterns {
        if let Ok(re) = regex::Regex::new(pattern) {
            if let Some(caps) = re.captures(branch) {
                if let Some(m) = caps.get(1) {
                    if let Ok(num) = u32::from_str(m.as_str()) {
                        return Some(num);
                    }
                }
            }
        }
    }
    None
}
```

**Step 2: Add the get_worktrees Tauri command**

```rust
#[tauri::command]
fn get_worktrees() -> Vec<WorktreeInfo> {
    let config_path = get_worktrees_config_path();

    // Load configured repos
    let repos: Vec<String> = if let Ok(content) = fs::read_to_string(&config_path) {
        // Simple YAML parsing for repos list
        let mut repos = Vec::new();
        let mut in_repos = false;
        for line in content.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with("repos:") {
                in_repos = true;
                continue;
            }
            if in_repos {
                if !line.starts_with(' ') && !line.starts_with('\t') && !trimmed.is_empty() {
                    break;
                }
                if trimmed.starts_with('-') {
                    let path = trimmed.trim_start_matches('-').trim();
                    if !path.is_empty() {
                        repos.push(path.to_string());
                    }
                }
            }
        }
        repos
    } else {
        Vec::new()
    };

    let mut worktrees = Vec::new();

    for repo in repos {
        if let Ok(output) = Command::new("git")
            .args(["worktree", "list", "--porcelain"])
            .current_dir(&repo)
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                let mut current_path = String::new();
                let mut current_branch = String::new();

                for line in stdout.lines() {
                    if line.starts_with("worktree ") {
                        current_path = line[9..].to_string();
                    } else if line.starts_with("branch ") {
                        current_branch = line[7..].to_string();
                        if current_branch.starts_with("refs/heads/") {
                            current_branch = current_branch[11..].to_string();
                        }
                    } else if line.is_empty() && !current_path.is_empty() {
                        let session_id = find_session_for_path(&current_path);
                        let tasks = session_id.as_ref()
                            .map(|id| load_tasks_for_session(id))
                            .unwrap_or_default();

                        worktrees.push(WorktreeInfo {
                            path: current_path.clone(),
                            branch: current_branch.clone(),
                            issue_number: extract_issue_number(&current_branch),
                            session_id,
                            tasks,
                        });

                        current_path.clear();
                        current_branch.clear();
                    }
                }

                // Handle last entry
                if !current_path.is_empty() {
                    let session_id = find_session_for_path(&current_path);
                    let tasks = session_id.as_ref()
                        .map(|id| load_tasks_for_session(id))
                        .unwrap_or_default();

                    worktrees.push(WorktreeInfo {
                        path: current_path,
                        branch: current_branch.clone(),
                        issue_number: extract_issue_number(&current_branch),
                        session_id,
                        tasks,
                    });
                }
            }
        }
    }

    worktrees
}
```

**Step 3: Add regex dependency to Cargo.toml**

In `/home/markmiddo/dev/misc/synthia/gui/src-tauri/Cargo.toml`, add under `[dependencies]`:

```toml
regex = "1"
```

**Step 4: Register command in invoke_handler (around line 795)**

Add `get_worktrees` to the `generate_handler!` macro list.

**Step 5: Commit**

```bash
git add gui/src-tauri/src/lib.rs gui/src-tauri/Cargo.toml
git commit -m "feat(gui): add worktree scanning command"
```

---

## Task 4: Add Rust Resume Session Command

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src-tauri/src/lib.rs`

**Step 1: Add resume_session command**

```rust
#[tauri::command]
fn resume_session(path: String, session_id: Option<String>) -> Result<String, String> {
    // Build the claude command
    let mut args = vec!["cli".to_string(), "split-pane".to_string(), "--".to_string()];

    if let Some(sid) = session_id {
        args.push("claude".to_string());
        args.push("--resume".to_string());
        args.push(sid);
    } else {
        args.push("claude".to_string());
    }

    // Use wezterm cli to open a new pane
    Command::new("wezterm")
        .args(&args)
        .current_dir(&path)
        .spawn()
        .map_err(|e| format!("Failed to open WezTerm pane: {}", e))?;

    Ok("Session opened in WezTerm".to_string())
}
```

**Step 2: Register command in invoke_handler**

Add `resume_session` to the `generate_handler!` macro list.

**Step 3: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add resume session command for WezTerm"
```

---

## Task 5: Add TypeScript Types for Worktrees

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Add interfaces after existing types (around line 37)**

```typescript
interface WorktreeTask {
  id: string;
  subject: string;
  status: "pending" | "in_progress" | "completed";
  active_form?: string;
  blocked_by: string[];
}

interface WorktreeInfo {
  path: string;
  branch: string;
  issue_number?: number;
  session_id?: string;
  tasks: WorktreeTask[];
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add TypeScript types for worktrees"
```

---

## Task 6: Add Navigation State and Section Type

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Update currentView type (line 48)**

Change from:
```typescript
const [currentView, setCurrentView] = useState<"main" | "history" | "words" | "clipboard" | "inbox">("main");
```

To:
```typescript
type Section = "worktrees" | "voice" | "memory" | "config";
type VoiceView = "main" | "history" | "words";

const [currentSection, setCurrentSection] = useState<Section>("worktrees");
const [voiceView, setVoiceView] = useState<VoiceView>("main");
```

**Step 2: Add worktrees state after other state declarations**

```typescript
const [worktrees, setWorktrees] = useState<WorktreeInfo[]>([]);
const [selectedWorktree, setSelectedWorktree] = useState<WorktreeInfo | null>(null);
```

**Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add navigation state for sections"
```

---

## Task 7: Add Worktree Loading Function

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Add loadWorktrees function after other load functions**

```typescript
async function loadWorktrees() {
  try {
    const result = await invoke<WorktreeInfo[]>("get_worktrees");
    setWorktrees(result);
  } catch (e) {
    // Ignore errors
  }
}
```

**Step 2: Add to useEffect initialization (around line 83)**

Add `loadWorktrees();` call and update the interval:

```typescript
loadWorktrees();

const interval = setInterval(() => {
  checkStatus();
  checkRemoteStatus();
  if (currentSection === "worktrees") loadWorktrees();
  if (currentSection === "voice" && voiceView === "history") loadHistory();
}, 2000);
```

**Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add worktree loading function"
```

---

## Task 8: Add Resume Session Handler

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Add handler function**

```typescript
async function handleResumeSession(worktree: WorktreeInfo) {
  try {
    await invoke("resume_session", {
      path: worktree.path,
      sessionId: worktree.session_id,
    });
  } catch (e) {
    setError(String(e));
  }
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add resume session handler"
```

---

## Task 9: Add Sidebar CSS

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.css`

**Step 1: Add sidebar styles at end of file**

```css
/* Sidebar Navigation */
.app-layout {
  display: flex;
  height: 100vh;
  background: linear-gradient(135deg, #0a0b14 0%, #0f1419 100%);
}

.sidebar {
  width: 200px;
  background: rgba(6, 182, 212, 0.03);
  border-right: 1px solid rgba(6, 182, 212, 0.15);
  padding: 1rem 0;
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 0 1rem 1rem;
  border-bottom: 1px solid rgba(6, 182, 212, 0.1);
  margin-bottom: 0.5rem;
}

.sidebar-logo {
  font-family: 'Orbitron', monospace;
  font-size: 1.1rem;
  color: #06b6d4;
  letter-spacing: 0.15em;
}

.sidebar-nav {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.5rem;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 8px;
  cursor: pointer;
  color: #94a3b8;
  transition: all 0.2s ease;
  border: none;
  background: transparent;
  width: 100%;
  text-align: left;
  font-size: 0.9rem;
}

.nav-item:hover {
  background: rgba(6, 182, 212, 0.1);
  color: #e2e8f0;
}

.nav-item.active {
  background: rgba(6, 182, 212, 0.15);
  color: #06b6d4;
}

.nav-item-icon {
  font-size: 1.1rem;
}

.main-content {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}
```

**Step 2: Commit**

```bash
git add gui/src/App.css
git commit -m "style(gui): add sidebar navigation styles"
```

---

## Task 10: Add Worktrees Section CSS

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.css`

**Step 1: Add worktree styles**

```css
/* Worktrees Section */
.worktrees-layout {
  display: flex;
  gap: 1rem;
  height: 100%;
}

.worktrees-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.worktree-item {
  padding: 1rem;
  background: rgba(6, 182, 212, 0.05);
  border: 1px solid rgba(6, 182, 212, 0.1);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.worktree-item:hover {
  background: rgba(6, 182, 212, 0.1);
  border-color: rgba(6, 182, 212, 0.2);
}

.worktree-item.selected {
  background: rgba(6, 182, 212, 0.15);
  border-color: #06b6d4;
}

.worktree-branch {
  font-weight: 500;
  color: #e2e8f0;
  margin-bottom: 0.25rem;
}

.worktree-path {
  font-size: 0.75rem;
  color: #64748b;
  font-family: monospace;
}

.worktree-meta {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 0.5rem;
}

.worktree-issue {
  font-size: 0.75rem;
  color: #06b6d4;
  background: rgba(6, 182, 212, 0.1);
  padding: 0.125rem 0.5rem;
  border-radius: 4px;
}

.worktree-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  color: #94a3b8;
}

.progress-bar {
  width: 60px;
  height: 4px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 2px;
  transition: width 0.3s ease;
}

.progress-fill.completed {
  background: #22c55e;
}

.progress-fill.in-progress {
  background: #f59e0b;
}

.progress-fill.none {
  background: #64748b;
}

/* Task Detail Panel */
.task-panel {
  width: 300px;
  background: rgba(6, 182, 212, 0.03);
  border: 1px solid rgba(6, 182, 212, 0.1);
  border-radius: 8px;
  padding: 1rem;
  overflow-y: auto;
}

.task-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 1px solid rgba(6, 182, 212, 0.1);
}

.task-panel-title {
  font-weight: 500;
  color: #e2e8f0;
}

.task-panel-actions {
  display: flex;
  gap: 0.5rem;
}

.task-panel-btn {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  border-radius: 4px;
  border: 1px solid rgba(6, 182, 212, 0.3);
  background: transparent;
  color: #06b6d4;
  cursor: pointer;
  transition: all 0.2s ease;
}

.task-panel-btn:hover {
  background: rgba(6, 182, 212, 0.1);
}

.task-panel-btn.primary {
  background: rgba(6, 182, 212, 0.2);
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.task-item {
  display: flex;
  align-items: flex-start;
  gap: 0.5rem;
  padding: 0.5rem;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
}

.task-item.blocked {
  opacity: 0.5;
}

.task-status {
  font-size: 0.875rem;
  margin-top: 0.125rem;
}

.task-status.completed { color: #22c55e; }
.task-status.in-progress { color: #f59e0b; }
.task-status.pending { color: #64748b; }

.task-content {
  flex: 1;
}

.task-subject {
  font-size: 0.8rem;
  color: #e2e8f0;
  line-height: 1.3;
}

.task-blocked-by {
  font-size: 0.7rem;
  color: #f59e0b;
  margin-top: 0.25rem;
}

.empty-state {
  text-align: center;
  padding: 2rem;
  color: #64748b;
}
```

**Step 2: Commit**

```bash
git add gui/src/App.css
git commit -m "style(gui): add worktrees and task panel styles"
```

---

## Task 11: Build Sidebar Component JSX

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Create renderSidebar function before the return statements**

```typescript
function renderSidebar() {
  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <div className="sidebar-logo">SYNTHIA</div>
      </div>
      <nav className="sidebar-nav">
        <button
          className={`nav-item ${currentSection === "worktrees" ? "active" : ""}`}
          onClick={() => setCurrentSection("worktrees")}
        >
          <span className="nav-item-icon">&#128193;</span>
          Worktrees
        </button>
        <button
          className={`nav-item ${currentSection === "voice" ? "active" : ""}`}
          onClick={() => { setCurrentSection("voice"); setVoiceView("main"); }}
        >
          <span className="nav-item-icon">&#127908;</span>
          Voice
        </button>
        <button
          className={`nav-item ${currentSection === "memory" ? "active" : ""}`}
          onClick={() => setCurrentSection("memory")}
        >
          <span className="nav-item-icon">&#128218;</span>
          Memory
        </button>
        <button
          className={`nav-item ${currentSection === "config" ? "active" : ""}`}
          onClick={() => setCurrentSection("config")}
        >
          <span className="nav-item-icon">&#9881;</span>
          Config
        </button>
      </nav>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add sidebar navigation component"
```

---

## Task 12: Build Worktrees Section JSX

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Create renderWorktreesSection function**

```typescript
function renderWorktreesSection() {
  function getProgressInfo(tasks: WorktreeTask[]) {
    const completed = tasks.filter(t => t.status === "completed").length;
    const inProgress = tasks.filter(t => t.status === "in_progress").length;
    const total = tasks.length;

    if (total === 0) return { text: "No tasks", percent: 0, status: "none" as const };
    if (completed === total) return { text: `${completed}/${total}`, percent: 100, status: "completed" as const };
    if (inProgress > 0 || completed > 0) return { text: `${completed}/${total}`, percent: (completed / total) * 100, status: "in-progress" as const };
    return { text: `0/${total}`, percent: 0, status: "none" as const };
  }

  function getDisplayName(path: string) {
    return path.split('/').pop() || path;
  }

  return (
    <div className="worktrees-layout">
      <div className="worktrees-list">
        {worktrees.length === 0 ? (
          <div className="empty-state">
            <p>No worktrees configured</p>
            <p style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
              Add repos to ~/.config/synthia/worktrees.yaml
            </p>
          </div>
        ) : (
          worktrees.map((wt) => {
            const progress = getProgressInfo(wt.tasks);
            return (
              <div
                key={wt.path}
                className={`worktree-item ${selectedWorktree?.path === wt.path ? "selected" : ""}`}
                onClick={() => setSelectedWorktree(wt)}
              >
                <div className="worktree-branch">{getDisplayName(wt.path)}</div>
                <div className="worktree-path">{wt.branch}</div>
                <div className="worktree-meta">
                  {wt.issue_number && (
                    <span className="worktree-issue">#{wt.issue_number}</span>
                  )}
                  <div className="worktree-progress">
                    <div className="progress-bar">
                      <div
                        className={`progress-fill ${progress.status}`}
                        style={{ width: `${progress.percent}%` }}
                      />
                    </div>
                    <span>{progress.text}</span>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {selectedWorktree && (
        <div className="task-panel">
          <div className="task-panel-header">
            <span className="task-panel-title">Tasks</span>
            <div className="task-panel-actions">
              <button
                className="task-panel-btn primary"
                onClick={() => handleResumeSession(selectedWorktree)}
              >
                Resume
              </button>
            </div>
          </div>

          {selectedWorktree.tasks.length === 0 ? (
            <div className="empty-state">No tasks</div>
          ) : (
            <div className="task-list">
              {selectedWorktree.tasks.map((task) => (
                <div
                  key={task.id}
                  className={`task-item ${task.blocked_by.length > 0 ? "blocked" : ""}`}
                >
                  <span className={`task-status ${task.status.replace("_", "-")}`}>
                    {task.status === "completed" ? "✓" : task.status === "in_progress" ? "▶" : "○"}
                  </span>
                  <div className="task-content">
                    <div className="task-subject">{task.subject}</div>
                    {task.blocked_by.length > 0 && (
                      <div className="task-blocked-by">
                        blocked by #{task.blocked_by.join(", #")}
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add worktrees section component"
```

---

## Task 13: Refactor Voice Section

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Create renderVoiceSection function**

Move the existing main view, history view, and words view into a single function. Remove clipboard and inbox views.

```typescript
function renderVoiceSection() {
  // History sub-view
  if (voiceView === "history") {
    return (
      <div className="voice-section">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setVoiceView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">VOICE HISTORY</div>
          {history.length > 0 && (
            <button className="clear-all-btn" onClick={handleClearHistory}>
              Clear All
            </button>
          )}
        </div>

        <div className="history-view-content">
          {history.length === 0 ? (
            <div className="history-empty-state">
              <p>No transcriptions yet</p>
              <p className="empty-hint">Use voice dictation or assistant to see history here</p>
            </div>
          ) : (
            <div className="history-list-full">
              {history.map((entry) => (
                <div key={entry.id} className={`history-item ${entry.mode}`}>
                  <div className="history-item-header">
                    <span className={`history-mode-label ${entry.mode}`}>
                      {entry.mode === "assistant" ? "ASSISTANT" : "DICTATION"}
                    </span>
                    <span className="history-time">{formatTime(entry.timestamp)}</span>
                  </div>
                  <p className="history-text">{entry.text}</p>
                  {entry.response && (
                    <p className="history-response">→ {entry.response}</p>
                  )}
                  <div className="history-item-actions">
                    <button
                      className={`history-btn ${copiedId === entry.id ? 'copied' : ''}`}
                      onClick={() => handleCopy(entry.text, entry.id)}
                    >
                      {copiedId === entry.id ? "✓" : "Copy"}
                    </button>
                    <button
                      className="history-btn resend"
                      onClick={() => handleResend(entry.text)}
                    >
                      Re-send
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Words sub-view
  if (voiceView === "words") {
    return (
      <div className="voice-section">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setVoiceView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">WORD DICTIONARY</div>
        </div>

        <div className="words-view-content">
          <p className="words-description">
            Fix common Whisper misrecognitions. Words on the left get replaced with words on the right.
          </p>

          <div className="word-add-form">
            <input
              type="text"
              placeholder="Wrong word"
              value={newWordFrom}
              onChange={(e) => setNewWordFrom(e.target.value)}
              className="word-input"
            />
            <span className="word-arrow">→</span>
            <input
              type="text"
              placeholder="Correct word"
              value={newWordTo}
              onChange={(e) => setNewWordTo(e.target.value)}
              className="word-input"
              onKeyDown={(e) => e.key === "Enter" && handleAddWordReplacement()}
            />
            <button className="word-add-btn" onClick={handleAddWordReplacement}>
              Add
            </button>
          </div>

          <div className="word-list">
            {wordReplacements.length === 0 ? (
              <div className="words-empty-state">
                <p>No word replacements yet</p>
                <p className="empty-hint">Add words that Whisper commonly gets wrong</p>
              </div>
            ) : (
              wordReplacements.map((r, index) => (
                <div key={index} className="word-item">
                  <span className="word-from">{r.from}</span>
                  <span className="word-arrow">→</span>
                  <span className="word-to">{r.to}</span>
                  <button
                    className="word-remove-btn"
                    onClick={() => handleRemoveWordReplacement(index)}
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    );
  }

  // Main voice view
  return (
    <div className="voice-section">
      <div className="status-section">
        <div
          className={`status-indicator ${status === "running" ? "running" : ""}`}
          style={{ backgroundColor: statusColors[status] }}
        />
        <span className="status-text">{status.charAt(0).toUpperCase() + status.slice(1)}</span>
      </div>

      <div className="controls">
        {status === "stopped" ? (
          <button className="btn btn-start" onClick={handleStart}>
            Start Synthia
          </button>
        ) : (
          <button className="btn btn-stop" onClick={handleStop}>
            Stop Synthia
          </button>
        )}
      </div>

      <div className="card">
        <div className="remote-toggle">
          <span>Remote Mode (Telegram)</span>
          <button
            className={`toggle ${remoteMode ? "active" : ""}`}
            onClick={handleRemoteToggle}
          >
            <div className="toggle-knob" />
          </button>
        </div>
        <p className="remote-description">
          {remoteMode ? "Telegram bot active - control via phone" : "Telegram bot disabled"}
        </p>
      </div>

      <div className="card hotkeys">
        <h3>Hotkeys</h3>
        <div className="hotkey-row">
          <button
            className={`hotkey-btn ${editingKey === "dictate" ? "editing" : ""}`}
            onClick={() => setEditingKey("dictate")}
          >
            {editingKey === "dictate" ? "Press key..." : dictateKey}
          </button>
          <span>Dictation</span>
        </div>
        <div className="hotkey-row">
          <button
            className={`hotkey-btn ${editingKey === "assistant" ? "editing" : ""}`}
            onClick={() => setEditingKey("assistant")}
          >
            {editingKey === "assistant" ? "Press key..." : assistantKey}
          </button>
          <span>AI Assistant</span>
        </div>
      </div>

      <button
        className="history-nav-btn"
        onClick={() => { setVoiceView("history"); loadHistory(); }}
      >
        <span>Voice History</span>
        {history.length > 0 && <span className="history-count">{history.length}</span>}
      </button>

      <button
        className="history-nav-btn"
        onClick={() => { setVoiceView("words"); loadWordReplacements(); }}
      >
        <span>Word Dictionary</span>
        {wordReplacements.length > 0 && <span className="history-count">{wordReplacements.length}</span>}
      </button>

      {error && <div className="error">{error}</div>}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "refactor(gui): extract voice section component"
```

---

## Task 14: Add Placeholder Sections for Memory and Config

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Add placeholder render functions**

```typescript
function renderMemorySection() {
  return (
    <div className="empty-state" style={{ marginTop: "4rem" }}>
      <p style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>Memory</p>
      <p>Coming soon - manage bugs, patterns, gotchas, and stack knowledge</p>
    </div>
  );
}

function renderConfigSection() {
  return (
    <div className="empty-state" style={{ marginTop: "4rem" }}>
      <p style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>Config</p>
      <p>Coming soon - agents, commands, plugins, hooks, settings</p>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add placeholder memory and config sections"
```

---

## Task 15: Update Main Return Statement

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx`

**Step 1: Replace all the conditional returns with new layout**

Remove all the existing `if (currentView === ...)` blocks and the final return. Replace with:

```typescript
return (
  <div className="app-layout">
    {renderSidebar()}
    <main className="main-content">
      {currentSection === "worktrees" && renderWorktreesSection()}
      {currentSection === "voice" && renderVoiceSection()}
      {currentSection === "memory" && renderMemorySection()}
      {currentSection === "config" && renderConfigSection()}
    </main>
  </div>
);
```

**Step 2: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): implement new layout with sidebar and sections"
```

---

## Task 16: Update Window Size in Tauri Config

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src-tauri/tauri.conf.json`

**Step 1: Update main window dimensions**

Change the main window size to accommodate the sidebar:

```json
{
  "label": "main",
  "title": "Synthia",
  "width": 800,
  "height": 600,
  "minWidth": 600,
  "minHeight": 400,
  "resizable": true,
  "center": true
}
```

**Step 2: Commit**

```bash
git add gui/src-tauri/tauri.conf.json
git commit -m "config(gui): increase window size for sidebar layout"
```

---

## Task 17: Add Voice Section CSS Class

**Files:**
- Modify: `/home/markmiddo/dev/misc/synthia/gui/src/App.css`

**Step 1: Add voice section wrapper styles**

```css
.voice-section {
  max-width: 500px;
}

.voice-section .header {
  background: transparent;
  padding: 0 0 1rem 0;
}

.voice-section .content {
  padding: 0;
}
```

**Step 2: Commit**

```bash
git add gui/src/App.css
git commit -m "style(gui): add voice section wrapper styles"
```

---

## Task 18: Test and Verify

**Step 1: Build the Rust backend**

```bash
cd /home/markmiddo/dev/misc/synthia/gui && cargo build --manifest-path src-tauri/Cargo.toml
```

Expected: Build succeeds

**Step 2: Run the app in dev mode**

```bash
cd /home/markmiddo/dev/misc/synthia/gui && npm run tauri dev
```

Expected: App opens with sidebar, worktrees section shows configured repos with tasks

**Step 3: Verify worktrees show tasks**

Click on a worktree that has active Claude Code tasks. Verify tasks appear in the side panel.

**Step 4: Verify resume works**

Click "Resume" button. Verify WezTerm opens a new pane with Claude session.

**Step 5: Verify voice section works**

Click "Voice" in sidebar. Verify start/stop, remote mode, hotkeys, history, and dictionary all work.

**Step 6: Final commit**

```bash
git add -A
git commit -m "feat(gui): complete GUI consolidation - worktrees with tasks, voice section"
```

---

## Cleanup Task: Remove Old View Code

After verifying everything works, remove the unused `currentView` state, clipboard/inbox state and functions, and related dead code.

**Files to clean:**
- `/home/markmiddo/dev/misc/synthia/gui/src/App.tsx` - Remove clipboard/inbox code
- `/home/markmiddo/dev/misc/synthia/gui/src/App.css` - Remove unused clipboard/inbox styles

```bash
git commit -m "chore(gui): remove deprecated clipboard and inbox code"
```
