# GitHub Issues Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a read-only GitHub Issues section to Synthia's GUI that shows issues assigned to the user across configured repos, using the `gh` CLI for data fetching.

**Architecture:** Rust Tauri commands shell out to `gh issue list --json` for each configured repo, cache results in `~/.config/synthia/github-issues-cache.json`, and serve them to a new React "GitHub" section. Config stored in `~/.config/synthia/github.json`.

**Tech Stack:** Rust (Tauri commands, serde, std::process::Command), React/TypeScript (frontend), `gh` CLI (GitHub data)

**Design Doc:** `docs/plans/2026-02-24-github-issues-integration-design.md`

---

### Task 1: Add Rust structs and config commands

**Files:**
- Modify: `gui/src-tauri/src/lib.rs` (add structs after line 210, add commands, register in handler)

**Step 1: Add struct definitions after the existing `WorktreeInfo` struct (after line 210)**

```rust
// GitHub Issues types
#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubLabel {
    name: String,
    color: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubIssue {
    number: u32,
    title: String,
    state: String,
    labels: Vec<GitHubLabel>,
    assignees: Vec<GitHubAssignee>,
    #[serde(rename = "createdAt")]
    created_at: String,
    #[serde(rename = "updatedAt")]
    updated_at: String,
    url: String,
    body: String,
    milestone: Option<GitHubMilestone>,
    comments: Vec<serde_json::Value>,
    repository: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubAssignee {
    login: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubMilestone {
    title: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubConfig {
    repos: Vec<String>,
    refresh_interval_seconds: u64,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubIssuesCache {
    fetched_at: String,
    issues: Vec<GitHubIssue>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct GitHubIssuesResponse {
    issues: Vec<GitHubIssue>,
    fetched_at: String,
    error: Option<String>,
}
```

Note: `gh` returns `assignees` as `[{login: "user"}]`, `milestone` as `{title: "v2.3"}` or null, and `comments` as an array. The serde renames match `gh`'s camelCase JSON output.

**Step 2: Add `get_github_config` command**

Add before the `invoke_handler!` block (before line 2549):

```rust
fn get_github_config_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("github.json")
}

fn get_github_cache_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("github-issues-cache.json")
}

#[tauri::command]
fn get_github_config() -> GitHubConfig {
    let path = get_github_config_path();
    if let Ok(content) = fs::read_to_string(&path) {
        if let Ok(config) = serde_json::from_str::<GitHubConfig>(&content) {
            return config;
        }
    }
    GitHubConfig {
        repos: Vec::new(),
        refresh_interval_seconds: 300,
    }
}

#[tauri::command]
fn save_github_config(repos: Vec<String>, refresh_interval_seconds: u64) -> Result<String, String> {
    let config = GitHubConfig {
        repos,
        refresh_interval_seconds,
    };
    let path = get_github_config_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Failed to create config dir: {}", e))?;
    }
    let json = serde_json::to_string_pretty(&config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;
    fs::write(&path, json).map_err(|e| format!("Failed to write config: {}", e))?;
    Ok("saved".to_string())
}
```

**Step 3: Register the new commands in invoke_handler (line 2604)**

Add after `move_task` in the handler list:

```rust
            move_task,
            get_github_config,
            save_github_config
```

**Step 4: Build to verify compilation**

Run: `cd gui && cargo build 2>&1 | tail -5`
Expected: Compiles successfully

