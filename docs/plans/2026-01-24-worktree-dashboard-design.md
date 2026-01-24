# Worktree Dashboard Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a Worktrees section to Synthia TUI that displays active git worktrees with linked GitHub issues and Claude Code task progress, enabling quick context switching during development.

**Architecture:** New Section.WORKTREES in the dashboard that aggregates data from git worktree list, Claude Code session/task storage, and GitHub CLI. Provides actions to resume sessions, open terminals, and view issues.

**Tech Stack:** Python, Textual TUI framework, git CLI, gh CLI

---

## Problem Statement

Mid-session context switching causes loss of track on complex dev tasks across multiple worktrees. GitHub Projects shows WHAT to work on strategically, but doesn't show WHERE you are tactically in each piece of work. This panel provides real-time visibility into worktree state and Claude Code task progress.

---

## Data Architecture

### Data Sources

| Source | Data | Path |
|--------|------|------|
| Git worktrees | Paths, branches, HEAD commits | `git worktree list --porcelain` |
| Session index | projectPath, summary, gitBranch, timestamps | `~/.claude/projects/*/sessions-index.json` |
| Tasks | content, status, activeForm | `~/.claude/todos/{sessionId}-agent-*.json` |
| GitHub | Issue titles | `gh issue view {num} --json title` (cached) |

### Session-Worktree Linking

Each session entry has `projectPath` which matches worktree paths. Each worktree gets its own project directory in `~/.claude/projects/`.

---

## UI Design

### Dashboard Integration

```
┌─────────────────────────────────────────────────────────────────────┐
│                         WORKTREE DASHBOARD                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─ Worktrees ─────────────────────────────────────────────────┐   │
│  │                                                              │   │
│  │  📁 .worktrees/issue-295-manage-order-mobile                │   │
│  │     Branch: feature/295-flosale-mobile                      │   │
│  │     Issue: #295 FloSale Manage Order Mobile                 │   │
│  │     Session: "FloSale manage order mobile redesign"         │   │
│  │     Tasks: ████████░░ 4/5 completed                         │   │
│  │                                                              │   │
│  │  📁 .worktrees/issue-301-promoter-codes                     │   │
│  │     Branch: feature/301-promoter-codes                      │   │
│  │     Issue: #301 Promoter Tracking                           │   │
│  │     Session: "Promoter codes backend implementation"        │   │
│  │     Tasks: ██░░░░░░░░ 1/5 completed                         │   │
│  │                                                              │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Display Modes

**Collapsed:**
```
📁 issue-295-manage-order-mobile  ████████░░ 4/5  #295
```

**Expanded:**
```
📁 issue-295-manage-order-mobile
   Branch: feature/295-flosale-mobile
   Issue: #295 FloSale Manage Order Mobile
   Session: "FloSale manage order mobile redesign"
   Tasks: ████████░░ 4/5 completed
     ✓ Create ManageOrderForm component
     ✓ Add mobile responsive styles
     ✓ Implement ticket selection
     ✓ Add quantity controls
     ○ Final testing and cleanup
```

---

## Keyboard Navigation

| Key | Action |
|-----|--------|
| `w` | Jump to Worktrees section |
| `↑/↓` | Navigate worktree list |
| `Enter` | Expand/collapse worktree details |
| `r` | Resume Claude session in worktree |
| `o` | Open terminal at worktree path |
| `g` | Open GitHub issue in browser |
| `d` | Delete worktree (with confirmation) |
| `R` | Manual refresh |

### Resume Action

When pressing `r` on a worktree:
1. `cd` to that worktree path
2. Run `claude --continue` to resume the last session there

---

## Data Model

```python
# src/synthia/worktrees.py

@dataclass
class WorktreeTask:
    content: str
    status: str  # "pending", "in_progress", "completed"
    active_form: str

@dataclass
class WorktreeInfo:
    path: str
    branch: str
    issue_number: int | None
    issue_title: str | None
    session_id: str | None
    session_summary: str | None
    tasks: list[WorktreeTask]

    @property
    def progress(self) -> tuple[int, int]:
        completed = sum(1 for t in self.tasks if t.status == "completed")
        return (completed, len(self.tasks))
```

---

## Data Fetching

### Scan Flow

```
1. git worktree list --porcelain
   ↓
2. For each worktree path:
   ├── Extract issue # from branch name (regex)
   ├── Find session in ~/.claude/projects/*/sessions-index.json
   │   where projectPath == worktree path
   ├── Load tasks from ~/.claude/todos/{sessionId}-*.json
   └── Cache issue title from gh (expires after 5 min)
   ↓
3. Return List[WorktreeInfo]
```

### Refresh Strategy

- Auto-refresh on section focus
- Manual refresh with `R` key
- Background refresh every 60 seconds while visible

---

## Edge Cases

| Scenario | Display |
|----------|---------|
| No branch → issue mapping | Show branch name only, no issue link |
| No Claude session found | "No active session" (dimmed) |
| Empty task list | "No tasks tracked" |
| GitHub API unavailable | Use cached title or show "#295" only |
| Worktree path deleted | Show ⚠️ indicator, offer cleanup |

### Branch → Issue Regex Patterns

```python
ISSUE_PATTERNS = [
    r"feature/(\d+)-",      # feature/295-flosale-mobile
    r"issue-(\d+)-",        # issue-295-manage-order
    r"fix/(\d+)-",          # fix/301-bug-name
    r"(\d+)-",              # 295-flosale-mobile
]
```

### Stale Detection

- If session `modified` > 24 hours ago → show "stale" indicator
- If worktree has uncommitted changes → show "modified" badge

---

## Synthia Integration

### New Section

```python
class Section(Enum):
    MEMORY = "memory"
    AGENTS = "agents"
    COMMANDS = "commands"
    PLUGINS = "plugins"
    HOOKS = "hooks"
    SETTINGS = "settings"
    WORKTREES = "worktrees"  # ← New section
```

---

## Implementation Summary

| Component | Implementation |
|-----------|----------------|
| New section | `Section.WORKTREES` in dashboard.py |
| Data model | `WorktreeInfo` dataclass in worktrees.py |
| Data sources | git, ~/.claude/projects, ~/.claude/todos, gh CLI |
| Key actions | Resume (r), Open (o), GitHub (g), Delete (d) |
| Refresh | On focus + manual (R) + 60s background |
