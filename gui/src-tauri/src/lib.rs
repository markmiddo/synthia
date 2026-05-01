use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};
use std::process::{Command, Child, Stdio};
use std::sync::Mutex;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::thread;
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};

mod security;
mod egress;

/// Get the Synthia project root directory.
/// Resolves from the executable path (gui/src-tauri/target/release/synthia-gui)
/// or falls back to finding run.sh relative to the binary.
fn get_synthia_root() -> PathBuf {
    // Try to find the root by looking for run.sh relative to the executable
    if let Ok(exe) = std::env::current_exe() {
        // The binary is at gui/src-tauri/target/release/synthia-gui
        // So root is 4 levels up: release -> target -> src-tauri -> gui -> root
        let mut path = exe.clone();
        for _ in 0..5 {
            path = path.parent().unwrap_or(&path).to_path_buf();
            if path.join("run.sh").exists() {
                return path;
            }
        }
    }
    // Fallback: check if SYNTHIA_ROOT env var is set
    if let Ok(root) = std::env::var("SYNTHIA_ROOT") {
        return PathBuf::from(root);
    }
    // Fallback: check the known development path
    let dev_path = PathBuf::from(
        std::env::var("HOME").unwrap_or_default()
    ).join("dev/misc/synthia");
    if dev_path.join("run.sh").exists() {
        return dev_path;
    }
    // Last resort: current directory
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// Get the XDG runtime directory for temp files (not world-readable /tmp).
fn get_runtime_dir() -> PathBuf {
    PathBuf::from(std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string()))
}

fn load_icon_from_path(path: &PathBuf) -> Option<Image<'static>> {
    let img = image::open(path).ok()?.to_rgba8();
    let (width, height) = img.dimensions();
    let rgba = img.into_raw();
    Some(Image::new_owned(rgba, width, height))
}

// Embed icons directly in binary for better compatibility
static TRAY_ICON_PNG: &[u8] = include_bytes!("../icons/tray-icon.png");
static TRAY_RECORDING_PNG: &[u8] = include_bytes!("../icons/tray-recording.png");

fn load_embedded_icon(data: &'static [u8]) -> Option<Image<'static>> {
    let img = image::load_from_memory(data).ok()?.to_rgba8();
    let (width, height) = img.dimensions();
    let rgba = img.into_raw();
    Some(Image::new_owned(rgba, width, height))
}

static SYNTHIA_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

#[derive(Deserialize, Debug, Default)]
struct SynthiaState {
    status: String,
    recording: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct HistoryEntry {
    id: u32,
    text: String,
    mode: String,
    timestamp: String,
    response: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct WordReplacement {
    from: String,
    to: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct ClipboardEntry {
    id: u64,
    content: String,
    timestamp: String,
    hash: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct InboxItem {
    id: String,
    #[serde(rename = "type")]
    item_type: String,
    filename: String,
    path: Option<String>,
    url: Option<String>,
    received_at: String,
    size_bytes: Option<u64>,
    from_user: Option<String>,
    opened: bool,
}

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
struct MemoryEntry {
    category: String,
    data: serde_json::Value,
    tags: Vec<String>,
    date: Option<String>,
    line_number: usize,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct MemoryStats {
    total: usize,
    categories: std::collections::HashMap<String, usize>,
    tags: Vec<(String, usize)>,
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct SynthiaConfig {
    // Local vs Cloud
    use_local_stt: bool,
    use_local_llm: bool,
    use_local_tts: bool,
    // Models
    local_stt_model: String,
    local_llm_model: String,
    local_tts_voice: String,
    assistant_model: String,
    // TTS settings
    tts_voice: String,
    tts_speed: f64,
    // Other
    conversation_memory: i32,
    show_notifications: bool,
    play_sound_on_record: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct WorktreesRepoConfig {
    repos: Vec<String>,
}

// Claude Config types
#[derive(Deserialize, Serialize, Debug, Clone)]
struct AgentConfig {
    filename: String,
    name: String,
    description: String,
    model: String,
    color: String,
    body: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct CommandConfig {
    filename: String,
    description: String,
    body: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct SkillConfig {
    name: String,
    description: String,
    body: String,
    is_dir: bool,
    has_resources: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct HookConfig {
    event: String,
    command: String,
    timeout: i32,
    hook_type: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct PluginInfo {
    name: String,
    version: String,
    enabled: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct WorktreeInfo {
    path: String,
    branch: String,
    repo_name: String,
    issue_number: Option<u32>,
    session_id: Option<String>,
    tasks: Vec<WorktreeTask>,
    completed_tasks: Vec<WorktreeTask>,
    status: Option<String>,
}

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

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct WorktreeStatuses {
    statuses: std::collections::HashMap<String, String>,
}

fn get_worktree_status_file() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia")
        .join("worktree-status.json")
}

fn load_worktree_statuses() -> WorktreeStatuses {
    let path = get_worktree_status_file();
    if let Ok(content) = fs::read_to_string(&path) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        WorktreeStatuses::default()
    }
}

fn save_worktree_statuses(statuses: &WorktreeStatuses) -> Result<(), String> {
    let path = get_worktree_status_file();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = serde_json::to_string_pretty(statuses).map_err(|e| e.to_string())?;
    fs::write(&path, content).map_err(|e| e.to_string())
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
    #[serde(rename = "gitBranch")]
    git_branch: Option<String>,
    summary: Option<String>,
}

#[derive(Deserialize, Debug)]
struct SessionsIndex {
    entries: Vec<SessionEntry>,
}

fn get_lock_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-gui.lock")
}

fn get_state_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-state.json")
}

fn get_history_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-history.json")
}

fn get_clipboard_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-clipboard.json")
}

fn get_inbox_file() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".local/share/synthia/inbox/inbox.json")
}

fn get_worktrees_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/worktrees.yaml")
}

fn get_claude_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".claude")
}

fn get_memory_dir() -> PathBuf {
    get_claude_dir().join("memory")
}

fn get_agents_dir() -> PathBuf {
    get_claude_dir().join("agents")
}

fn get_commands_dir() -> PathBuf {
    get_claude_dir().join("commands")
}

fn get_skills_dir() -> PathBuf {
    get_claude_dir().join("skills")
}

fn get_settings_file() -> PathBuf {
    get_claude_dir().join("settings.json")
}

fn get_plugins_file() -> PathBuf {
    get_claude_dir().join("plugins").join("installed_plugins.json")
}

fn parse_frontmatter(content: &str) -> (std::collections::HashMap<String, String>, String) {
    if !content.starts_with("---") {
        return (std::collections::HashMap::new(), content.to_string());
    }

    let parts: Vec<&str> = content.splitn(3, "---").collect();
    if parts.len() < 3 {
        return (std::collections::HashMap::new(), content.to_string());
    }

    let mut frontmatter = std::collections::HashMap::new();
    for line in parts[1].trim().lines() {
        if let Some(colon_pos) = line.find(':') {
            let key = line[..colon_pos].trim().to_string();
            let value = line[colon_pos + 1..].trim().to_string();
            frontmatter.insert(key, value);
        }
    }

    (frontmatter, parts[2].to_string())
}

fn get_memory_categories() -> std::collections::HashMap<&'static str, &'static str> {
    let mut map = std::collections::HashMap::new();
    map.insert("bug", "bugs.jsonl");
    map.insert("pattern", "patterns.jsonl");
    map.insert("arch", "architecture.jsonl");
    map.insert("gotcha", "gotchas.jsonl");
    map.insert("stack", "stack.jsonl");
    map
}

fn load_memory_entries(category: Option<&str>) -> Vec<MemoryEntry> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();
    let mut entries = Vec::new();

    let files_to_read: Vec<_> = if let Some(cat) = category {
        if let Some(filename) = categories.get(cat) {
            vec![(cat, *filename)]
        } else {
            return entries;
        }
    } else {
        categories.iter().map(|(k, v)| (*k, *v)).collect()
    };

    for (cat, filename) in files_to_read {
        let filepath = memory_dir.join(filename);
        if !filepath.exists() {
            continue;
        }

        if let Ok(content) = fs::read_to_string(&filepath) {
            for (line_num, line) in content.lines().enumerate() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                if let Ok(mut data) = serde_json::from_str::<serde_json::Value>(line) {
                    let tags = data.get("tags")
                        .and_then(|t| t.as_array())
                        .map(|arr| arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect())
                        .unwrap_or_default();

                    let date = data.get("date")
                        .and_then(|d| d.as_str())
                        .map(|s| s.to_string());

                    // Remove tags and date from data for cleaner display
                    if let Some(obj) = data.as_object_mut() {
                        obj.remove("tags");
                        obj.remove("date");
                    }

                    entries.push(MemoryEntry {
                        category: cat.to_string(),
                        data,
                        tags,
                        date,
                        line_number: line_num,
                    });
                }
            }
        }
    }

    entries
}

fn is_wayland_env() -> bool {
    std::env::var("WAYLAND_DISPLAY").is_ok()
}

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