**Step 5: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add GitHub config structs and commands"
```

---

### Task 2: Add `get_github_issues` Rust command

**Files:**
- Modify: `gui/src-tauri/src/lib.rs` (add command after `save_github_config`, register in handler)

**Step 1: Add the `get_github_issues` command**

Add after the `save_github_config` function:

```rust
#[tauri::command]
fn get_github_issues(force_refresh: bool) -> GitHubIssuesResponse {
    let config = get_github_config();

    if config.repos.is_empty() {
        return GitHubIssuesResponse {
            issues: Vec::new(),
            fetched_at: String::new(),
            error: None,
        };
    }

    // Check cache freshness
    let cache_path = get_github_cache_path();
    if !force_refresh {
        if let Ok(content) = fs::read_to_string(&cache_path) {
            if let Ok(cache) = serde_json::from_str::<GitHubIssuesCache>(&content) {
                // Parse fetched_at and check if within refresh interval
                if let Ok(fetched) = chrono::DateTime::parse_from_rfc3339(&cache.fetched_at) {
                    let age = chrono::Utc::now().signed_duration_since(fetched);
                    if age.num_seconds() < config.refresh_interval_seconds as i64 {
                        return GitHubIssuesResponse {
                            issues: cache.issues,
                            fetched_at: cache.fetched_at,
                            error: None,
                        };
                    }
                }
            }
        }
    }

    // Check if gh is installed
    if Command::new("gh").arg("--version").output().is_err() {
        return GitHubIssuesResponse {
            issues: Vec::new(),
            fetched_at: String::new(),
            error: Some("GitHub CLI (gh) is not installed. Install it from https://cli.github.com/".to_string()),
        };
    }

    // Fetch issues from each repo
    let mut all_issues: Vec<GitHubIssue> = Vec::new();
    let mut errors: Vec<String> = Vec::new();

    for repo in &config.repos {
        match Command::new("gh")
            .args([
                "issue", "list",
                "--assignee", "@me",
                "--repo", repo,
                "--json", "number,title,state,labels,assignees,createdAt,updatedAt,url,body,milestone,comments",
                "--state", "all",
                "--limit", "100",
            ])
            .output()
        {
            Ok(output) => {
                if output.status.success() {
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    match serde_json::from_str::<Vec<GitHubIssue>>(&stdout) {
                        Ok(mut issues) => {
                            for issue in &mut issues {
                                issue.repository = Some(repo.clone());
                            }
                            all_issues.extend(issues);
                        }
                        Err(e) => {
                            errors.push(format!("{}: parse error: {}", repo, e));
                        }
                    }
                } else {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    errors.push(format!("{}: {}", repo, stderr.trim()));
                }
            }
            Err(e) => {
                errors.push(format!("{}: {}", repo, e));
            }
        }
    }

    // Sort by updated_at descending (most recently updated first)
    all_issues.sort_by(|a, b| b.updated_at.cmp(&a.updated_at));

    let fetched_at = chrono::Utc::now().to_rfc3339();

    // Write cache
    let cache = GitHubIssuesCache {
        fetched_at: fetched_at.clone(),
        issues: all_issues.clone(),
    };
    if let Ok(json) = serde_json::to_string_pretty(&cache) {
        let _ = fs::write(&cache_path, json);
    }

    GitHubIssuesResponse {
        issues: all_issues,
        fetched_at,
        error: if errors.is_empty() { None } else { Some(errors.join("; ")) },
    }
}
```

**Step 2: Register in invoke_handler**

Add `get_github_issues` to the handler list:

```rust
            save_github_config,
            get_github_issues
```

**Step 3: Build to verify**

Run: `cd gui && cargo build 2>&1 | tail -5`
Expected: Compiles successfully

**Step 4: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): add get_github_issues command with caching"
```

---

### Task 3: Add TypeScript interfaces and state to App.tsx

**Files:**
- Modify: `gui/src/App.tsx`

**Step 1: Add TypeScript interfaces after `WorktreeInfo` (after line 280)**

```typescript
interface GitHubLabel {
  name: string;
  color: string;
}

interface GitHubAssignee {
  login: string;
}

interface GitHubMilestone {
  title: string;
}

interface GitHubIssue {
  number: number;
  title: string;
  state: string;
  labels: GitHubLabel[];
  assignees: GitHubAssignee[];
  createdAt: string;
  updatedAt: string;
  url: string;
  body: string;
  milestone: GitHubMilestone | null;
  comments: unknown[];
  repository: string | null;
}

interface GitHubConfig {
  repos: string[];
  refresh_interval_seconds: number;
}

interface GitHubIssuesResponse {
  issues: GitHubIssue[];
  fetched_at: string;
  error: string | null;
}
```

