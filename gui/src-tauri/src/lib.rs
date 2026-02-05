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
use std::time::Duration;
use serde::{Deserialize, Serialize};

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
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
    PathBuf::from(home).join(".config/synthia/worktrees.yaml")
}

fn get_claude_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
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

    let child = Command::new("/home/markmiddo/dev/misc/synthia/run.sh")
        .current_dir("/home/markmiddo/dev/misc/synthia")
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

    // Create the remote mode flag file with chat ID (enables response forwarding to Telegram)
    // Chat ID is needed by send_telegram.py to know where to send messages
    let _ = fs::write("/tmp/synthia-remote-mode", "537808338");

    // Start the telegram bot with CUDA disabled
    Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args(["/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py"])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .env("CUDA_VISIBLE_DEVICES", "")
        .spawn()
        .map_err(|e| format!("Failed to start remote mode: {}", e))?;

    // Send notification in background (don't block UI)
    let _ = Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args([
            "/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py",
            "--notify",
            "🟢 *Remote Mode ENABLED*\n\nYou can now control Claude Code via Telegram."
        ])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .spawn();

    Ok("Remote mode started".to_string())
}

#[tauri::command]
fn stop_remote_mode() -> Result<String, String> {
    // Remove the remote mode flag file (stops response forwarding to Telegram)
    let _ = fs::remove_file("/tmp/synthia-remote-mode");

    // Kill the bot immediately for instant UI response
    let _ = Command::new("pkill")
        .args(["-f", "telegram_bot.py"])
        .output();

    // Send notification in background (after bot is killed, uses --notify which is standalone)
    let _ = Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args([
            "/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py",
            "--notify",
            "🔴 *Remote Mode DISABLED*\n\nTelegram bot stopped."
        ])
        .current_dir("/home/markmiddo/dev/misc/synthia")
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
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
    PathBuf::from(home).join(".config/synthia/config.yaml")
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
    let signal_file = PathBuf::from("/tmp/synthia-reload-config");
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
    let signal_file = PathBuf::from("/tmp/synthia-reload-config");
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

// === TASKS COMMANDS ===

#[derive(Deserialize, Serialize, Debug, Clone)]
struct Task {
    id: String,
    title: String,
    description: Option<String>,
    status: String,  // "todo", "in_progress", "done"
    tags: Vec<String>,
    due_date: Option<String>,
    created_at: String,
    completed_at: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct TasksData {
    tasks: Vec<Task>,
}

fn get_tasks_file() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia")
        .join("tasks.json")
}

fn load_tasks() -> TasksData {
    let path = get_tasks_file();
    if let Ok(content) = fs::read_to_string(&path) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        TasksData::default()
    }
}

fn save_tasks(data: &TasksData) -> Result<(), String> {
    let path = get_tasks_file();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let content = serde_json::to_string_pretty(data).map_err(|e| e.to_string())?;
    fs::write(&path, content).map_err(|e| e.to_string())
}

#[tauri::command]
fn list_tasks() -> Vec<Task> {
    load_tasks().tasks
}

#[tauri::command]
fn add_task(
    title: String,
    description: Option<String>,
    tags: Vec<String>,
    due_date: Option<String>,
) -> Result<Task, String> {
    let mut data = load_tasks();

    let task = Task {
        id: uuid::Uuid::new_v4().to_string(),
        title,
        description,
        status: "todo".to_string(),
        tags,
        due_date,
        created_at: chrono::Utc::now().to_rfc3339(),
        completed_at: None,
    };

    data.tasks.push(task.clone());
    save_tasks(&data)?;
    Ok(task)
}