fn load_completed_tasks_from_session(session_id: &str, project_dir: &std::path::Path) -> Vec<WorktreeTask> {
    let session_file = project_dir.join(format!("{}.jsonl", session_id));

    if !session_file.exists() {
        return Vec::new();
    }

    // Check if this session had tasks
    let tasks_dir = get_claude_dir().join("tasks").join(session_id);
    if !tasks_dir.exists() {
        return Vec::new();
    }

    let mut tasks: std::collections::HashMap<String, WorktreeTask> = std::collections::HashMap::new();

    if let Ok(content) = fs::read_to_string(&session_file) {
        // Regex patterns for extracting task info
        let task_id_re = regex::Regex::new(r#""taskId"\s*:\s*"(\d+)""#).ok();
        let subject_re = regex::Regex::new(r#""subject"\s*:\s*"([^"]+)""#).ok();
        let status_re = regex::Regex::new(r#""status"\s*:\s*"([^"]+)""#).ok();

        for line in content.lines() {
            // Look for TaskCreate or TaskUpdate tool calls
            if line.contains("TaskCreate") || line.contains("TaskUpdate") {
                let task_id = task_id_re.as_ref()
                    .and_then(|re| re.captures(line))
                    .and_then(|caps| caps.get(1))
                    .map(|m| m.as_str().to_string());

                let subject = subject_re.as_ref()
                    .and_then(|re| re.captures(line))
                    .and_then(|caps| caps.get(1))
                    .map(|m| m.as_str().to_string());

                let status = status_re.as_ref()
                    .and_then(|re| re.captures(line))
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
                if let Some(id_re) = regex::Regex::new(r#""id"\s*:\s*"(\d+)""#).ok() {
                    if let Some(caps) = id_re.captures(line) {
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

fn find_session_for_worktree(project_path: &str, branch: &str, repo_path: &str) -> Option<(String, PathBuf)> {
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

#[tauri::command]
fn get_worktrees() -> Vec<WorktreeInfo> {
    let config_path = get_worktrees_config_path();
    let statuses = load_worktree_statuses();

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
                    if line.starts_with("worktree ") {
                        current_path = line[9..].to_string();
                    } else if line.starts_with("branch ") {
                        current_branch = line[7..].to_string();
                        if current_branch.starts_with("refs/heads/") {
                            current_branch = current_branch[11..].to_string();
                        }
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
fn set_worktree_status(path: String, status: Option<String>) -> Result<String, String> {
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

fn acquire_lock() -> bool {
    let lock_file = get_lock_file();

    if lock_file.exists() {
        if let Ok(pid_str) = fs::read_to_string(&lock_file) {
            if let Ok(pid) = pid_str.trim().parse::<i32>() {
                let check = Command::new("kill")
                    .args(["-0", &pid.to_string()])
                    .output();
                if check.map(|o| o.status.success()).unwrap_or(false) {
                    return false;
                }
            }
        }
    }

    let pid = std::process::id();
    fs::write(&lock_file, pid.to_string()).ok();
    true
}

fn release_lock() {
    let lock_file = get_lock_file();
    fs::remove_file(lock_file).ok();
}

fn read_synthia_state() -> SynthiaState {
    let state_file = get_state_file();
    if let Ok(content) = fs::read_to_string(&state_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        SynthiaState::default()
    }
}

#[tauri::command]
fn get_status() -> String {
    let output = Command::new("pgrep")
        .args(["-f", "synthia.main"])
        .output();

    match output {
        Ok(out) if out.status.success() => "running".to_string(),
        _ => "stopped".to_string(),
    }
}

#[tauri::command]
fn start_synthia() -> Result<String, String> {
    let mut proc = SYNTHIA_PROCESS.lock().unwrap();
    if proc.is_some() {
        return Ok("Already running".to_string());
    }

    let root = get_synthia_root();
    let log_path = root.join("synthia.log");
    let log_file = std::fs::File::create(&log_path)
        .map_err(|e| format!("Failed to create log file: {}", e))?;
    let stderr_file = log_file.try_clone()
        .map_err(|e| format!("Failed to clone log file: {}", e))?;
    let child = Command::new(root.join("run.sh"))
        .current_dir(&root)
        .stdout(std::process::Stdio::from(log_file))
        .stderr(std::process::Stdio::from(stderr_file))
        .spawn()
        .map_err(|e| format!("Failed to start: {}", e))?;

    *proc = Some(child);
    Ok("Synthia started".to_string())
}

#[tauri::command]
fn stop_synthia() -> Result<String, String> {
    let _ = Command::new("pkill")
        .args(["-f", "synthia.main"])
        .output();

    let mut proc = SYNTHIA_PROCESS.lock().unwrap();
    *proc = None;

    Ok("Synthia stopped".to_string())
}

#[tauri::command]
fn set_mode(mode: &str) -> Result<String, String> {
    Ok(format!("Mode set to: {}", mode))
}

#[tauri::command]
fn start_remote_mode() -> Result<String, String> {
    // Check if already running
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    if check.map(|o| o.status.success()).unwrap_or(false) {
        return Ok("Remote mode already running".to_string());
    }

    let root = get_synthia_root();
    let runtime_dir = get_runtime_dir();
    let remote_mode_file = runtime_dir.join("synthia-remote-mode");

    // Create the remote mode flag file (chat ID is read from config by telegram_bot.py)
    let _ = fs::write(&remote_mode_file, "remote");

    // Start the telegram bot with CUDA disabled
    let python = root.join("venv/bin/python");
    let bot_script = root.join("src/synthia/remote/telegram_bot.py");
    Command::new(&python)
        .args([bot_script.to_str().unwrap_or("")])
        .current_dir(&root)
        .env("CUDA_VISIBLE_DEVICES", "")
        .spawn()
        .map_err(|e| format!("Failed to start remote mode: {}", e))?;

    // Send notification in background (don't block UI)
    let _ = Command::new(&python)
        .args([
            bot_script.to_str().unwrap_or(""),
            "--notify",
            "🟢 *Remote Mode ENABLED*\n\nYou can now control Claude Code via Telegram."
        ])
        .current_dir(&root)
        .spawn();

    Ok("Remote mode started".to_string())
}

#[tauri::command]
fn stop_remote_mode() -> Result<String, String> {
    let root = get_synthia_root();
    let runtime_dir = get_runtime_dir();
    let remote_mode_file = runtime_dir.join("synthia-remote-mode");

    // Remove the remote mode flag file (stops response forwarding to Telegram)
    let _ = fs::remove_file(&remote_mode_file);

    // Kill the bot immediately for instant UI response
    let _ = Command::new("pkill")
        .args(["-f", "telegram_bot.py"])
        .output();

    // Send notification in background (after bot is killed, uses --notify which is standalone)
    let python = root.join("venv/bin/python");
    let bot_script = root.join("src/synthia/remote/telegram_bot.py");
    let _ = Command::new(&python)
        .args([
            bot_script.to_str().unwrap_or(""),
            "--notify",
            "🔴 *Remote Mode DISABLED*\n\nTelegram bot stopped."
        ])
        .current_dir(&root)
        .spawn();

    Ok("Remote mode stopped".to_string())
}

#[tauri::command]
fn get_remote_status() -> bool {
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    check.map(|o| o.status.success()).unwrap_or(false)
}

#[tauri::command]
fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.show().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn set_overlay_recording(app: tauri::AppHandle, active: bool) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.emit("recording", active).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn get_history() -> Vec<HistoryEntry> {
    let history_file = get_history_file();
    if let Ok(content) = fs::read_to_string(&history_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
fn clear_history() -> Result<String, String> {
    let history_file = get_history_file();
    fs::write(&history_file, "[]").map_err(|e| e.to_string())?;
    Ok("History cleared".to_string())
}

fn get_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

fn get_runtime_state_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/runtime.json")
}

#[tauri::command]
fn get_voice_muted() -> bool {
    let path = get_runtime_state_path();
    let content = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return false,
    };
    serde_json::from_str::<serde_json::Value>(&content)
        .ok()
        .and_then(|v| v.get("tts_muted").and_then(|b| b.as_bool()))
        .unwrap_or(false)
}

#[tauri::command]
fn set_voice_muted(muted: bool) -> Result<(), String> {
    let path = get_runtime_state_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut state: serde_json::Value = fs::read_to_string(&path)
        .ok()
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = state.as_object_mut() {
        obj.insert("tts_muted".to_string(), serde_json::Value::Bool(muted));
    }
    let serialized = serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?;
    fs::write(&path, serialized).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn get_hotkeys() -> Result<(String, String), String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

    // Parse YAML manually for simplicity
    let mut dictation_key = "Right Ctrl".to_string();
    let mut assistant_key = "Right Alt".to_string();

    for line in content.lines() {
        if line.starts_with("dictation_key:") {
            dictation_key = line.split(':').nth(1)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or(dictation_key);
            // Convert from pynput format to display format
            dictation_key = dictation_key
                .replace("Key.ctrl_r", "Right Ctrl")
                .replace("Key.ctrl_l", "Left Ctrl")
                .replace("Key.alt_r", "Right Alt")
                .replace("Key.alt_l", "Left Alt")
                .replace("Key.shift_r", "Right Shift")
                .replace("Key.shift_l", "Left Shift");
        } else if line.starts_with("assistant_key:") {
            assistant_key = line.split(':').nth(1)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or(assistant_key);
            // Convert from pynput format to display format
            assistant_key = assistant_key
                .replace("Key.ctrl_r", "Right Ctrl")
                .replace("Key.ctrl_l", "Left Ctrl")
                .replace("Key.alt_r", "Right Alt")
                .replace("Key.alt_l", "Left Alt")
                .replace("Key.shift_r", "Right Shift")
                .replace("Key.shift_l", "Left Shift");
        }
    }

    Ok((dictation_key, assistant_key))
}

#[tauri::command]
fn save_hotkeys(dictation_key: String, assistant_key: String) -> Result<String, String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

    // Convert display format to pynput format
    let dictation_pynput = match dictation_key.as_str() {
        "Right Ctrl" => "Key.ctrl_r",
        "Left Ctrl" => "Key.ctrl_l",
        "Right Alt" => "Key.alt_r",
        "Left Alt" => "Key.alt_l",
        "Right Shift" => "Key.shift_r",
        "Left Shift" => "Key.shift_l",
        _ => &dictation_key,
    };

    let assistant_pynput = match assistant_key.as_str() {
        "Right Ctrl" => "Key.ctrl_r",
        "Left Ctrl" => "Key.ctrl_l",
        "Right Alt" => "Key.alt_r",
        "Left Alt" => "Key.alt_l",
        "Right Shift" => "Key.shift_r",
        "Left Shift" => "Key.shift_l",
        _ => &assistant_key,
    };

    // Update the config file
    let mut new_content = String::new();
    for line in content.lines() {
        if line.starts_with("dictation_key:") {
            new_content.push_str(&format!("dictation_key: \"{}\"\n", dictation_pynput));
        } else if line.starts_with("assistant_key:") {
            new_content.push_str(&format!("assistant_key: \"{}\"\n", assistant_pynput));
        } else {
            new_content.push_str(line);
            new_content.push('\n');
        }
    }

    fs::write(&config_path, new_content.trim_end())
        .map_err(|e| format!("Failed to write config: {}", e))?;

    // Signal Synthia to reload config by touching a signal file
    // Synthia watches for this file and updates hotkeys dynamically (no restart needed!)
    let signal_file = get_runtime_dir().join("synthia-reload-config");
    fs::write(&signal_file, "reload").ok();

    Ok("Hotkeys saved".to_string())
}

#[tauri::command]
fn get_word_replacements() -> Vec<WordReplacement> {
    let config_path = get_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let mut replacements = Vec::new();
    let mut in_word_replacements = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("word_replacements:") {
            in_word_replacements = true;
            continue;
        }

        // Check if we've left the word_replacements section
        if in_word_replacements && !trimmed.is_empty() && !trimmed.starts_with('#') {
            if !line.starts_with(' ') && !line.starts_with('\t') {
                // New top-level key, we're done
                break;
            }

            // Parse "from: to" format
            if let Some(colon_pos) = trimmed.find(':') {
                let from = trimmed[..colon_pos].trim().to_string();
                let to = trimmed[colon_pos + 1..].trim().to_string();
                if !from.is_empty() && !to.is_empty() {
                    replacements.push(WordReplacement { from, to });
                }
            }
        }
    }

    replacements
}

#[tauri::command]
fn save_word_replacements(replacements: Vec<WordReplacement>) -> Result<String, String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

    let mut new_content = String::new();
    let mut in_word_replacements = false;
    let mut wrote_replacements = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("word_replacements:") {
            in_word_replacements = true;
            new_content.push_str("word_replacements:\n");
            // Write all replacements
            for r in &replacements {
                new_content.push_str(&format!("  {}: {}\n", r.from, r.to));
            }
            wrote_replacements = true;
            continue;
        }

        if in_word_replacements {
            // Skip old replacement lines (indented lines)
            if line.starts_with(' ') || line.starts_with('\t') {
                if !trimmed.is_empty() && !trimmed.starts_with('#') {
                    continue; // Skip old entries
                }
            } else if !trimmed.is_empty() {
                // New top-level key, we're done with word_replacements
                in_word_replacements = false;
            }
        }

        if !in_word_replacements {
            new_content.push_str(line);
            new_content.push('\n');
        }
    }

    // If word_replacements section didn't exist, add it
    if !wrote_replacements {
        new_content.push_str("\n# Word replacements for dictation\nword_replacements:\n");
        for r in &replacements {
            new_content.push_str(&format!("  {}: {}\n", r.from, r.to));
        }
    }

    fs::write(&config_path, new_content.trim_end())
        .map_err(|e| format!("Failed to write config: {}", e))?;

    Ok("Word replacements saved".to_string())
}

#[tauri::command]
fn get_clipboard_history() -> Vec<ClipboardEntry> {
    let clipboard_file = get_clipboard_file();
    if let Ok(content) = fs::read_to_string(&clipboard_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
fn copy_from_clipboard_history(content: String) -> Result<String, String> {
    if is_wayland_env() {
        let mut child = Command::new("wl-copy")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn wl-copy: {}", e))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(content.as_bytes())
                .map_err(|e| format!("Failed to write to wl-copy: {}", e))?;
        }

        child.wait().map_err(|e| format!("wl-copy failed: {}", e))?;
    } else {
        let mut child = Command::new("xclip")
            .args(["-selection", "clipboard"])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn xclip: {}", e))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(content.as_bytes())
                .map_err(|e| format!("Failed to write to xclip: {}", e))?;
        }

        child.wait().map_err(|e| format!("xclip failed: {}", e))?;
    }

    Ok("Copied to clipboard".to_string())
}

#[derive(Deserialize, Serialize, Debug)]
struct InboxData {
    items: Vec<InboxItem>,
}

#[tauri::command]
fn get_inbox_items() -> Vec<InboxItem> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(data) = serde_json::from_str::<InboxData>(&content) {
            return data.items;
        }
    }
    Vec::new()
}

#[tauri::command]
fn open_inbox_item(id: String, item_type: String, path: Option<String>, url: Option<String>) -> Result<String, String> {
    // Open the item with xdg-open
    let target = if item_type == "url" {
        url.ok_or("No URL provided")?
    } else {
        path.ok_or("No path provided")?
    };

    Command::new("xdg-open")
        .arg(&target)
        .spawn()
        .map_err(|e| format!("Failed to open: {}", e))?;

    // Mark as opened in the inbox file
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(mut data) = serde_json::from_str::<InboxData>(&content) {
            for item in &mut data.items {
                if item.id == id {
                    item.opened = true;
                    break;
                }
            }
            let _ = fs::write(&inbox_file, serde_json::to_string_pretty(&data).unwrap_or_default());
        }
    }

    Ok("Opened".to_string())
}

#[tauri::command]
fn delete_inbox_item(id: String) -> Result<String, String> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(mut data) = serde_json::from_str::<InboxData>(&content) {
            // Find and remove the item, also delete file if exists
            let mut path_to_delete: Option<String> = None;
            data.items.retain(|item| {
                if item.id == id {
                    path_to_delete = item.path.clone();
                    false
                } else {
                    true
                }
            });

            // Delete the file if it exists
            if let Some(path) = path_to_delete {
                let _ = fs::remove_file(&path);
            }

            let _ = fs::write(&inbox_file, serde_json::to_string_pretty(&data).unwrap_or_default());
            return Ok("Deleted".to_string());
        }
    }
    Err("Failed to delete item".to_string())
}

#[tauri::command]
fn clear_inbox() -> Result<String, String> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(data) = serde_json::from_str::<InboxData>(&content) {
            // Delete all files
            for item in &data.items {
                if let Some(path) = &item.path {
                    let _ = fs::remove_file(path);
                }
            }
        }
    }

    // Clear the inbox
    let _ = fs::write(&inbox_file, r#"{"items": []}"#);
    Ok("Inbox cleared".to_string())
}

#[tauri::command]
fn resume_session(path: String, session_id: Option<String>) -> Result<String, String> {
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
        .map_err(|e| format!("Failed to open WezTerm pane: {}", e))?;

    Ok("Session opened in WezTerm".to_string())
}

#[tauri::command]
fn get_memory_stats() -> MemoryStats {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();
    let mut cat_counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut tag_counts: std::collections::HashMap<String, usize> = std::collections::HashMap::new();
    let mut total = 0;

    for (cat, filename) in &categories {
        let filepath = memory_dir.join(filename);
        if !filepath.exists() {
            cat_counts.insert(cat.to_string(), 0);
            continue;
        }

        if let Ok(content) = fs::read_to_string(&filepath) {
            let mut count = 0;
            for line in content.lines() {
                let line = line.trim();
                if line.is_empty() {
                    continue;
                }

                if let Ok(data) = serde_json::from_str::<serde_json::Value>(line) {
                    count += 1;

                    // Count tags
                    if let Some(tags) = data.get("tags").and_then(|t| t.as_array()) {
                        for tag in tags {
                            if let Some(tag_str) = tag.as_str() {
                                *tag_counts.entry(tag_str.to_string()).or_insert(0) += 1;
                            }
                        }
                    }
                }
            }
            total += count;
            cat_counts.insert(cat.to_string(), count);
        } else {
            cat_counts.insert(cat.to_string(), 0);
        }
    }

    // Sort tags by count
    let mut tags: Vec<_> = tag_counts.into_iter().collect();
    tags.sort_by(|a, b| b.1.cmp(&a.1));
    tags.truncate(15);

    MemoryStats {
        total,
        categories: cat_counts,
        tags,
    }
}

#[tauri::command]
fn get_memory_entries(category: Option<String>) -> Vec<MemoryEntry> {
    load_memory_entries(category.as_deref())
}

#[tauri::command]
fn search_memory(query: String) -> Vec<MemoryEntry> {
    let all_entries = load_memory_entries(None);
    let query_lower = query.to_lowercase();
    let query_tags: Vec<_> = query.split(',').map(|s| s.trim().to_lowercase()).collect();

    all_entries.into_iter().filter(|entry| {
        // Check if any tag matches
        let tag_match = entry.tags.iter().any(|t| {
            query_tags.iter().any(|qt| t.to_lowercase().contains(qt))
        });

        if tag_match {
            return true;
        }

        // Check full text in data
        let data_str = entry.data.to_string().to_lowercase();
        data_str.contains(&query_lower)
    }).collect()
}

#[tauri::command]
fn update_memory_entry(
    category: String,
    line_number: usize,
    data: serde_json::Value,
    tags: Vec<String>,
) -> Result<String, String> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();

    let filename = categories.get(category.as_str())
        .ok_or_else(|| format!("Unknown category: {}", category))?;

    let filepath = memory_dir.join(filename);

    let content = fs::read_to_string(&filepath)
        .map_err(|e| format!("Failed to read file: {}", e))?;

    let mut lines: Vec<_> = content.lines().collect();

    if line_number >= lines.len() {
        return Err("Invalid line number".to_string());
    }

    // Build new entry
    let mut new_data = data;
    if let Some(obj) = new_data.as_object_mut() {
        obj.insert("tags".to_string(), serde_json::json!(tags));
        obj.insert("date".to_string(), serde_json::json!(
            chrono::Local::now().format("%Y-%m").to_string()
        ));
    }

    let new_line = serde_json::to_string(&new_data)
        .map_err(|e| format!("Failed to serialize: {}", e))?;

    lines[line_number] = Box::leak(new_line.into_boxed_str());

    let new_content = lines.join("\n");
    fs::write(&filepath, new_content)
        .map_err(|e| format!("Failed to write file: {}", e))?;

    Ok("Entry updated".to_string())
}

#[tauri::command]
fn get_synthia_config() -> SynthiaConfig {
    let config_path = get_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return SynthiaConfig::default(),
    };

    let mut config = SynthiaConfig::default();

    for line in content.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }

        if let Some((key, value)) = line.split_once(':') {
            let key = key.trim();
            let value = value.trim().trim_matches('"').trim_matches('\'');

            match key {
                "use_local_stt" => config.use_local_stt = value == "true",
                "use_local_llm" => config.use_local_llm = value == "true",
                "use_local_tts" => config.use_local_tts = value == "true",
                "local_stt_model" => config.local_stt_model = value.to_string(),
                "local_llm_model" => config.local_llm_model = value.to_string(),
                "local_tts_voice" => config.local_tts_voice = value.to_string(),
                "assistant_model" => config.assistant_model = value.to_string(),
                "tts_voice" => config.tts_voice = value.to_string(),
                "tts_speed" => config.tts_speed = value.parse().unwrap_or(1.0),
                "conversation_memory" => config.conversation_memory = value.parse().unwrap_or(10),
                "show_notifications" => config.show_notifications = value == "true",
                "play_sound_on_record" => config.play_sound_on_record = value == "true",
                _ => {}
            }
        }
    }

    config
}

