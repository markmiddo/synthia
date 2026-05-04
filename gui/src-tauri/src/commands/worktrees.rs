//! Worktree Tauri commands.

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::LazyLock;

use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{get_claude_dir, get_worktrees_config_path};

static TASK_ID_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#""taskId"\s*:\s*"(\d+)""#).expect("TASK_ID_RE compiles")
});
static TASK_SUBJECT_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#""subject"\s*:\s*"([^"]+)""#).expect("TASK_SUBJECT_RE compiles")
});
static TASK_STATUS_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#""status"\s*:\s*"([^"]+)""#).expect("TASK_STATUS_RE compiles")
});
static TASK_RESULT_ID_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r#""id"\s*:\s*"(\d+)""#).expect("TASK_RESULT_ID_RE compiles")
});

static ISSUE_NUMBER_REGEXES: LazyLock<Vec<Regex>> = LazyLock::new(|| {
    [
        r"feature/(\d+)-",
        r"issue-(\d+)-",
        r"fix/(\d+)-",
        r"bugfix/(\d+)-",
        r"hotfix/(\d+)-",
        r"(\d+)-",
    ]
    .into_iter()
    .map(|p| Regex::new(p).expect("ISSUE_NUMBER pattern compiles"))
    .collect()
});

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct WorktreeTask {
    pub id: String,
    pub subject: String,
    pub status: String,
    #[serde(rename = "activeForm")]
    pub active_form: Option<String>,
    #[serde(rename = "blockedBy")]
    pub blocked_by: Vec<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct WorktreeInfo {
    path: String,
    branch: String,
    repo_name: String,
    issue_number: Option<u32>,
    session_id: Option<String>,
    tasks: Vec<WorktreeTask>,
    completed_tasks: Vec<WorktreeTask>,
    status: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
pub struct WorktreeStatuses {
    statuses: HashMap<String, String>,
}

#[derive(Deserialize, Debug)]
pub struct SessionEntry {
    #[serde(rename = "sessionId")]
    session_id: String,
    #[serde(rename = "projectPath")]
    project_path: String,
    #[serde(rename = "gitBranch")]
    git_branch: Option<String>,
    summary: Option<String>,
}

#[derive(Deserialize, Debug)]
pub struct SessionsIndex {
    entries: Vec<SessionEntry>,
}

pub(crate) fn get_worktree_status_file() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia")
        .join("worktree-status.json")
}

pub(crate) fn load_worktree_statuses() -> WorktreeStatuses {
    let path = get_worktree_status_file();
    if let Ok(content) = fs::read_to_string(&path) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        WorktreeStatuses::default()
    }
}

pub(crate) fn save_worktree_statuses(statuses: &WorktreeStatuses) -> AppResult<()> {
    let path = get_worktree_status_file();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(statuses)?;
    fs::write(&path, content)?;
    Ok(())
}