Note: Frontend uses camelCase field names because Tauri's serde serialization converts the Rust `#[serde(rename = "...")]` fields. The `comments` field from `gh` is an array of objects but we only need the count, so use `unknown[]` and read `.length`.

**Step 2: Update the `Section` type (line 284)**

Change from:
```typescript
type Section = "worktrees" | "notes" | "tasks" | "voice" | "memory" | "config";
```
To:
```typescript
type Section = "worktrees" | "notes" | "tasks" | "voice" | "memory" | "config" | "github";
```

**Step 3: Add GitHub state variables after the Notes state block (after line 359)**

```typescript
  // GitHub state
  const [githubIssues, setGithubIssues] = useState<GitHubIssue[]>([]);
  const [githubConfig, setGithubConfig] = useState<GitHubConfig>({ repos: [], refresh_interval_seconds: 300 });
  const [githubFetchedAt, setGithubFetchedAt] = useState<string>("");
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubLoading, setGithubLoading] = useState(false);
  const [selectedIssue, setSelectedIssue] = useState<GitHubIssue | null>(null);
  const [githubRepoFilter, setGithubRepoFilter] = useState<string>("all");
  const [githubStateFilter, setGithubStateFilter] = useState<string>("open");
  const [githubConfigOpen, setGithubConfigOpen] = useState(false);
  const [newGithubRepo, setNewGithubRepo] = useState("");
```

**Step 4: Add data loading functions after `loadWorktrees()` (after line 473)**

```typescript
  async function loadGithubConfig() {
    try {
      const result = await invoke<GitHubConfig>("get_github_config");
      setGithubConfig(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadGithubIssues(forceRefresh = false) {
    setGithubLoading(true);
    try {
      const result = await invoke<GitHubIssuesResponse>("get_github_issues", {
        forceRefresh,
      });
      setGithubIssues(result.issues);
      setGithubFetchedAt(result.fetched_at);
      setGithubError(result.error);
    } catch (e) {
      setGithubError(String(e));
    } finally {
      setGithubLoading(false);
    }
  }

  async function saveGithubConfig(repos: string[], refreshInterval: number) {
    try {
      await invoke("save_github_config", {
        repos,
        refreshIntervalSeconds: refreshInterval,
      });
      setGithubConfig({ repos, refresh_interval_seconds: refreshInterval });
    } catch (e) {
      setGithubError(String(e));
    }
  }
```

**Step 5: Add GitHub section loading to useEffect (around line 444)**

Add after the `if (currentSection === "tasks")` block:

```typescript
    if (currentSection === "github") {
      loadGithubConfig();
      loadGithubIssues();
    }
```

Also add to the interval block (around line 451):

```typescript
      if (currentSection === "github") loadGithubIssues();
```

**Step 6: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add GitHub issues TypeScript types and state"
```

---

### Task 4: Add GitHub navigation item

**Files:**
- Modify: `gui/src/App.tsx` (nav section around line 1145)

**Step 1: Add GitHub nav button after the Worktrees button (after line 1146)**

Insert after the Worktrees `</button>` closing tag (line 1146):

```tsx
          <button
            className={`nav-item ${currentSection === "github" ? "active" : ""}`}
            onClick={() => setCurrentSection("github")}
          >
            <span className="nav-item-icon">&#128025;</span>
            GitHub
            {githubIssues.filter(i => i.state === "OPEN").length > 0 && (
              <span className="nav-badge">{githubIssues.filter(i => i.state === "OPEN").length}</span>
            )}
          </button>
```

Note: The `&#128025;` is the octocat-like emoji. GitHub `gh` returns state as "OPEN"/"CLOSED" in uppercase.

**Step 2: Add the section render call (around line 2751)**

Add after the worktrees render line:

```tsx
        {currentSection === "github" && renderGithubSection()}
```

**Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): add GitHub nav item and section mount point"
```

---

### Task 5: Implement `renderGithubSection()` - issue list

**Files:**
- Modify: `gui/src/App.tsx` (add before `renderVoiceSection()`, around line 1404)

**Step 1: Add the render function**

Insert before `function renderVoiceSection()`:

```tsx
  function renderGithubSection() {
    function timeAgo(dateStr: string): string {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      const diffDays = Math.floor(diffHours / 24);
      if (diffDays < 30) return `${diffDays}d ago`;
      return date.toLocaleDateString();
    }

    function getRepoColorClass(repo: string): string {
      let hash = 0;
      for (let i = 0; i < repo.length; i++) {
        hash = repo.charCodeAt(i) + ((hash << 5) - hash);
      }
      return `repo-${Math.abs(hash) % 8}`;
    }

    const filteredIssues = githubIssues.filter(issue => {
      if (githubRepoFilter !== "all" && issue.repository !== githubRepoFilter) return false;
      if (githubStateFilter === "open" && issue.state !== "OPEN") return false;
      if (githubStateFilter === "closed" && issue.state !== "CLOSED") return false;
      return true;
    });

    const repos = [...new Set(githubIssues.map(i => i.repository).filter(Boolean))] as string[];
    const groupedByRepo = repos
      .filter(r => githubRepoFilter === "all" || r === githubRepoFilter)
      .map(repo => ({
        repo,
        issues: filteredIssues.filter(i => i.repository === repo),
      }))
      .filter(g => g.issues.length > 0);

    return (
      <div className="github-layout">
        <div className="github-list">
          {/* Header */}
          <div className="github-header">
            <div className="github-title-row">
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>GitHub Issues</h2>
              <div className="github-header-actions">
                <span className="github-count">{filteredIssues.length} issues</span>
                <button
                  className="github-refresh-btn"
                  onClick={() => loadGithubIssues(true)}
                  disabled={githubLoading}
                  title="Refresh issues"
                >
                  {githubLoading ? "⟳" : "↻"}
                </button>
                <button
                  className="github-config-btn"
                  onClick={() => setGithubConfigOpen(true)}
                  title="Configure repos"
                >
                  ⚙
                </button>
              </div>
            </div>
            {githubFetchedAt && (
              <div className="github-fetched">Updated {timeAgo(githubFetchedAt)}</div>
            )}
            {githubError && (
              <div className="github-error">{githubError}</div>
            )}

            {/* Filters */}
            <div className="github-filters">
              <select
                className="github-filter-select"
                value={githubRepoFilter}
                onChange={(e) => setGithubRepoFilter(e.target.value)}
              >
                <option value="all">All repos</option>
                {repos.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <div className="github-state-toggle">
                <button
                  className={`github-state-btn ${githubStateFilter === "open" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("open")}
                >
                  Open
                </button>
                <button
                  className={`github-state-btn ${githubStateFilter === "closed" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("closed")}
                >
                  Closed
                </button>
                <button
                  className={`github-state-btn ${githubStateFilter === "all" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("all")}
                >
                  All
                </button>
              </div>
            </div>
          </div>

          {/* Empty states */}
          {githubConfig.repos.length === 0 ? (
            <div className="empty-state">
              <p>No repos configured</p>
              <p style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                Click ⚙ to add GitHub repos to track
              </p>
            </div>
          ) : filteredIssues.length === 0 && !githubLoading ? (
            <div className="empty-state">
              <p>No issues assigned to you</p>
            </div>
          ) : (
            /* Issue list grouped by repo */
            groupedByRepo.map(({ repo, issues }) => (
              <div key={repo} className="github-repo-group">
                <div className="github-repo-header">
                  <span className={`worktree-repo ${getRepoColorClass(repo)}`}>
                    {repo}
                  </span>
                  <span className="github-repo-count">{issues.length}</span>
                </div>
                {issues.map(issue => (
                  <div
                    key={`${issue.repository}-${issue.number}`}
                    className={`github-issue-item ${selectedIssue?.number === issue.number && selectedIssue?.repository === issue.repository ? "selected" : ""}`}
                    onClick={() => setSelectedIssue(
                      selectedIssue?.number === issue.number && selectedIssue?.repository === issue.repository ? null : issue
                    )}
                  >
                    <div className="github-issue-header">
                      <span className={`github-issue-number ${issue.state === "OPEN" ? "open" : "closed"}`}>
                        #{issue.number}
                      </span>
                      <span className="github-issue-title">{issue.title}</span>
                    </div>
                    <div className="github-issue-meta">
                      {issue.labels.map(label => (
                        <span
                          key={label.name}
                          className="github-label"
                          style={{
                            backgroundColor: `#${label.color}33`,
                            color: `#${label.color}`,
                            border: `1px solid #${label.color}66`,
                          }}
                        >
                          {label.name}
                        </span>
                      ))}
                      {issue.milestone && (
                        <span className="github-milestone">🎯 {issue.milestone.title}</span>
                      )}
                      <span className="github-time">{timeAgo(issue.updatedAt)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        {/* Detail panel */}
        {selectedIssue && (
          <div className="task-panel" style={{ minWidth: "350px" }}>
            <div className="task-panel-header">
              <span className="task-panel-title">#{selectedIssue.number}</span>
              <button
                className="task-panel-btn primary"
                onClick={() => {
                  if (selectedIssue.url) {
                    window.open(selectedIssue.url, "_blank");
                  }
                }}
              >
                Open in GitHub
              </button>
            </div>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem", fontWeight: 500 }}>
              {selectedIssue.title}
            </h3>
            <div className="github-detail-meta">
              <span className={`github-state-badge ${selectedIssue.state === "OPEN" ? "open" : "closed"}`}>
                {selectedIssue.state === "OPEN" ? "● Open" : "● Closed"}
              </span>
              {selectedIssue.assignees.map(a => (
                <span key={a.login} className="github-assignee">@{a.login}</span>
              ))}
              <span className="github-comments">{selectedIssue.comments.length} comments</span>
            </div>
            {selectedIssue.labels.length > 0 && (
              <div className="github-detail-labels">
                {selectedIssue.labels.map(label => (
                  <span
                    key={label.name}
                    className="github-label"
                    style={{
                      backgroundColor: `#${label.color}33`,
                      color: `#${label.color}`,
                      border: `1px solid #${label.color}66`,
                    }}
                  >
                    {label.name}
                  </span>
                ))}
              </div>
            )}
            {selectedIssue.body && (
              <div className="github-issue-body">
                <pre style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: "0.85rem",
                  lineHeight: 1.5,
                  color: "#e2e8f0",
                  margin: 0,
                  fontFamily: "inherit",
                }}>
                  {selectedIssue.body}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Config modal */}
        {githubConfigOpen && (
          <div className="modal-overlay" onClick={() => setGithubConfigOpen(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <h3 style={{ margin: "0 0 1rem" }}>GitHub Repos</h3>
              <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
                <input
                  className="github-repo-input"
                  type="text"
                  placeholder="owner/repo"
                  value={newGithubRepo}
                  onChange={(e) => setNewGithubRepo(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newGithubRepo.includes("/")) {
                      const updated = [...githubConfig.repos, newGithubRepo.trim()];
                      saveGithubConfig(updated, githubConfig.refresh_interval_seconds);
                      setNewGithubRepo("");
                    }
                  }}
                />
                <button
                  className="task-panel-btn primary"
                  onClick={() => {
                    if (newGithubRepo.includes("/")) {
                      const updated = [...githubConfig.repos, newGithubRepo.trim()];
                      saveGithubConfig(updated, githubConfig.refresh_interval_seconds);
                      setNewGithubRepo("");
                    }
                  }}
                >
                  Add
                </button>
              </div>
              <div className="github-repo-list">
                {githubConfig.repos.map((repo, i) => (
                  <div key={repo} className="github-repo-list-item">
                    <span>{repo}</span>
                    <button
                      className="github-repo-remove"
                      onClick={() => {
                        const updated = githubConfig.repos.filter((_, idx) => idx !== i);
                        saveGithubConfig(updated, githubConfig.refresh_interval_seconds);
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <button
                className="task-panel-btn"
                style={{ marginTop: "1rem" }}
                onClick={() => {
                  setGithubConfigOpen(false);
                  loadGithubIssues(true);
                }}
              >
                Done
              </button>
            </div>
          </div>
        )}
      </div>
    );
  }
```

**Step 2: Verify no TypeScript errors**

Run: `cd gui && npx tsc --noEmit 2>&1 | tail -10`
Expected: No errors (or only pre-existing ones)

**Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): implement GitHub issues section with list, detail panel, and config modal"
```

---

### Task 6: Add CSS styles for GitHub section

**Files:**
- Modify: `gui/src/App.css` (add at end of file)

**Step 1: Add GitHub section styles**

Append to end of `App.css`:

```css
/* ==================== GitHub Section ==================== */

.github-layout {
  display: flex;
  gap: 1rem;
  height: 100%;
  overflow: hidden;
}

.github-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.github-header {
  padding: 0.75rem 0;
  border-bottom: 1px solid rgba(6, 182, 212, 0.1);
  margin-bottom: 0.5rem;
}

.github-title-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.github-header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.github-count {
  font-size: 0.8rem;
  color: #94a3b8;
}

.github-refresh-btn,
.github-config-btn {
  background: rgba(6, 182, 212, 0.1);
  border: 1px solid rgba(6, 182, 212, 0.2);
  color: #94a3b8;
  border-radius: 4px;
  padding: 0.25rem 0.5rem;
  cursor: pointer;
  font-size: 1rem;
  transition: all 0.15s ease;
}

.github-refresh-btn:hover,
.github-config-btn:hover {
  background: rgba(6, 182, 212, 0.2);
  color: #06b6d4;
}

.github-refresh-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.github-fetched {
  font-size: 0.75rem;
  color: #64748b;
  margin-top: 0.25rem;
}

.github-error {
  font-size: 0.8rem;
  color: #f87171;
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: rgba(248, 113, 113, 0.1);
  border-radius: 4px;
}

.github-filters {
  display: flex;
  gap: 0.5rem;
  margin-top: 0.75rem;
  align-items: center;
}

.github-filter-select {
  background: rgba(6, 182, 212, 0.05);
  border: 1px solid rgba(6, 182, 212, 0.15);
  color: #e2e8f0;
  border-radius: 4px;
  padding: 0.3rem 0.5rem;
  font-size: 0.8rem;
  cursor: pointer;
}

.github-filter-select option {
  background: #0a0b14;
  color: #e2e8f0;
}

.github-state-toggle {
  display: flex;
  border: 1px solid rgba(6, 182, 212, 0.15);
  border-radius: 4px;
  overflow: hidden;
}

.github-state-btn {
  background: transparent;
  border: none;
  color: #94a3b8;
  padding: 0.3rem 0.6rem;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s ease;
}

.github-state-btn:not(:last-child) {
  border-right: 1px solid rgba(6, 182, 212, 0.15);
}

.github-state-btn.active {
  background: rgba(6, 182, 212, 0.15);
  color: #06b6d4;
}

.github-state-btn:hover:not(.active) {
  background: rgba(6, 182, 212, 0.08);
}

/* Repo groups */
.github-repo-group {
  margin-bottom: 0.5rem;
}

.github-repo-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
}

.github-repo-count {
  font-size: 0.75rem;
  color: #64748b;
}

/* Issue items */
.github-issue-item {
  padding: 0.75rem 1rem;
  background: rgba(6, 182, 212, 0.03);
  border: 1px solid rgba(6, 182, 212, 0.08);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s ease;
  margin-bottom: 0.375rem;
}

.github-issue-item:hover {
  background: rgba(6, 182, 212, 0.08);
  border-color: rgba(6, 182, 212, 0.15);
}

.github-issue-item.selected {
  background: rgba(6, 182, 212, 0.12);
  border-color: #06b6d4;
}

.github-issue-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  margin-bottom: 0.375rem;
}

.github-issue-number {
  font-size: 0.8rem;
  font-weight: 600;
  font-family: monospace;
}

.github-issue-number.open {
  color: #22c55e;
}

.github-issue-number.closed {
  color: #a78bfa;
}

.github-issue-title {
  font-size: 0.9rem;
  color: #e2e8f0;
  font-weight: 500;
}

.github-issue-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  align-items: center;
}

.github-label {
  font-size: 0.7rem;
  padding: 0.1rem 0.4rem;
  border-radius: 10px;
  font-weight: 500;
}

.github-milestone {
  font-size: 0.75rem;
  color: #94a3b8;
}

.github-time {
  font-size: 0.7rem;
  color: #64748b;
  margin-left: auto;
}

/* Detail panel additions */
.github-detail-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  align-items: center;
  margin-bottom: 0.75rem;
}

.github-state-badge {
  font-size: 0.8rem;
  padding: 0.2rem 0.5rem;
  border-radius: 12px;
  font-weight: 500;
}

.github-state-badge.open {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}

.github-state-badge.closed {
  background: rgba(167, 139, 250, 0.15);
  color: #a78bfa;
}

.github-assignee {
  font-size: 0.8rem;
  color: #94a3b8;
}

.github-comments {
  font-size: 0.8rem;
  color: #64748b;
}

.github-detail-labels {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.75rem;
}

.github-issue-body {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(6, 182, 212, 0.1);
  max-height: 400px;
  overflow-y: auto;
}

/* Nav badge */
.nav-badge {
  background: rgba(6, 182, 212, 0.3);
  color: #06b6d4;
  font-size: 0.65rem;
  padding: 0.1rem 0.35rem;
  border-radius: 8px;
  margin-left: 0.375rem;
  font-weight: 600;
}

/* Config modal */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.modal-content {
  background: #0f1019;
  border: 1px solid rgba(6, 182, 212, 0.2);
  border-radius: 12px;
  padding: 1.5rem;
  min-width: 400px;
  max-width: 500px;
}

.github-repo-input {
  flex: 1;
  background: rgba(6, 182, 212, 0.05);
  border: 1px solid rgba(6, 182, 212, 0.15);
  color: #e2e8f0;
  border-radius: 4px;
  padding: 0.4rem 0.6rem;
  font-size: 0.85rem;
}

.github-repo-input::placeholder {
  color: #64748b;
}

.github-repo-list {
  display: flex;
  flex-direction: column;
  gap: 0.375rem;
}

.github-repo-list-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.5rem 0.75rem;
  background: rgba(6, 182, 212, 0.05);
  border: 1px solid rgba(6, 182, 212, 0.1);
  border-radius: 4px;
  font-size: 0.85rem;
  color: #e2e8f0;
}

.github-repo-remove {
  background: none;
  border: none;
  color: #f87171;
  cursor: pointer;
  font-size: 0.9rem;
  padding: 0 0.25rem;
  opacity: 0.6;
  transition: opacity 0.15s ease;
}

.github-repo-remove:hover {
  opacity: 1;
}
```

**Step 2: Verify the app builds and renders**

Run: `cd gui && npm run build 2>&1 | tail -5`
Expected: Build succeeds

**Step 3: Commit**

```bash
git add gui/src/App.css
git commit -m "style(gui): add GitHub issues section styles"
```

---

### Task 7: Build, test, and verify end-to-end

**Files:** None (testing only)

**Step 1: Build the full Tauri app**

Run: `cd gui && cargo build 2>&1 | tail -10`
Expected: Compiles successfully

**Step 2: Run TypeScript check**

Run: `cd gui && npx tsc --noEmit 2>&1 | tail -10`
Expected: No new errors

**Step 3: Test `gh` CLI works for configured repo**

Run: `gh issue list --assignee @me --repo markmiddo/eventflo-fan-experience --json number,title,state,labels --limit 3`
Expected: JSON output with issues (or empty array)

**Step 4: Build deb package and test**

Run: `cd gui && cargo tauri build --bundles deb 2>&1 | tail -5`
Then install: `sudo dpkg -i gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb`

**Step 5: Launch and verify**

1. Kill any existing Synthia GUI process
2. Launch `synthia-gui`
3. Click GitHub in nav - should show empty state with gear icon
4. Click gear, add a repo (e.g., `markmiddo/eventflo-fan-experience`)
5. Issues should load and display grouped by repo
6. Click an issue to see detail panel
7. Click "Open in GitHub" to verify it opens browser
8. Test filter by repo and open/closed toggle

**Step 6: Final commit if any fixes needed**

```bash
git add -A
git commit -m "fix(gui): address issues found during testing"
```