#[tauri::command]
fn save_synthia_config(config: SynthiaConfig) -> Result<String, String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

    let mut new_lines: Vec<String> = Vec::new();

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.is_empty() || trimmed.starts_with('#') {
            new_lines.push(line.to_string());
            continue;
        }

        if let Some((key, _)) = trimmed.split_once(':') {
            let key = key.trim();
            let new_value = match key {
                "use_local_stt" => Some(format!("use_local_stt: {}", config.use_local_stt)),
                "use_local_llm" => Some(format!("use_local_llm: {}", config.use_local_llm)),
                "use_local_tts" => Some(format!("use_local_tts: {}", config.use_local_tts)),
                "local_stt_model" => Some(format!("local_stt_model: \"{}\"", config.local_stt_model)),
                "local_llm_model" => Some(format!("local_llm_model: \"{}\"", config.local_llm_model)),
                "local_tts_voice" => Some(format!("local_tts_voice: {}", config.local_tts_voice)),
                "assistant_model" => Some(format!("assistant_model: \"{}\"", config.assistant_model)),
                "tts_voice" => Some(format!("tts_voice: \"{}\"", config.tts_voice)),
                "tts_speed" => Some(format!("tts_speed: {}", config.tts_speed)),
                "conversation_memory" => Some(format!("conversation_memory: {}", config.conversation_memory)),
                "show_notifications" => Some(format!("show_notifications: {}", config.show_notifications)),
                "play_sound_on_record" => Some(format!("play_sound_on_record: {}", config.play_sound_on_record)),
                _ => None,
            };

            if let Some(new_line) = new_value {
                new_lines.push(new_line);
            } else {
                new_lines.push(line.to_string());
            }
        } else {
            new_lines.push(line.to_string());
        }
    }

    fs::write(&config_path, new_lines.join("\n"))
        .map_err(|e| format!("Failed to write config: {}", e))?;

    // Signal Synthia to reload config
    let signal_file = get_runtime_dir().join("synthia-reload-config");
    fs::write(&signal_file, "reload").ok();

    Ok("Config saved".to_string())
}