pub(crate) fn load_tasks_for_session(session_id: &str) -> Vec<WorktreeTask> {
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

pub(crate) fn load_completed_tasks_from_session(session_id: &str, project_dir: &std::path::Path) -> Vec<WorktreeTask> {
    let session_file = project_dir.join(format!("{}.jsonl", session_id));

    if !session_file.exists() {
        return Vec::new();
    }

    // Check if this session had tasks
    let tasks_dir = get_claude_dir().join("tasks").join(session_id);
    if !tasks_dir.exists() {
        return Vec::new();
    }

    let mut tasks: HashMap<String, WorktreeTask> = HashMap::new();

    if let Ok(content) = fs::read_to_string(&session_file) {
        for line in content.lines() {
            // Look for TaskCreate or TaskUpdate tool calls
            if line.contains("TaskCreate") || line.contains("TaskUpdate") {
                let task_id = TASK_ID_RE
                    .captures(line)
                    .and_then(|caps| caps.get(1))
                    .map(|m| m.as_str().to_string());

                let subject = TASK_SUBJECT_RE
                    .captures(line)
                    .and_then(|caps| caps.get(1))
                    .map(|m| m.as_str().to_string());

                let status = TASK_STATUS_RE
                    .captures(line)
                    .and_then(|caps| caps.get(1))
                    .map(|m| m.as_str().to_string());

                // TaskCreate - add new task
                if line.contains("TaskCreate") {
                    if let Some(subj) = subject {
                        // For TaskCreate, we need to find the task ID from the result
                        // but for now use a placeholder that will be updated
                        let id = task_id.clone().unwrap_or_else(|| format!("new_{}", tasks.len()));
                        tasks.insert(id.clone(), WorktreeTask {
                            id,
                            subject: subj,
                            status: "pending".to_string(),
                            active_form: None,
                            blocked_by: Vec::new(),
                        });
                    }
                }

                // TaskUpdate - update status
                if line.contains("TaskUpdate") {
                    if let (Some(id), Some(stat)) = (task_id, status) {
                        if let Some(task) = tasks.get_mut(&id) {
                            task.status = stat;
                        }
                    }
                }
            }

            // Also check for tool_result with task ID (from TaskCreate)
            if line.contains("tool_result") && line.contains("\"id\":") {
                if let Some(caps) = TASK_RESULT_ID_RE.captures(line) {
                    if let Some(m) = caps.get(1) {
                        let new_id = m.as_str().to_string();
                        // Find any task with placeholder ID and update it
                        let placeholder_keys: Vec<_> = tasks.keys()
                            .filter(|k| k.starts_with("new_"))
                            .cloned()
                            .collect();
                        if let Some(old_key) = placeholder_keys.last() {
                            if let Some(mut task) = tasks.remove(old_key) {
                                task.id = new_id.clone();
                                tasks.insert(new_id, task);
                            }
                        }
                    }
                }
            }
        }
    }

    // Return only completed tasks, sorted by ID
    let mut completed: Vec<_> = tasks.into_values()
        .filter(|t| t.status == "completed")
        .collect();
    completed.sort_by(|a, b| {
        a.id.parse::<u32>().unwrap_or(0).cmp(&b.id.parse::<u32>().unwrap_or(0))
    });
    completed
}

pub(crate) fn find_session_for_worktree(project_path: &str, branch: &str, repo_path: &str) -> Option<(String, PathBuf)> {
    let projects_dir = get_claude_dir().join("projects");

    if !projects_dir.exists() {
        return None;
    }

    let normalized_path = PathBuf::from(project_path).canonicalize().ok();
    let normalized_repo = PathBuf::from(repo_path).canonicalize().ok();

    // Collect potential matches with scores
    let mut candidates: Vec<(String, PathBuf, i32)> = Vec::new();

    for entry in fs::read_dir(&projects_dir).ok()?.flatten() {
        let project_dir = entry.path();
        if !project_dir.is_dir() {
            continue;
        }

        let index_file = project_dir.join("sessions-index.json");
        if !index_file.exists() {
            continue;
        }

        if let Ok(content) = fs::read_to_string(&index_file) {
            if let Ok(index) = serde_json::from_str::<SessionsIndex>(&content) {
                for session in index.entries {
                    let mut score = 0;

                    // Exact worktree path match (highest priority)
                    if let Some(ref norm_path) = normalized_path {
                        if let Ok(entry_path) = PathBuf::from(&session.project_path).canonicalize() {
                            if entry_path == *norm_path {
                                return Some((session.session_id, project_dir));
                            }
                        }
                    }

                    // Check if worktree is under session's project path
                    if let Some(ref norm_path) = normalized_path {
                        if let Ok(session_path) = PathBuf::from(&session.project_path).canonicalize() {
                            if norm_path.starts_with(&session_path) {
                                score += 10;
                            }
                        }
                    }

                    // Check if session path is under repo path
                    if let Some(ref norm_repo) = normalized_repo {
                        if let Ok(session_path) = PathBuf::from(&session.project_path).canonicalize() {
                            if session_path.starts_with(norm_repo) || norm_repo.starts_with(&session_path) {
                                score += 5;
                            }
                        }
                    }

                    // Branch name match in session metadata
                    if let Some(ref session_branch) = session.git_branch {
                        if !session_branch.is_empty() {
                            let branch_name = branch.trim_start_matches("feature/");
                            let session_branch_name = session_branch.trim_start_matches("feature/");
                            if branch_name == session_branch_name {
                                score += 20;
                            }
                        }
                    }

                    // Check if branch name appears in summary
                    if let Some(ref summary) = session.summary {
                        let branch_name = branch.trim_start_matches("feature/").replace("-", " ");
                        if summary.to_lowercase().contains(&branch_name.to_lowercase()) {
                            score += 15;
                        }
                    }

                    if score > 0 {
                        candidates.push((session.session_id.clone(), project_dir.clone(), score));
                    }
                }
            }
        }
    }

    // Return the best match
    candidates.sort_by(|a, b| b.2.cmp(&a.2));
    candidates.into_iter().next().map(|(id, dir, _)| (id, dir))
}

pub(crate) fn extract_issue_number(branch: &str) -> Option<u32> {
    use std::str::FromStr;

    for re in ISSUE_NUMBER_REGEXES.iter() {
        if let Some(caps) = re.captures(branch) {
            if let Some(m) = caps.get(1) {
                if let Ok(num) = u32::from_str(m.as_str()) {
                    return Some(num);
                }
            }
        }
    }
    None
}

#[tauri::command]
pub fn get_worktrees() -> Vec<WorktreeInfo> {
    let config_path = get_worktrees_config_path();
    let statuses = load_worktree_statuses();

    // Load configured repos via serde_yaml. Empty/missing/malformed config
    // all collapse to an empty list — the worktrees panel just shows nothing
    // rather than erroring out.
    let repos: Vec<String> = fs::read_to_string(&config_path)
        .ok()
        .and_then(|c| serde_yaml::from_str::<crate::config::WorktreesYaml>(&c).ok())
        .map(|c| c.repos)
        .unwrap_or_default();

    let mut worktrees = Vec::new();

    for repo in repos {
        // Extract repo name from path (e.g., "/home/user/dev/organizer-backend" -> "organizer-backend")
        let repo_name = PathBuf::from(&repo)
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| repo.clone());

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
                    if let Some(p) = line.strip_prefix("worktree ") {
                        current_path = p.to_string();
                    } else if let Some(b) = line.strip_prefix("branch ") {
                        current_branch = b
                            .strip_prefix("refs/heads/")
                            .unwrap_or(b)
                            .to_string();
                    } else if line.is_empty() && !current_path.is_empty() {
                        let session_result = find_session_for_worktree(&current_path, &current_branch, &repo);
                        let (session_id, tasks, completed_tasks) = match session_result {
                            Some((id, project_dir)) => {
                                let t = load_tasks_for_session(&id);
                                let ct = if t.is_empty() {
                                    load_completed_tasks_from_session(&id, &project_dir)
                                } else {
                                    Vec::new()
                                };
                                (Some(id), t, ct)
                            }
                            None => (None, Vec::new(), Vec::new())
                        };

                        let status = statuses.statuses.get(&current_path).cloned();
                        worktrees.push(WorktreeInfo {
                            path: current_path.clone(),
                            branch: current_branch.clone(),
                            repo_name: repo_name.clone(),
                            issue_number: extract_issue_number(&current_branch),
                            session_id,
                            tasks,
                            completed_tasks,
                            status,
                        });

                        current_path.clear();
                        current_branch.clear();
                    }
                }

                // Handle last entry
                if !current_path.is_empty() {
                    let session_result = find_session_for_worktree(&current_path, &current_branch, &repo);
                    let (session_id, tasks, completed_tasks) = match session_result {
                        Some((id, project_dir)) => {
                            let t = load_tasks_for_session(&id);
                            let ct = if t.is_empty() {
                                load_completed_tasks_from_session(&id, &project_dir)
                            } else {
                                Vec::new()
                            };
                            (Some(id), t, ct)
                        }
                        None => (None, Vec::new(), Vec::new())
                    };

                    let status = statuses.statuses.get(&current_path).cloned();
                    worktrees.push(WorktreeInfo {
                        path: current_path,
                        branch: current_branch.clone(),
                        repo_name: repo_name.clone(),
                        issue_number: extract_issue_number(&current_branch),
                        session_id,
                        tasks,
                        completed_tasks,
                        status,
                    });
                }
            }
        }
    }

    worktrees
}