#[tauri::command]
fn update_task(
    id: String,
    title: Option<String>,
    description: Option<String>,
    tags: Option<Vec<String>>,
    due_date: Option<String>,
    status: Option<String>,
) -> Result<Task, String> {
    let mut data = load_tasks();

    let task = data.tasks.iter_mut()
        .find(|t| t.id == id)
        .ok_or("Task not found")?;

    if let Some(t) = title {
        task.title = t;
    }
    if let Some(d) = description {
        task.description = Some(d);
    }
    if let Some(t) = tags {
        task.tags = t;
    }
    if due_date.is_some() {
        task.due_date = due_date;
    }
    if let Some(s) = status {
        if s == "done" && task.status != "done" {
            task.completed_at = Some(chrono::Utc::now().to_rfc3339());
        } else if s != "done" {
            task.completed_at = None;
        }
        task.status = s;
    }

    let updated = task.clone();
    save_tasks(&data)?;
    Ok(updated)
}

#[tauri::command]
fn delete_task(id: String) -> Result<String, String> {
    let mut data = load_tasks();
    let initial_len = data.tasks.len();
    data.tasks.retain(|t| t.id != id);

    if data.tasks.len() == initial_len {
        return Err("Task not found".to_string());
    }

    save_tasks(&data)?;
    Ok("Task deleted".to_string())
}

#[tauri::command]
fn move_task(id: String, status: String) -> Result<Task, String> {
    update_task(id, None, None, None, None, Some(status))
}

// === USAGE COMMANDS ===

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct UsageStats {
    today_messages: u64,
    today_tokens: u64,
    today_sessions: u64,
    week_messages: u64,
    week_tokens: u64,
    week_sessions: u64,
    subscription_type: String,
}

#[derive(Deserialize, Debug)]
struct DailyActivity {
    date: String,
    #[serde(rename = "messageCount")]
    message_count: u64,
    #[serde(rename = "sessionCount")]
    session_count: u64,
}

#[derive(Deserialize, Debug)]
struct DailyModelTokens {
    date: String,
    #[serde(rename = "tokensByModel")]
    tokens_by_model: std::collections::HashMap<String, u64>,
}

#[derive(Deserialize, Debug)]
struct StatsCache {
    #[serde(rename = "dailyActivity")]
    daily_activity: Option<Vec<DailyActivity>>,
    #[serde(rename = "dailyModelTokens")]
    daily_model_tokens: Option<Vec<DailyModelTokens>>,
}

#[derive(Deserialize, Debug)]
struct Credentials {
    #[serde(rename = "claudeAiOauth")]
    claude_ai_oauth: Option<CredentialsOAuth>,
}

#[derive(Deserialize, Debug)]
struct CredentialsOAuth {
    #[serde(rename = "subscriptionType")]
    subscription_type: Option<String>,
}