#[tauri::command]
fn get_worktree_repos() -> Vec<String> {
    let config_path = get_worktrees_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

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
}

#[tauri::command]
fn save_worktree_repos(repos: Vec<String>) -> Result<String, String> {
    let config_path = get_worktrees_config_path();

    let mut content = String::from("# Repositories to scan for worktrees\n");
    content.push_str("# Add paths to git repos you want to track\n");
    content.push_str("repos:\n");

    for repo in repos {
        content.push_str(&format!("  - {}\n", repo));
    }

    fs::write(&config_path, content)
        .map_err(|e| format!("Failed to write config: {}", e))?;

    Ok("Worktree repos saved".to_string())
}

#[tauri::command]
fn delete_memory_entry(category: String, line_number: usize) -> Result<String, String> {
    let memory_dir = get_memory_dir();
    let categories = get_memory_categories();

    let filename = categories.get(category.as_str())
        .ok_or_else(|| format!("Unknown category: {}", category))?;

    let filepath = memory_dir.join(filename);

    let content = fs::read_to_string(&filepath)
        .map_err(|e| format!("Failed to read file: {}", e))?;

    let mut lines: Vec<_> = content.lines().collect();

    if line_number >= lines.len() {
        return Err("Invalid line number".to_string());
    }

    lines.remove(line_number);

    let new_content = lines.join("\n");
    fs::write(&filepath, new_content)
        .map_err(|e| format!("Failed to write file: {}", e))?;

    Ok("Entry deleted".to_string())
}

// === CLAUDE CONFIG COMMANDS ===

#[tauri::command]
fn list_agents() -> Vec<AgentConfig> {
    let agents_dir = get_agents_dir();
    if !agents_dir.exists() {
        return Vec::new();
    }

    let mut agents = Vec::new();
    if let Ok(entries) = fs::read_dir(&agents_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().map(|e| e == "md").unwrap_or(false) {
                if let Ok(content) = fs::read_to_string(&path) {
                    let (fm, body) = parse_frontmatter(&content);
                    let filename = path.file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_default();
                    agents.push(AgentConfig {
                        filename: filename.clone(),
                        name: fm.get("name").cloned().unwrap_or_else(|| filename.replace(".md", "")),
                        description: fm.get("description").cloned().unwrap_or_default(),
                        model: fm.get("model").cloned().unwrap_or_else(|| "sonnet".to_string()),
                        color: fm.get("color").cloned().unwrap_or_else(|| "green".to_string()),
                        body: body.trim().to_string(),
                    });
                }
            }
        }
    }
    agents.sort_by(|a, b| a.name.cmp(&b.name));
    agents
}

#[tauri::command]
fn save_agent(agent: AgentConfig) -> Result<String, String> {
    let agents_dir = get_agents_dir();
    fs::create_dir_all(&agents_dir).map_err(|e| e.to_string())?;

    let content = format!(
        "---\nname: {}\ndescription: {}\nmodel: {}\ncolor: {}\n---\n\n{}",
        agent.name, agent.description, agent.model, agent.color, agent.body
    );

    let filepath = agents_dir.join(&agent.filename);
    fs::write(&filepath, content).map_err(|e| e.to_string())?;
    Ok("Agent saved".to_string())
}

#[tauri::command]
fn delete_agent(filename: String) -> Result<String, String> {
    let filepath = get_agents_dir().join(&filename);
    if filepath.exists() {
        fs::remove_file(&filepath).map_err(|e| e.to_string())?;
    }
    Ok("Agent deleted".to_string())
}

#[tauri::command]
fn list_commands() -> Vec<CommandConfig> {
    let commands_dir = get_commands_dir();
    if !commands_dir.exists() {
        return Vec::new();
    }

    let mut commands = Vec::new();
    if let Ok(entries) = fs::read_dir(&commands_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.extension().map(|e| e == "md").unwrap_or(false) {
                if let Ok(content) = fs::read_to_string(&path) {
                    let (fm, body) = parse_frontmatter(&content);
                    let filename = path.file_name()
                        .map(|n| n.to_string_lossy().to_string())
                        .unwrap_or_default();
                    commands.push(CommandConfig {
                        filename,
                        description: fm.get("description").cloned().unwrap_or_default(),
                        body: body.trim().to_string(),
                    });
                }
            }
        }
    }
    commands.sort_by(|a, b| a.filename.cmp(&b.filename));
    commands
}

#[tauri::command]
fn save_command(command: CommandConfig) -> Result<String, String> {
    let commands_dir = get_commands_dir();
    fs::create_dir_all(&commands_dir).map_err(|e| e.to_string())?;

    let content = format!(
        "---\ndescription: {}\n---\n\n{}",
        command.description, command.body
    );

    let filepath = commands_dir.join(&command.filename);
    fs::write(&filepath, content).map_err(|e| e.to_string())?;
    Ok("Command saved".to_string())
}

#[tauri::command]
fn delete_command(filename: String) -> Result<String, String> {
    let filepath = get_commands_dir().join(&filename);
    if filepath.exists() {
        fs::remove_file(&filepath).map_err(|e| e.to_string())?;
    }
    Ok("Command deleted".to_string())
}

#[tauri::command]
fn list_skills() -> Vec<SkillConfig> {
    let skills_dir = get_skills_dir();
    if !skills_dir.exists() {
        return Vec::new();
    }

    let mut skills = Vec::new();
    let entries = match fs::read_dir(&skills_dir) {
        Ok(e) => e,
        Err(_) => return skills,
    };

    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            let skill_md = path.join("SKILL.md");
            if !skill_md.is_file() {
                continue;
            }
            let content = match fs::read_to_string(&skill_md) {
                Ok(c) => c,
                Err(_) => continue,
            };
            let (fm, body) = parse_frontmatter(&content);
            let name = fm.get("name").cloned().unwrap_or_else(|| {
                path.file_name()
                    .and_then(|n| n.to_str())
                    .unwrap_or("")
                    .to_string()
            });
            let has_resources = fs::read_dir(&path)
                .map(|d| d.flatten().any(|e| e.file_name() != "SKILL.md"))
                .unwrap_or(false);
            skills.push(SkillConfig {
                name,
                description: fm.get("description").cloned().unwrap_or_default(),
                body: body.trim().to_string(),
                is_dir: true,
                has_resources,
            });
        } else if path.extension().map(|e| e == "md").unwrap_or(false) {
            let content = match fs::read_to_string(&path) {
                Ok(c) => c,
                Err(_) => continue,
            };
            let (fm, body) = parse_frontmatter(&content);
            let stem = path.file_stem()
                .and_then(|n| n.to_str())
                .unwrap_or("")
                .to_string();
            let name = fm.get("name").cloned().unwrap_or(stem);
            skills.push(SkillConfig {
                name,
                description: fm.get("description").cloned().unwrap_or_default(),
                body: body.trim().to_string(),
                is_dir: false,
                has_resources: false,
            });
        }
    }

    skills.sort_by(|a, b| a.name.cmp(&b.name));
    skills
}

fn validate_skill_name(name: &str) -> Result<(), String> {
    if name.is_empty() {
        return Err("Skill name cannot be empty".to_string());
    }
    if name.contains('/') || name.contains('\\') || name.contains("..") {
        return Err("Invalid skill name".to_string());
    }
    Ok(())
}

#[tauri::command]
fn save_skill(skill: SkillConfig) -> Result<String, String> {
    validate_skill_name(&skill.name)?;
    let skills_dir = get_skills_dir();
    fs::create_dir_all(&skills_dir).map_err(|e| e.to_string())?;

    let content = format!(
        "---\nname: {}\ndescription: {}\n---\n\n{}",
        skill.name, skill.description, skill.body.trim()
    );

    let target_dir = skills_dir.join(&skill.name);
    fs::create_dir_all(&target_dir).map_err(|e| e.to_string())?;
    let target_file = target_dir.join("SKILL.md");
    fs::write(&target_file, content).map_err(|e| e.to_string())?;
    Ok("Skill saved".to_string())
}

#[tauri::command]
fn delete_skill(name: String) -> Result<String, String> {
    validate_skill_name(&name)?;
    let skills_dir = get_skills_dir();
    let dir_path = skills_dir.join(&name);
    if dir_path.is_dir() {
        fs::remove_dir_all(&dir_path).map_err(|e| e.to_string())?;
        return Ok("Skill deleted".to_string());
    }
    let file_path = skills_dir.join(format!("{}.md", name));
    if file_path.is_file() {
        fs::remove_file(&file_path).map_err(|e| e.to_string())?;
        return Ok("Skill deleted".to_string());
    }
    Err("Skill not found".to_string())
}

#[tauri::command]
fn list_hooks() -> Vec<HookConfig> {
    let settings_file = get_settings_file();
    if !settings_file.exists() {
        return Vec::new();
    }

    let content = match fs::read_to_string(&settings_file) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let settings: serde_json::Value = match serde_json::from_str(&content) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    let mut hooks = Vec::new();

    if let Some(hooks_obj) = settings.get("hooks").and_then(|h| h.as_object()) {
        for (event, event_hooks) in hooks_obj {
            if let Some(arr) = event_hooks.as_array() {
                for hook_group in arr {
                    if let Some(hooks_arr) = hook_group.get("hooks").and_then(|h| h.as_array()) {
                        for hook in hooks_arr {
                            hooks.push(HookConfig {
                                event: event.clone(),
                                command: hook.get("command")
                                    .and_then(|c| c.as_str())
                                    .unwrap_or("")
                                    .to_string(),
                                timeout: hook.get("timeout")
                                    .and_then(|t| t.as_i64())
                                    .unwrap_or(30) as i32,
                                hook_type: hook.get("type")
                                    .and_then(|t| t.as_str())
                                    .unwrap_or("command")
                                    .to_string(),
                            });
                        }
                    }
                }
            }
        }
    }

    hooks
}