#[tauri::command]
pub fn set_worktree_status(path: String, status: Option<String>) -> AppResult<String> {
    let mut statuses = load_worktree_statuses();

    if let Some(s) = status {
        if s.is_empty() {
            statuses.statuses.remove(&path);
        } else {
            statuses.statuses.insert(path, s);
        }
    } else {
        statuses.statuses.remove(&path);
    }

    save_worktree_statuses(&statuses)?;
    Ok("Status updated".to_string())
}

#[tauri::command]
pub fn resume_session(path: String, session_id: Option<String>) -> AppResult<String> {
    // Build the claude command with permissions bypass
    let mut args = vec!["cli".to_string(), "split-pane".to_string(), "--".to_string()];

    if let Some(sid) = session_id {
        args.push("claude-us".to_string());
        args.push("--resume".to_string());
        args.push(sid);
    } else {
        args.push("claude-us".to_string());
    }

    // Use wezterm cli to open a new pane
    Command::new("wezterm")
        .args(&args)
        .current_dir(&path)
        .spawn()
        .map_err(|e| AppError::Process(format!("Failed to open WezTerm pane: {}", e)))?;

    Ok("Session opened in WezTerm".to_string())
}

#[tauri::command]
pub fn get_worktree_repos() -> Vec<String> {
    let config_path = get_worktrees_config_path();
    fs::read_to_string(&config_path)
        .ok()
        .and_then(|c| serde_yaml::from_str::<crate::config::WorktreesYaml>(&c).ok())
        .map(|c| c.repos)
        .unwrap_or_default()
}

#[tauri::command]
pub fn save_worktree_repos(repos: Vec<String>) -> AppResult<String> {
    let config_path = get_worktrees_config_path();
    let content = crate::yaml_writer::write_worktrees_repos(&repos);

    fs::write(&config_path, content)
        .map_err(|e| AppError::Io(format!("Failed to write config: {}", e)))?;

    Ok("Worktree repos saved".to_string())
}