#[tauri::command]
fn get_usage_stats() -> UsageStats {
    let claude_dir = get_claude_dir();
    let stats_file = claude_dir.join("stats-cache.json");
    let creds_file = claude_dir.join(".credentials.json");
    let projects_dir = claude_dir.join("projects");

    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    let today_start = chrono::Local::now()
        .date_naive()
        .and_hms_opt(0, 0, 0)
        .unwrap();

    // Calculate the date 7 days ago
    let week_ago = (chrono::Local::now() - chrono::Duration::days(7))
        .format("%Y-%m-%d")
        .to_string();

    let mut stats = UsageStats::default();

    // Get subscription type
    if let Ok(content) = fs::read_to_string(&creds_file) {
        if let Ok(creds) = serde_json::from_str::<Credentials>(&content) {
            if let Some(oauth) = creds.claude_ai_oauth {
                stats.subscription_type = oauth.subscription_type.unwrap_or_default();
            }
        }
    }

    // Get cached stats for weekly totals
    if let Ok(content) = fs::read_to_string(&stats_file) {
        if let Ok(cache) = serde_json::from_str::<StatsCache>(&content) {
            // Process daily activity for weekly totals
            if let Some(activities) = cache.daily_activity {
                for activity in &activities {
                    if activity.date >= week_ago && activity.date != today {
                        stats.week_messages += activity.message_count;
                        stats.week_sessions += activity.session_count;
                    }
                }
            }

            // Process token usage for weekly totals
            if let Some(tokens) = cache.daily_model_tokens {
                for day in &tokens {
                    let day_total: u64 = day.tokens_by_model.values().sum();
                    if day.date >= week_ago && day.date != today {
                        stats.week_tokens += day_total;
                    }
                }
            }
        }
    }

    // Calculate today's stats from actual session files
    if projects_dir.exists() {
        let today_start_time = std::time::SystemTime::from(
            std::time::UNIX_EPOCH + std::time::Duration::from_secs(
                today_start.and_utc().timestamp() as u64
            )
        );

        // Walk through all project directories
        if let Ok(project_entries) = fs::read_dir(&projects_dir) {
            for project_entry in project_entries.flatten() {
                let project_path = project_entry.path();
                if !project_path.is_dir() {
                    continue;
                }

                // Session files are directly in project folder as UUID.jsonl
                if let Ok(session_entries) = fs::read_dir(&project_path) {
                    for session_entry in session_entries.flatten() {
                        let session_path = session_entry.path();

                        // Only process .jsonl files (not directories)
                        if session_path.is_file() {
                            if let Some(ext) = session_path.extension() {
                                if ext == "jsonl" {
                                    if let Ok(metadata) = session_path.metadata() {
                                        if let Ok(modified) = metadata.modified() {
                                            if modified >= today_start_time {
                                                // Parse this file for today's usage
                                                if let Ok(content) = fs::read_to_string(&session_path) {
                                                    for line in content.lines() {
                                                        if let Ok(data) = serde_json::from_str::<serde_json::Value>(line) {
                                                            // Count assistant messages and extract usage
                                                            if data.get("type").and_then(|t| t.as_str()) == Some("assistant") {
                                                                if let Some(msg) = data.get("message") {
                                                                    stats.today_messages += 1;
                                                                    if let Some(usage) = msg.get("usage") {
                                                                        let output = usage.get("output_tokens")
                                                                            .and_then(|v| v.as_u64())
                                                                            .unwrap_or(0);
                                                                        stats.today_tokens += output;
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    // Add today's stats to weekly totals
    stats.week_messages += stats.today_messages;
    stats.week_tokens += stats.today_tokens;

    stats
}

// === NOTES COMMANDS ===

const NOTES_BASE_PATH: &str = "/home/markmiddo/dev/eventflo/docs";

#[derive(Deserialize, Serialize, Debug, Clone)]
struct NoteEntry {
    name: String,
    path: String,
    is_dir: bool,
}

#[tauri::command]
fn list_notes(subpath: Option<String>) -> Result<Vec<NoteEntry>, String> {
    let base = PathBuf::from(NOTES_BASE_PATH);
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
    let base = PathBuf::from(NOTES_BASE_PATH);
    let full_path = base.join(&path);

    if !full_path.starts_with(&base) {
        return Err("Invalid path".to_string());
    }

    fs::read_to_string(&full_path)
        .map_err(|e| format!("Failed to read file: {}", e))
}

#[tauri::command]
fn save_note(path: String, content: String) -> Result<String, String> {
    let base = PathBuf::from(NOTES_BASE_PATH);
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
    let base = PathBuf::from(NOTES_BASE_PATH);
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
fn resend_to_assistant(text: String) -> Result<String, String> {
    // Use xdotool to type the text into Claude Code terminal
    // First, we'll write to a temp file that the stop hook can check
    let prompt_file = PathBuf::from("/tmp/synthia-resend-prompt");
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

pub fn run() {
    if !acquire_lock() {
        eprintln!("Synthia GUI is already running");
        std::process::exit(0);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Clean up any stale remote mode state from previous sessions
            let _ = fs::remove_file("/tmp/synthia-remote-mode");
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
            let dev_icons_dir = PathBuf::from("/home/markmiddo/dev/misc/synthia/gui/src-tauri/icons");

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
            list_hooks,
            list_plugins,
            toggle_plugin,
            list_notes,
            read_note,
            save_note,
            rename_note,
            get_usage_stats,
            list_tasks,
            add_task,
            update_task,
            delete_task,
            move_task
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