#[tauri::command]
fn list_plugins() -> Vec<PluginInfo> {
    let settings_file = get_settings_file();
    let plugins_file = get_plugins_file();

    // Load enabled status from settings.json
    let mut enabled_plugins: std::collections::HashMap<String, bool> = std::collections::HashMap::new();
    if let Ok(content) = fs::read_to_string(&settings_file) {
        if let Ok(settings) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(enabled) = settings.get("enabledPlugins").and_then(|e| e.as_object()) {
                for (name, val) in enabled {
                    if let Some(b) = val.as_bool() {
                        enabled_plugins.insert(name.clone(), b);
                    }
                }
            }
        }
    }

    // Load installed plugins
    let mut plugins = Vec::new();
    if let Ok(content) = fs::read_to_string(&plugins_file) {
        if let Ok(data) = serde_json::from_str::<serde_json::Value>(&content) {
            if let Some(plugins_obj) = data.get("plugins").and_then(|p| p.as_object()) {
                for (name, versions) in plugins_obj {
                    if let Some(arr) = versions.as_array() {
                        if let Some(latest) = arr.first() {
                            let version = latest.get("version")
                                .and_then(|v| v.as_str())
                                .unwrap_or("")
                                .to_string();
                            let enabled = enabled_plugins.get(name).copied().unwrap_or(false);
                            plugins.push(PluginInfo {
                                name: name.clone(),
                                version,
                                enabled,
                            });
                        }
                    }
                }
            }
        }
    }

    // Also add plugins from enabledPlugins that might not be in installed list
    for (name, enabled) in &enabled_plugins {
        if !plugins.iter().any(|p| &p.name == name) {
            plugins.push(PluginInfo {
                name: name.clone(),
                version: String::new(),
                enabled: *enabled,
            });
        }
    }

    plugins.sort_by(|a, b| a.name.cmp(&b.name));
    plugins
}

