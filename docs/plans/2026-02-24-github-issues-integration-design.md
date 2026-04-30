# GitHub Issues Integration Design

**Date:** 2026-02-24
**Status:** Approved

## Goal

Add a GitHub Issues section to Synthia's GUI so the user can see all issues assigned to them across configured repos - turning Synthia into a personal command center.

## Decisions

- **Scope:** Read-only view of assigned issues from user-configured repos
- **Auth:** Use `gh` CLI (already authenticated on machine)
- **Architecture:** Rust shells out to `gh`, caches results in JSON
- **Placement:** New "GitHub" nav section after Worktrees

## Data Model

### Config: `~/.config/synthia/github.json`

```json
{
  "repos": ["owner/repo-name", "owner/other-repo"],
  "refresh_interval_seconds": 300
}
```

### Cache: `~/.config/synthia/github-issues-cache.json`

```json
{
  "fetched_at": "2026-02-24T10:30:00Z",
  "issues": [
    {
      "number": 42,
      "title": "Fix checkout flow",
      "state": "open",
      "labels": [{"name": "bug", "color": "d73a4a"}],
      "assignees": ["markmiddo"],
      "created_at": "2026-02-20T08:00:00Z",
      "updated_at": "2026-02-23T14:00:00Z",
      "url": "https://github.com/owner/repo/issues/42",
      "body": "Description text...",
      "milestone": "v2.3",
      "comments": 5,
      "repository": "owner/repo"
    }
  ]
}
```

## Tauri Commands (Rust)

### `get_github_config() -> GitHubConfig`
Reads `~/.config/synthia/github.json`. Returns default config if file doesn't exist.

### `save_github_config(repos: Vec<String>, refresh_interval: u64)`
Writes config file. Validates repo format (`owner/repo`).

### `get_github_issues(force_refresh: bool) -> GitHubIssuesResponse`
1. Check cache freshness against `refresh_interval_seconds`
2. If fresh and not `force_refresh`, return cached data
3. Otherwise, for each configured repo run:
   ```
   gh issue list --assignee @me --repo {repo} --json number,title,state,labels,assignees,createdAt,updatedAt,url,body,milestone,comments --state open --limit 100
   ```
4. Aggregate results, add `repository` field to each issue
5. Write cache, return results
6. If `gh` not found, return error with install instructions

### Response Types

```rust
struct GitHubConfig {
    repos: Vec<String>,
    refresh_interval_seconds: u64,
}

struct GitHubIssue {
    number: u32,
    title: String,
    state: String,
    labels: Vec<GitHubLabel>,
    assignees: Vec<String>,
    created_at: String,
    updated_at: String,
    url: String,
    body: String,
    milestone: Option<String>,
    comments: u32,
    repository: String,
}

struct GitHubLabel {
    name: String,
    color: String,
}

struct GitHubIssuesResponse {
    issues: Vec<GitHubIssue>,
    fetched_at: String,
    error: Option<String>,
}
```

## Frontend UI

### Navigation
- New "GitHub" icon in nav bar, positioned after Worktrees
- Badge showing total open issue count

### Layout
- **Header:** "GitHub Issues" title, count badge, refresh button, settings gear
- **Filter bar:** Repo dropdown, label filter, open/closed toggle (default: open)
- **Issue list:** Grouped by repository with collapsible sections

### Issue Cards
- Issue number (clickable, opens in browser)
- Title
- Label chips (colored)
- Milestone (if any)
- Time since last update
- Click card to expand and show body/description inline

### Empty States
- No repos configured: prompt to add repos via settings
- No issues: "No issues assigned to you"
- `gh` not installed: install instructions with link

### Repo Config Modal
- Text input for `owner/repo` format
- List of configured repos with remove buttons
- Triggered by gear icon in header

## Technical Notes

- `gh` outputs native JSON with `--json` flag - no text parsing needed
- Cache file pattern matches existing worktree/task caching
- Frontend section pattern matches existing Worktrees/Tasks sections
- Shell command execution uses `std::process::Command` like worktree scanning