#[tauri::command]
fn toggle_plugin(name: String, enabled: bool) -> Result<String, String> {
    let settings_file = get_settings_file();

    let mut settings: serde_json::Value = if settings_file.exists() {
        let content = fs::read_to_string(&settings_file).map_err(|e| e.to_string())?;
        serde_json::from_str(&content).unwrap_or(serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    // Ensure enabledPlugins exists
    if settings.get("enabledPlugins").is_none() {
        settings["enabledPlugins"] = serde_json::json!({});
    }

    settings["enabledPlugins"][&name] = serde_json::json!(enabled);

    let content = serde_json::to_string_pretty(&settings).map_err(|e| e.to_string())?;
    fs::write(&settings_file, content + "\n").map_err(|e| e.to_string())?;

    Ok("Plugin toggled".to_string())
}

// === (Tasks/Kanban code removed — superseded by agents monitor) ===

// === AGENTS COMMANDS ===

#[derive(Serialize, Debug, Clone)]
struct AgentInfo {
    pid: u32,
    kind: String, // "claude" | "opencode" | "kimi" | "codex"
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
    risk: Option<String>, // "info" | "low" | "medium" | "high" | "critical"
    risk_events: Vec<security::SecurityEvent>,
    role: String,        // "Developer" | "Technical Writer" | "Architect" | ...
    role_icon: String,   // emoji for the role
    topic: Option<String>,  // short headline derived from first user message
    name: String,        // deterministic friendly name per session
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

/// Identify which AI CLI is running, if any. Returns kind name or None.
fn classify_ai_argv(argv: &str) -> Option<&'static str> {
    let argv_lc = argv.to_lowercase();
    if argv_lc.contains("grep ") || argv_lc.contains("statusline") {
        return None;
    }
    let mut tokens = argv.split_whitespace();
    let first = tokens.next().unwrap_or("");
    let first_base = std::path::Path::new(first)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("");
    let second = tokens.next().unwrap_or("");
    let second_base = std::path::Path::new(second)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("");

    // Claude Code
    if first_base == "claude"
        || argv.contains("/claude/cli")
        || argv.contains("@anthropic-ai/claude-code")
    {
        return Some("claude");
    }
    // OpenCode
    if first_base == "opencode"
        || argv.contains(".opencode/bin/opencode")
        || argv.contains("/opencode/bin/opencode")
    {
        return Some("opencode");
    }
    // Kimi (python wrapper)
    if first_base == "kimi"
        || second_base == "kimi"
        || argv.contains("kimi-cli/bin/kimi")
        || argv.contains("/.kimi/bin/")
    {
        return Some("kimi");
    }
    // Codex (node script)
    if first_base == "codex"
        || second_base == "codex"
        || argv.contains("@openai/codex")
        || argv.contains("/codex.js")
    {
        return Some("codex");
    }
    None
}

/// Returns Vec of (pid, etime_seconds, full_argv, kind).
pub(crate) fn list_ai_processes(self_pid: u32) -> Vec<(u32, u64, String, &'static str)> {
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
        let mut tokens = line.split_whitespace();
        let pid: u32 = match tokens.next().and_then(|s| s.parse().ok()) {
            Some(p) => p,
            None => continue,
        };
        if pid == self_pid {
            continue;
        }
        let etime_str = match tokens.next() { Some(s) => s, None => continue };
        let argv_parts: Vec<&str> = tokens.collect();
        if argv_parts.is_empty() {
            continue;
        }
        let argv = argv_parts.join(" ");

        let kind = match classify_ai_argv(&argv) {
            Some(k) => k,
            None => continue,
        };

        out.push((pid, parse_etime(etime_str), argv, kind));
    }
    out
}

#[derive(Default)]
struct SessionSnapshot {
    last_user_msg: Option<String>,
    first_user_msg: Option<String>,
    last_action: Option<String>,
    session_id: Option<String>,
    last_activity: Option<String>,
    /// Tally of file extensions touched by Edit/Write/Read tool calls.
    ext_counts: std::collections::HashMap<String, u32>,
    /// Tally of tool names invoked.
    tool_counts: std::collections::HashMap<String, u32>,
}

fn snapshot_session(jsonl_path: &std::path::Path) -> SessionSnapshot {
    let content = match fs::read_to_string(jsonl_path) {
        Ok(c) => c,
        Err(_) => return SessionSnapshot::default(),
    };
    let lines: Vec<&str> = content.lines().collect();
    // Read the head of the session for first_user_msg, plus the tail for
    // current activity. Cap each side so very long sessions stay cheap.
    let head_end = lines.len().min(40);
    let tail_start = lines.len().saturating_sub(400);
    let scan_ranges: Vec<&[&str]> = if tail_start > head_end {
        vec![&lines[..head_end], &lines[tail_start..]]
    } else {
        vec![&lines[..]]
    };

    let mut snap = SessionSnapshot::default();
    for tail in scan_ranges.into_iter() {
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
                if !trimmed.is_empty() && !trimmed.starts_with('<') {
                    let truncated: String = trimmed.chars().take(200).collect();
                    snap.last_user_msg = Some(truncated.clone());
                    if snap.first_user_msg.is_none() {
                        snap.first_user_msg = Some(truncated);
                    }
                }
            }
        } else if msg_type == "assistant" {
            if let Some(content) = v.get("message").and_then(|m| m.get("content")).and_then(|c| c.as_array()) {
                for item in content {
                    if item.get("type").and_then(|t| t.as_str()) == Some("tool_use") {
                        let name = item.get("name").and_then(|s| s.as_str()).unwrap_or("tool");
                        let input = item.get("input").cloned().unwrap_or(serde_json::Value::Null);
                        *snap.tool_counts.entry(name.to_string()).or_insert(0) += 1;
                        if matches!(name, "Edit" | "Write" | "Read" | "NotebookEdit") {
                            if let Some(p) = input.get("file_path").and_then(|s| s.as_str()) {
                                if let Some(ext) = std::path::Path::new(p)
                                    .extension()
                                    .and_then(|e| e.to_str())
                                {
                                    *snap.ext_counts.entry(ext.to_lowercase()).or_insert(0) += 1;
                                }
                            }
                        }
                        let target = match name {
                            "Bash" => input.get("description").and_then(|s| s.as_str())
                                .or_else(|| input.get("command").and_then(|s| s.as_str())),
                            "Read" | "Edit" | "Write" | "NotebookEdit" =>
                                input.get("file_path").and_then(|s| s.as_str()),
                            "Grep" | "Glob" =>
                                input.get("pattern").and_then(|s| s.as_str()),
                            "Agent" | "Task" | "TaskCreate" | "TaskUpdate" =>
                                input.get("description").and_then(|s| s.as_str())
                                    .or_else(|| input.get("prompt").and_then(|s| s.as_str())),
                            "WebFetch" | "WebSearch" =>
                                input.get("url").and_then(|s| s.as_str())
                                    .or_else(|| input.get("query").and_then(|s| s.as_str())),
                            _ => input.get("description").and_then(|s| s.as_str())
                                .or_else(|| input.get("file_path").and_then(|s| s.as_str()))
                                .or_else(|| input.get("command").and_then(|s| s.as_str()))
                                .or_else(|| input.get("pattern").and_then(|s| s.as_str())),
                        }.unwrap_or("");
                        let target_clean = target.split('\n').next().unwrap_or("").trim();
                        let target_short: String = target_clean.chars().take(80).collect();
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
    }
    snap
}

/// Pick a persona for the agent based on what tools and file types it
/// has been touching this session. Returns (role_label, emoji_avatar).
fn classify_role(snap: &SessionSnapshot) -> (&'static str, &'static str) {
    let docs_exts: [&str; 6] = ["md", "mdx", "rst", "txt", "adoc", "org"];
    let code_exts: [&str; 16] = [
        "ts", "tsx", "js", "jsx", "py", "rs", "go", "java", "rb",
        "php", "c", "cpp", "h", "swift", "kt", "scala",
    ];
    let infra_exts: [&str; 8] = [
        "yaml", "yml", "toml", "tf", "sh", "dockerfile", "ini", "conf",
    ];

    let mut docs = 0u32;
    let mut code = 0u32;
    let mut infra = 0u32;
    let mut total = 0u32;
    for (ext, n) in &snap.ext_counts {
        total += *n;
        if docs_exts.contains(&ext.as_str()) { docs += *n; }
        if code_exts.contains(&ext.as_str()) { code += *n; }
        if infra_exts.contains(&ext.as_str()) { infra += *n; }
    }
    let bash_n = *snap.tool_counts.get("Bash").unwrap_or(&0);
    let web_n = *snap.tool_counts.get("WebFetch").unwrap_or(&0)
        + *snap.tool_counts.get("WebSearch").unwrap_or(&0);
    let agent_n = *snap.tool_counts.get("Agent").unwrap_or(&0)
        + *snap.tool_counts.get("Task").unwrap_or(&0);
    let plan_n = *snap.tool_counts.get("ExitPlanMode").unwrap_or(&0)
        + *snap.tool_counts.get("EnterPlanMode").unwrap_or(&0);

    if total == 0 && bash_n == 0 && web_n == 0 {
        return ("Researcher", "\u{1F9D1}\u{200D}\u{1F52C}");
    }
    if plan_n > 0 || (web_n >= 3 && code == 0) {
        return ("Architect", "\u{1F9D1}\u{200D}\u{1F4BC}");
    }
    if agent_n >= 2 && code <= docs {
        return ("Orchestrator", "\u{1F9D1}\u{200D}\u{1F3A8}");
    }
    if total > 0 && docs as f32 >= (total as f32) * 0.5 {
        return ("Technical Writer", "\u{1F9D1}\u{200D}\u{1F3EB}");
    }
    if infra >= code && infra > 0 && bash_n >= total / 2 {
        return ("DevOps", "\u{1F9D1}\u{200D}\u{1F527}");
    }
    if code > 0 || total > 0 {
        return ("Developer", "\u{1F9D1}\u{200D}\u{1F4BB}");
    }
    if bash_n > 0 || web_n > 0 {
        return ("Researcher", "\u{1F9D1}\u{200D}\u{1F52C}");
    }
    ("Agent", "\u{1F916}")
}

const AGENT_NAMES: &[&str] = &[
    "Atlas", "Beckett", "Caleb", "Declan", "Elliot",
    "Felix", "Hugo", "Jasper", "Marcus", "Wren",
    "Aria", "Briony", "Camille", "Delphine", "Esme",
    "Fiona", "Hazel", "Iris", "Maeve", "Sienna",
];

fn agent_name_for(seed: &str) -> &'static str {
    // Cheap deterministic hash so the same session always gets the same name.
    let mut h: u32 = 0x811C9DC5;
    for b in seed.as_bytes() {
        h ^= *b as u32;
        h = h.wrapping_mul(0x0100_0193);
    }
    let idx = (h as usize) % AGENT_NAMES.len();
    AGENT_NAMES[idx]
}

/// Trim a first-user-message into a short shareable headline.
fn topic_from_first_msg(msg: &str) -> String {
    let cleaned: String = msg
        .lines()
        .filter(|l| {
            let t = l.trim();
            !t.is_empty() && !t.starts_with('<') && !t.starts_with('#')
        })
        .collect::<Vec<&str>>()
        .join(" ")
        .chars()
        .take(140)
        .collect();
    if cleaned.is_empty() {
        msg.chars().take(140).collect()
    } else {
        cleaned
    }
}

/// Read the timestamp of the first message in a jsonl session log.
/// Used to match running PIDs to their session by start time.
fn jsonl_first_timestamp(path: &std::path::Path) -> Option<chrono::DateTime<chrono::Utc>> {
    let content = fs::read_to_string(path).ok()?;
    for line in content.lines() {
        let v: serde_json::Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        if let Some(ts) = v.get("timestamp").and_then(|s| s.as_str()) {
            if let Ok(dt) = chrono::DateTime::parse_from_rfc3339(ts) {
                return Some(dt.with_timezone(&chrono::Utc));
            }
        }
    }
    None
}

/// All jsonls in the project dir for a cwd, with each one's first-message
/// timestamp and modification mtime. Used to match running PIDs to their
/// own session log by comparing process start_time to jsonl first-message
/// time — needed because multiple Claude agents in the same cwd otherwise
/// collapse onto whichever jsonl was last written to.
fn project_jsonls(cwd: &str) -> Vec<(PathBuf, chrono::DateTime<chrono::Utc>, std::time::SystemTime)> {
    let claude_dir = get_claude_dir();
    let project_dir = claude_dir.join("projects").join(encode_project_dir(cwd));
    let mut out = Vec::new();
    if let Ok(entries) = fs::read_dir(&project_dir) {
        for e in entries.flatten() {
            let p = e.path();
            if p.extension().and_then(|s| s.to_str()) != Some("jsonl") { continue; }
            let mtime = match e.metadata().and_then(|m| m.modified()) {
                Ok(t) => t,
                Err(_) => continue,
            };
            let first_ts = match jsonl_first_timestamp(&p) {
                Some(t) => t,
                None => continue,
            };
            out.push((p, first_ts, mtime));
        }
    }
    out
}

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

#[tauri::command]
fn list_active_agents() -> Vec<AgentInfo> {
    let self_pid = std::process::id();
    let mut agents = Vec::new();

    // Pass 1: collect proc rows and resolve cwd, branch.
    struct Row {
        pid: u32,
        etime_secs: u64,
        kind: &'static str,
        cwd: String,
        branch: Option<String>,
        started_utc: chrono::DateTime<chrono::Utc>,
    }
    let mut rows: Vec<Row> = Vec::new();
    let now_utc = chrono::Utc::now();
    for (pid, etime_secs, _argv, kind) in list_ai_processes(self_pid) {
        let cwd = match read_proc_cwd(pid) {
            Some(c) => c,
            None => continue,
        };
        let branch = std::process::Command::new("git")
            .args(["-C", &cwd, "branch", "--show-current"])
            .output()
            .ok()
            .and_then(|o| if o.status.success() {
                let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
                if s.is_empty() { None } else { Some(s) }
            } else { None });
        let started_utc = now_utc - chrono::Duration::seconds(etime_secs as i64);
        rows.push(Row { pid, etime_secs, kind, cwd, branch, started_utc });
    }

    // Pass 2: per-cwd, match each Claude PID to its own jsonl by closest
    // first-message timestamp to the PID's start time. Greedy assignment
    // so two agents in the same dir each get their own log.
    use std::collections::HashMap;
    let mut jsonl_for_pid: HashMap<u32, (PathBuf, std::time::SystemTime)> = HashMap::new();
    let mut by_cwd: HashMap<String, Vec<&Row>> = HashMap::new();
    for r in &rows {
        if r.kind == "claude" {
            by_cwd.entry(r.cwd.clone()).or_default().push(r);
        }
    }
    for (cwd, group) in by_cwd {
        let jsonls = project_jsonls(&cwd);
        if jsonls.is_empty() {
            continue;
        }
        // Build (pid, jsonl_idx, distance) candidates and pick greedily.
        let mut candidates: Vec<(u32, usize, i64, PathBuf, std::time::SystemTime)> = Vec::new();
        for r in &group {
            for (idx, (path, first_ts, mtime)) in jsonls.iter().enumerate() {
                let dist_ms = (r.started_utc - *first_ts).num_milliseconds().abs();
                candidates.push((r.pid, idx, dist_ms, path.clone(), *mtime));
            }
        }
        candidates.sort_by_key(|c| c.2);
        let mut used_jsonl: std::collections::HashSet<usize> = std::collections::HashSet::new();
        let mut used_pid: std::collections::HashSet<u32> = std::collections::HashSet::new();
        for (pid, idx, _dist, path, mtime) in candidates {
            if used_pid.contains(&pid) || used_jsonl.contains(&idx) {
                continue;
            }
            jsonl_for_pid.insert(pid, (path, mtime));
            used_pid.insert(pid);
            used_jsonl.insert(idx);
            if used_pid.len() == group.len() || used_jsonl.len() == jsonls.len() {
                break;
            }
        }
    }

    for r in rows {
        let Row { pid, etime_secs, kind, cwd, branch, .. } = r;
        let project_name = std::path::Path::new(&cwd)
            .file_name()
            .and_then(|s| s.to_str())
            .unwrap_or("?")
            .to_string();

        let (jsonl_path, snap, mtime) = if kind == "claude" {
            let resolved = jsonl_for_pid
                .remove(&pid)
                .or_else(|| newest_session_jsonl(&cwd));
            match resolved {
                Some((p, m)) => {
                    let snap = snapshot_session(&p);
                    (Some(p.to_string_lossy().to_string()), snap, Some(m))
                }
                None => (None, SessionSnapshot::default(), None),
            }
        } else {
            (None, SessionSnapshot::default(), None)
        };

        let risk = if kind == "claude" {
            jsonl_path.as_ref().and_then(|p| {
                security::scan_session_incremental(
                    std::path::Path::new(p),
                    Some(pid),
                    Some(kind),
                    Some(&cwd),
                )
            })
        } else {
            None
        };
        // Combine fresh hits with persisted recent hits for this session so the
        // badge persists past the cursor advance.
        let session_risk = snap.session_id.as_ref().and_then(|sid| {
            security::recent_max_severity_for_session(sid, 400)
        });
        let final_risk = match (risk, session_risk) {
            (Some(a), Some(b)) => Some(if a > b { a } else { b }),
            (Some(a), None) | (None, Some(a)) => Some(a),
            _ => None,
        };
        let risk_events = snap.session_id.as_deref()
            .map(|sid| security::recent_events_for_session(sid, 800, 20))
            .unwrap_or_default();

        let status = if kind == "claude" {
            classify_status(mtime).to_string()
        } else {
            "active".to_string()
        };

        let (role_label, role_icon) = classify_role(&snap);
        let topic = snap.first_user_msg.as_deref().map(topic_from_first_msg);
        let name_seed = snap.session_id.clone().unwrap_or_else(|| format!("pid:{}", pid));
        let name = agent_name_for(&name_seed).to_string();

        agents.push(AgentInfo {
            pid,
            kind: kind.to_string(),
            cwd,
            project_name,
            branch,
            status,
            started_at: started_at_from_etime(etime_secs),
            last_activity: snap.last_activity,
            last_user_msg: snap.last_user_msg,
            last_action: snap.last_action,
            session_id: snap.session_id,
            jsonl_path,
            risk: final_risk.map(|s| s.as_str().to_string()),
            risk_events,
            role: role_label.to_string(),
            role_icon: role_icon.to_string(),
            topic,
            name,
        });
    }

    agents.sort_by(|a, b| {
        let order = |s: &str| match s { "active" => 0, "idle" => 1, _ => 2 };
        order(&a.status).cmp(&order(&b.status))
            .then(b.started_at.cmp(&a.started_at))
    });
    agents
}

#[tauri::command]
fn list_security_events(limit: Option<usize>) -> Vec<security::SecurityEvent> {
    security::read_events(limit.unwrap_or(200))
}

#[tauri::command]
fn clear_security_events() -> Result<(), String> {
    security::clear_events().map_err(|e| e.to_string())
}

#[derive(Serialize, Deserialize, Debug, Clone)]
struct PendingPrompt {
    id: String,
    ts: String,
    tool: String,
    raw: serde_json::Value,
    events: Vec<serde_json::Value>,
    agent_pid: Option<u32>,
    timeout_s: Option<u64>,
}

fn pending_prompts_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security/pending-prompts")
}

fn prompt_responses_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security/prompt-responses")
}

#[tauri::command]
fn get_egress_enabled() -> bool {
    egress::is_enabled()
}

#[tauri::command]
fn set_egress_enabled(enabled: bool) -> Result<(), String> {
    let path = egress::runtime_state_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let mut state: serde_json::Value = fs::read_to_string(&path)
        .ok()
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = state.as_object_mut() {
        obj.insert("egress_enabled".to_string(), serde_json::Value::Bool(enabled));
    }
    fs::write(&path, serde_json::to_string_pretty(&state).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn list_pending_prompts() -> Vec<PendingPrompt> {
    let dir = pending_prompts_dir();
    if !dir.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    if let Ok(entries) = fs::read_dir(&dir) {
        for entry in entries.flatten() {
            if entry.path().extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            if let Ok(text) = fs::read_to_string(entry.path()) {
                if let Ok(p) = serde_json::from_str::<PendingPrompt>(&text) {
                    out.push(p);
                }
            }
        }
    }
    out.sort_by(|a, b| a.ts.cmp(&b.ts));
    out
}

#[tauri::command]
fn respond_to_prompt(id: String, decision: String) -> Result<(), String> {
    let allow = decision == "allow";
    let dir = prompt_responses_dir();
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let payload = serde_json::json!({
        "id": id,
        "decision": if allow { "allow" } else { "deny" },
        "ts": chrono::Utc::now().to_rfc3339(),
    });
    let file = dir.join(format!("{}.json", id));
    fs::write(&file, payload.to_string()).map_err(|e| e.to_string())?;
    Ok(())
}

fn synthia_python_path() -> PathBuf {
    let root = get_synthia_root();
    root.join("venv/bin/python")
}

fn security_gate_path() -> PathBuf {
    let root = get_synthia_root();
    root.join("src/synthia/hooks/security_gate.py")
}

#[tauri::command]
fn neuralguard_status() -> serde_json::Value {
    let settings = get_settings_file();
    let installed = match fs::read_to_string(&settings) {
        Ok(c) => c.contains("security_gate.py"),
        Err(_) => false,
    };
    serde_json::json!({
        "installed": installed,
        "events_path": security::events_path_for_display(),
        "policy_path": security::policy_path_for_display(),
        "gate_script": security_gate_path().to_string_lossy(),
    })
}

#[tauri::command]
fn install_neuralguard_hooks() -> Result<String, String> {
    let settings = get_settings_file();
    fs::create_dir_all(settings.parent().ok_or("no parent")?).map_err(|e| e.to_string())?;
    let mut root: serde_json::Value = if settings.exists() {
        let txt = fs::read_to_string(&settings).map_err(|e| e.to_string())?;
        serde_json::from_str(&txt).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };
    let py = synthia_python_path();
    let gate = security_gate_path();
    let cmd = format!("{} {}", py.to_string_lossy(), gate.to_string_lossy());

    let entry = serde_json::json!({
        "matcher": "",
        "hooks": [
            { "type": "command", "command": cmd, "timeout": 35 }
        ]
    });

    for event in ["PreToolUse", "PostToolUse"] {
        let hooks = root
            .as_object_mut()
            .unwrap()
            .entry("hooks")
            .or_insert_with(|| serde_json::json!({}))
            .as_object_mut()
            .ok_or("hooks not object")?;
        let arr = hooks
            .entry(event.to_string())
            .or_insert_with(|| serde_json::json!([]))
            .as_array_mut()
            .ok_or("event not array")?;
        // dedupe: drop existing security_gate entries first
        arr.retain(|item| {
            !item
                .get("hooks")
                .and_then(|h| h.as_array())
                .map(|hs| {
                    hs.iter().any(|h| {
                        h.get("command")
                            .and_then(|c| c.as_str())
                            .map(|s| s.contains("security_gate.py"))
                            .unwrap_or(false)
                    })
                })
                .unwrap_or(false)
        });
        arr.push(entry.clone());
    }

    let serialized = serde_json::to_string_pretty(&root).map_err(|e| e.to_string())?;
    fs::write(&settings, serialized).map_err(|e| e.to_string())?;
    security::ensure_dir().map_err(|e| e.to_string())?;
    Ok("NeuralGuard hooks installed".to_string())
}

#[tauri::command]
fn uninstall_neuralguard_hooks() -> Result<String, String> {
    let settings = get_settings_file();
    if !settings.exists() {
        return Ok("Nothing to remove".to_string());
    }
    let txt = fs::read_to_string(&settings).map_err(|e| e.to_string())?;
    let mut root: serde_json::Value = serde_json::from_str(&txt).map_err(|e| e.to_string())?;
    if let Some(hooks) = root.get_mut("hooks").and_then(|v| v.as_object_mut()) {
        for event in ["PreToolUse", "PostToolUse"] {
            if let Some(arr) = hooks.get_mut(event).and_then(|v| v.as_array_mut()) {
                arr.retain(|item| {
                    !item
                        .get("hooks")
                        .and_then(|h| h.as_array())
                        .map(|hs| {
                            hs.iter().any(|h| {
                                h.get("command")
                                    .and_then(|c| c.as_str())
                                    .map(|s| s.contains("security_gate.py"))
                                    .unwrap_or(false)
                            })
                        })
                        .unwrap_or(false)
                });
            }
        }
    }
    let serialized = serde_json::to_string_pretty(&root).map_err(|e| e.to_string())?;
    fs::write(&settings, serialized).map_err(|e| e.to_string())?;
    Ok("NeuralGuard hooks removed".to_string())
}

#[tauri::command]
fn scan_all_sessions() -> Result<usize, String> {
    let self_pid = std::process::id();
    let mut total = 0usize;
    for (pid, _etime, _argv, kind) in list_ai_processes(self_pid) {
        if kind != "claude" { continue; }
        let cwd = match read_proc_cwd(pid) { Some(c) => c, None => continue };
        if let Some((path, _)) = newest_session_jsonl(&cwd) {
            if security::scan_session_incremental(&path, Some(pid), Some(kind), Some(&cwd)).is_some() {
                total += 1;
            }
        }
    }
    Ok(total)
}

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
    seven_day_sonnet_pct: Option<f64>,
    seven_day_sonnet_resets_at: Option<String>,
    seven_day_sonnet_resets_in: Option<String>,
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
    seven_day_sonnet: Option<UsageWindow>,
}

#[derive(Deserialize, Debug)]
struct UsageWindow {
    utilization: Option<f64>,
    resets_at: Option<String>,
}

static USAGE_TOKEN_CACHE: Mutex<Option<(String, Instant)>> = Mutex::new(None);
static USAGE_RESPONSE_CACHE: Mutex<Option<(UsageStats, Instant)>> = Mutex::new(None);

const TOKEN_TTL: Duration = Duration::from_secs(900);
const RESPONSE_TTL: Duration = Duration::from_secs(60);
const STALE_OK: Duration = Duration::from_secs(600);

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

#[tauri::command]
fn get_usage_stats() -> UsageStats {
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
    if let Some(w) = body.seven_day_sonnet {
        stats.seven_day_sonnet_pct = w.utilization;
        if let Some(r) = w.resets_at {
            stats.seven_day_sonnet_resets_in = Some(humanize_duration_until(&r));
            stats.seven_day_sonnet_resets_at = Some(r);
        }
    }

    if let Ok(mut cache) = USAGE_RESPONSE_CACHE.lock() {
        *cache = Some((stats.clone(), Instant::now()));
    }
    stats
}

// === KNOWLEDGE META COMMANDS ===

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct KnowledgeMeta {
    pinned: Vec<String>,
    recent: Vec<String>,
    #[serde(default)]
    expanded_folders: Vec<String>,
}

fn get_knowledge_meta_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia")
        .join("knowledge-meta.json")
}

#[tauri::command]
fn get_knowledge_meta() -> KnowledgeMeta {
    let path = get_knowledge_meta_path();
    let mut meta: KnowledgeMeta = if let Ok(content) = fs::read_to_string(&path) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        return KnowledgeMeta::default();
    };

    // Filter out pinned/recent entries whose files were deleted externally
    let base = get_notes_base_path();
    let orig_pinned_len = meta.pinned.len();
    let orig_recent_len = meta.recent.len();

    meta.pinned.retain(|p| base.join(p).exists());
    meta.recent.retain(|p| base.join(p).exists());

    // Persist cleaned meta if any entries were removed
    if meta.pinned.len() != orig_pinned_len || meta.recent.len() != orig_recent_len {
        if let Ok(content) = serde_json::to_string_pretty(&meta) {
            let _ = fs::write(&path, content);
        }
    }

    meta
}

#[tauri::command]
fn save_knowledge_meta(meta: KnowledgeMeta) -> Result<String, String> {
    let path = get_knowledge_meta_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = serde_json::to_string_pretty(&meta).map_err(|e| e.to_string())?;
    fs::write(&path, content).map_err(|e| e.to_string())?;
    Ok("saved".to_string())
}

// === NOTES COMMANDS ===

fn get_notes_base_path() -> PathBuf {
    // Check NOTES_PATH env var first, then fall back to ~/dev/eventflo/docs
    if let Ok(path) = std::env::var("SYNTHIA_NOTES_PATH") {
        return PathBuf::from(path);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join("dev/eventflo/docs")
}

#[tauri::command]
fn get_notes_base_path_cmd() -> String {
    get_notes_base_path().to_string_lossy().to_string()
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct NoteEntry {
    name: String,
    path: String,
    is_dir: bool,
}

#[tauri::command]
fn list_notes(subpath: Option<String>) -> Result<Vec<NoteEntry>, String> {
    let base = get_notes_base_path();
    let target = match &subpath {
        Some(p) if !p.is_empty() => base.join(p),
        _ => base.clone(),
    };

    if !target.exists() {
        return Err("Directory not found".to_string());
    }

    if !target.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    let mut entries = Vec::new();

    if let Ok(dir_entries) = fs::read_dir(&target) {
        for entry in dir_entries.flatten() {
            let path = entry.path();
            let name = path.file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();

            // Skip hidden files
            if name.starts_with('.') {
                continue;
            }

            let is_dir = path.is_dir();

            // Only show directories and markdown files
            if is_dir || name.ends_with(".md") {
                let relative_path = path.strip_prefix(&base)
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_default();

                entries.push(NoteEntry {
                    name,
                    path: relative_path,
                    is_dir,
                });
            }
        }
    }

    // Sort: directories first, then alphabetically
    entries.sort_by(|a, b| {
        match (a.is_dir, b.is_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
        }
    });

    Ok(entries)
}

#[tauri::command]
fn read_note(path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full_path = base.join(&path);

    if !full_path.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    fs::read_to_string(&full_path)
        .map_err(|e| format!("Failed to read file: {}", e))
}

#[tauri::command]
fn get_note_preview(path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full = base.join(&path);
    if !full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }
    match std::fs::read_to_string(&full) {
        Ok(content) => {
            let preview: String = content.chars().take(200).collect();
            Ok(preview)
        }
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn get_note_modified(path: String) -> Result<u64, String> {
    let base = get_notes_base_path();
    let full = base.join(&path);
    if !full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }
    match std::fs::metadata(&full) {
        Ok(meta) => {
            match meta.modified() {
                Ok(time) => {
                    let duration = time.duration_since(std::time::UNIX_EPOCH).unwrap_or_default();
                    Ok(duration.as_secs())
                }
                Err(e) => Err(e.to_string()),
            }
        }
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
fn save_note(path: String, content: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full_path = base.join(&path);

    if !full_path.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    fs::write(&full_path, content)
        .map_err(|e| format!("Failed to save file: {}", e))?;

    Ok("Note saved".to_string())
}

#[tauri::command]
fn rename_note(old_path: String, new_path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let old_full = base.join(&old_path);
    let new_full = base.join(&new_path);

    if !old_full.starts_with(&base) || !new_full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    if !old_full.exists() {
        return Err("File not found".to_string());
    }

    if new_full.exists() {
        return Err("A file with that name already exists".to_string());
    }

    fs::rename(&old_full, &new_full)
        .map_err(|e| format!("Failed to rename file: {}", e))?;

    Ok(new_path)
}

#[tauri::command]
fn move_note(path: String, new_parent: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let old_full = base.join(&path);

    if !old_full.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    if !old_full.exists() {
        return Err("File not found".to_string());
    }

    let filename = old_full.file_name()
        .ok_or("Invalid filename")?
        .to_string_lossy()
        .to_string();

    let new_dir = if new_parent.is_empty() {
        base.clone()
    } else {
        base.join(&new_parent)
    };

    if !new_dir.starts_with(&base) {
        return Err("Invalid target path".to_string());
    }

    // Prevent moving a folder into itself
    if old_full.is_dir() && new_dir.starts_with(&old_full) {
        return Err("Cannot move a folder into itself".to_string());
    }

    let new_full = new_dir.join(&filename);

    if new_full.exists() {
        return Err("A file with that name already exists in the target folder".to_string());
    }

    fs::rename(&old_full, &new_full)
        .map_err(|e| format!("Failed to move file: {}", e))?;

    // Return the new relative path
    let new_rel = new_full.strip_prefix(&base)
        .map_err(|_| "Path error".to_string())?
        .to_string_lossy()
        .to_string();

    Ok(new_rel)
}

#[tauri::command]
fn create_folder(path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full_path = base.join(&path);

    if !full_path.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    if full_path.exists() {
        return Err("A folder with that name already exists".to_string());
    }

    fs::create_dir_all(&full_path)
        .map_err(|e| format!("Failed to create folder: {}", e))?;

    Ok("Folder created".to_string())
}

#[tauri::command]
fn delete_note(path: String) -> Result<String, String> {
    let base = get_notes_base_path();
    let full_path = base.join(&path);

    if !full_path.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    if !full_path.exists() {
        return Err("File not found".to_string());
    }

    fs::remove_file(&full_path)
        .map_err(|e| format!("Failed to delete file: {}", e))?;

    Ok("Note deleted".to_string())
}

#[tauri::command]
fn resend_to_assistant(text: String) -> Result<String, String> {
    // Use xdotool to type the text into Claude Code terminal
    // First, we'll write to a temp file that the stop hook can check
    let prompt_file = get_runtime_dir().join("synthia-resend-prompt");
    fs::write(&prompt_file, &text).map_err(|e| e.to_string())?;

    // Use xdotool to focus Claude Code window and type the text
    let _ = Command::new("xdotool")
        .args(["search", "--name", "Claude Code", "windowactivate", "--sync"])
        .output();

    // Type the text
    Command::new("xdotool")
        .args(["type", "--clearmodifiers", &text])
        .output()
        .map_err(|e| format!("Failed to type text: {}", e))?;

    // Press Enter to submit
    Command::new("xdotool")
        .args(["key", "Return"])
        .output()
        .map_err(|e| format!("Failed to press Enter: {}", e))?;

    // Clean up
    let _ = fs::remove_file(&prompt_file);

    Ok("Sent to assistant".to_string())
}

// === PINNED NOTE COMMANDS ===

fn get_pinned_note_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("pinned-note.txt")
}

#[tauri::command]
fn get_pinned_note() -> String {
    fs::read_to_string(get_pinned_note_path()).unwrap_or_default()
}

#[tauri::command]
fn save_pinned_note(content: String) -> Result<String, String> {
    let path = get_pinned_note_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("Failed to create config dir: {}", e))?;
    }
    fs::write(&path, content).map_err(|e| format!("Failed to write pinned note: {}", e))?;
    Ok("saved".to_string())
}

// === GITHUB ISSUES COMMANDS ===

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

    // Return cached data immediately unless force refresh is requested
    let cache_path = get_github_cache_path();
    if !force_refresh {
        if let Ok(content) = fs::read_to_string(&cache_path) {
            if let Ok(cache) = serde_json::from_str::<GitHubIssuesCache>(&content) {
                return GitHubIssuesResponse {
                    issues: cache.issues,
                    fetched_at: cache.fetched_at,
                    error: None,
                };
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

    // Sort by updated_at descending
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

pub fn run() {
    if !acquire_lock() {
        eprintln!("Synthia GUI is already running");
        std::process::exit(0);
    }

    egress::spawn_watcher();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Clean up any stale remote mode state from previous sessions
            let _ = fs::remove_file(get_runtime_dir().join("synthia-remote-mode"));
            let _ = Command::new("pkill")
                .args(["-f", "telegram_bot.py"])
                .output();

            // Create tray menu
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show Settings", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[
                &show,
                &quit,
            ])?;

            // Load the tray icon immediately for COSMIC/StatusNotifierItem compatibility
            let initial_icon = load_embedded_icon(TRAY_ICON_PNG)
                .unwrap_or_else(|| app.default_window_icon().unwrap().clone());

            // Create tray icon with ID so we can update it later
            let tray = TrayIconBuilder::with_id("main-tray")
                .icon(initial_icon)
                .menu(&menu)
                .tooltip("Synthia - Voice Assistant")
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "quit" => {
                            release_lock();
                            app.exit(0);
                        }
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Handle window close - hide instead of quit
            if let Some(window) = app.get_webview_window("main") {
                let window_clone = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_clone.hide();
                    }
                });
            }

            // Load tray icons - try bundled resources first, then fall back to dev path
            let resource_dir = app.path().resource_dir().unwrap_or_default();
            let dev_icons_dir = get_synthia_root().join("gui/src-tauri/icons");

            let normal_icon_path = if resource_dir.join("icons/tray-icon.png").exists() {
                resource_dir.join("icons/tray-icon.png")
            } else {
                dev_icons_dir.join("tray-icon.png")
            };

            let recording_icon_path = if resource_dir.join("icons/tray-recording.png").exists() {
                resource_dir.join("icons/tray-recording.png")
            } else {
                dev_icons_dir.join("tray-recording.png")
            };

            // Start state watcher thread for tray icon
            let app_handle = app.handle().clone();
            thread::spawn(move || {
                // Load embedded icons (more reliable across desktop environments)
                let normal_icon = load_embedded_icon(TRAY_ICON_PNG);
                let recording_icon = load_embedded_icon(TRAY_RECORDING_PNG);

                // Set initial icon immediately
                if let Some(tray) = app_handle.tray_by_id("main-tray") {
                    if let Some(ref icon) = normal_icon {
                        let _ = tray.set_icon(Some(icon.clone()));
                    }
                }

                let mut last_recording = false;

                loop {
                    let state = read_synthia_state();

                    // Update tray icon when state changes
                    if state.recording != last_recording {
                        last_recording = state.recording;

                        if let Some(tray) = app_handle.tray_by_id("main-tray") {
                            if state.recording {
                                if let Some(ref icon) = recording_icon {
                                    let _ = tray.set_icon(Some(icon.clone()));
                                    let _ = tray.set_tooltip(Some("Synthia - Recording..."));
                                }
                            } else {
                                if let Some(ref icon) = normal_icon {
                                    let _ = tray.set_icon(Some(icon.clone()));
                                    let _ = tray.set_tooltip(Some("Synthia - Voice Assistant"));
                                }
                            }
                        }
                    }

                    thread::sleep(Duration::from_millis(50));
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            start_synthia,
            stop_synthia,
            set_mode,
            show_overlay,
            hide_overlay,
            set_overlay_recording,
            start_remote_mode,
            stop_remote_mode,
            get_remote_status,
            get_history,
            clear_history,
            resend_to_assistant,
            get_hotkeys,
            save_hotkeys,
            get_word_replacements,
            save_word_replacements,
            get_clipboard_history,
            copy_from_clipboard_history,
            get_inbox_items,
            open_inbox_item,
            delete_inbox_item,
            clear_inbox,
            get_worktrees,
            resume_session,
            set_worktree_status,
            get_memory_stats,
            get_memory_entries,
            search_memory,
            update_memory_entry,
            delete_memory_entry,
            get_synthia_config,
            save_synthia_config,
            get_worktree_repos,
            save_worktree_repos,
            list_agents,
            save_agent,
            delete_agent,
            list_commands,
            save_command,
            delete_command,
            list_skills,
            save_skill,
            delete_skill,
            get_voice_muted,
            set_voice_muted,
            list_security_events,
            clear_security_events,
            scan_all_sessions,
            list_pending_prompts,
            respond_to_prompt,
            neuralguard_status,
            install_neuralguard_hooks,
            uninstall_neuralguard_hooks,
            get_egress_enabled,
            set_egress_enabled,
            list_hooks,
            list_plugins,
            toggle_plugin,
            get_knowledge_meta,
            save_knowledge_meta,
            list_notes,
            read_note,
            get_note_preview,
            get_note_modified,
            save_note,
            rename_note,
            move_note,
            create_folder,
            delete_note,
            get_usage_stats,
            get_pinned_note,
            save_pinned_note,
            get_github_config,
            save_github_config,
            get_github_issues,
            get_notes_base_path_cmd,
            list_active_agents,
            kill_agent
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

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
