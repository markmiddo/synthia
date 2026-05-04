//! Agents/commands/skills/hooks/plugins/active-agents Tauri commands.

use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{
    get_agents_dir, get_claude_dir, get_commands_dir, get_plugins_file, get_settings_file,
    get_skills_dir, parse_frontmatter, security,
};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct AgentConfig {
    filename: String,
    name: String,
    description: String,
    model: String,
    color: String,
    body: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct CommandConfig {
    filename: String,
    description: String,
    body: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct SkillConfig {
    name: String,
    description: String,
    body: String,
    is_dir: bool,
    has_resources: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct HookConfig {
    event: String,
    command: String,
    timeout: i32,
    hook_type: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct PluginInfo {
    name: String,
    version: String,
    enabled: bool,
}

#[derive(Serialize, Debug, Clone)]
pub struct AgentInfo {
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
    current_task: Option<String>, // active in-progress todo, "Doing X"
    activity: Option<String>,     // friendly verb form of latest tool call
    name: String,        // deterministic friendly name per session
}

/// Encode an absolute filesystem path the same way Claude Code does:
/// replace `/` with `-`. Leading slash → leading `-`.
/// e.g. "/home/markmiddo/dev/misc/synthia" → "-home-markmiddo-dev-misc-synthia"
pub(crate) fn encode_project_dir(cwd: &str) -> String {
    cwd.replace('/', "-")
}

/// Read /proc/<pid>/cwd symlink. Returns None on permission error.
pub(crate) fn read_proc_cwd(pid: u32) -> Option<String> {
    let link = format!("/proc/{}/cwd", pid);
    fs::read_link(&link).ok().and_then(|p| p.to_str().map(|s| s.to_string()))
}

/// Parse `ps -eo etime` (e.g. "01:23", "1-02:03:04", "1234:56") into seconds.
pub(crate) fn parse_etime(etime: &str) -> u64 {
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
pub(crate) fn classify_ai_argv(argv: &str) -> Option<&'static str> {
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
pub(crate) struct SessionSnapshot {
    last_user_msg: Option<String>,
    first_user_msg: Option<String>,
    last_action: Option<String>,
    session_id: Option<String>,
    last_activity: Option<String>,
    /// Tally of file extensions touched by Edit/Write/Read tool calls.
    ext_counts: HashMap<String, u32>,
    /// Tally of tool names invoked.
    tool_counts: HashMap<String, u32>,
    /// "Doing X" string — pulled from the latest TaskCreate/TaskUpdate
    /// in_progress todo so the agent reads as a teammate currently
    /// working on something specific instead of the verbatim first user
    /// message.
    current_task: Option<String>,
    /// Compact verb phrase derived from the most recent tool call,
    /// e.g. "Editing types.ts", "Reading config.yaml", "Running:
    /// commit + push". Falls back to last_action if a friendly form is
    /// not available.
    activity: Option<String>,
}

pub(crate) fn snapshot_session(jsonl_path: &std::path::Path) -> SessionSnapshot {
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
                        // Pull the latest in-progress todo as the current
                        // task headline. activeForm is a "doing X" sentence
                        // already written by Claude, so it reads naturally.
                        if matches!(name, "TaskCreate" | "TaskUpdate") {
                            if let Some(todos) = input.get("todos").and_then(|t| t.as_array()) {
                                let mut picked: Option<String> = None;
                                for t in todos {
                                    let status = t.get("status").and_then(|s| s.as_str()).unwrap_or("");
                                    if status == "in_progress" {
                                        let label = t.get("activeForm").and_then(|s| s.as_str())
                                            .or_else(|| t.get("content").and_then(|s| s.as_str()))
                                            .unwrap_or("");
                                        if !label.is_empty() {
                                            picked = Some(label.to_string());
                                            break;
                                        }
                                    }
                                }
                                if picked.is_none() {
                                    for t in todos.iter().rev() {
                                        if t.get("status").and_then(|s| s.as_str()) == Some("pending") {
                                            let label = t.get("content").and_then(|s| s.as_str()).unwrap_or("");
                                            if !label.is_empty() {
                                                picked = Some(label.to_string());
                                                break;
                                            }
                                        }
                                    }
                                }
                                if picked.is_some() {
                                    snap.current_task = picked;
                                }
                            }
                        }
                        // Friendly verb form so the right column reads
                        // "Editing types.ts" instead of "Bash: Read:
                        // /long/path/types.ts".
                        let activity = match name {
                            "Bash" => input.get("description").and_then(|s| s.as_str())
                                .map(|d| d.to_string())
                                .or_else(|| input.get("command").and_then(|s| s.as_str())
                                    .map(|c| {
                                        let first_token = c.split_whitespace().next().unwrap_or("cmd");
                                        format!("Running {}", first_token)
                                    })),
                            "Read" => input.get("file_path").and_then(|s| s.as_str())
                                .map(|p| format!("Reading {}", basename(p))),
                            "Edit" | "MultiEdit" => input.get("file_path").and_then(|s| s.as_str())
                                .map(|p| format!("Editing {}", basename(p))),
                            "Write" | "NotebookEdit" => input.get("file_path").and_then(|s| s.as_str())
                                .map(|p| format!("Writing {}", basename(p))),
                            "Grep" => input.get("pattern").and_then(|s| s.as_str())
                                .map(|p| format!("Searching for {}", p)),
                            "Glob" => input.get("pattern").and_then(|s| s.as_str())
                                .map(|p| format!("Listing {}", p)),
                            "WebFetch" => input.get("url").and_then(|s| s.as_str())
                                .map(|u| format!("Fetching {}", short_host(u))),
                            "WebSearch" => input.get("query").and_then(|s| s.as_str())
                                .map(|q| format!("Searching web: {}", q)),
                            "Agent" | "Task" | "TaskCreate" | "TaskUpdate" => input.get("description")
                                .and_then(|s| s.as_str())
                                .map(|d| format!("Planning: {}", d))
                                .or_else(|| Some("Updating tasks".to_string())),
                            other => Some(other.to_string()),
                        };
                        if let Some(a) = activity {
                            let trimmed: String = a.split('\n').next().unwrap_or("").trim().chars().take(80).collect();
                            if !trimmed.is_empty() {
                                snap.activity = Some(trimmed);
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
pub(crate) fn classify_role(snap: &SessionSnapshot) -> (&'static str, &'static str) {
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

pub(crate) fn agent_name_for(seed: &str) -> &'static str {
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
pub(crate) fn topic_from_first_msg(msg: &str) -> String {
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
pub(crate) fn basename(path: &str) -> String {
    std::path::Path::new(path)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(path)
        .to_string()
}

pub(crate) fn short_host(url: &str) -> String {
    let after_scheme = url.split("://").nth(1).unwrap_or(url);
    after_scheme.split('/').next().unwrap_or(after_scheme).to_string()
}

pub(crate) fn jsonl_first_timestamp(path: &std::path::Path) -> Option<chrono::DateTime<chrono::Utc>> {
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
pub(crate) fn project_jsonls(cwd: &str) -> Vec<(PathBuf, chrono::DateTime<chrono::Utc>, std::time::SystemTime)> {
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

pub(crate) fn newest_session_jsonl(cwd: &str) -> Option<(PathBuf, std::time::SystemTime)> {
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

pub(crate) fn classify_status(mtime: Option<std::time::SystemTime>) -> &'static str {
    let now = std::time::SystemTime::now();
    match mtime.and_then(|m| now.duration_since(m).ok()) {
        Some(d) if d.as_secs() < 30 => "active",
        Some(d) if d.as_secs() < 300 => "idle",
        _ => "stale",
    }
}

pub(crate) fn started_at_from_etime(etime_secs: u64) -> String {
    let started = chrono::Local::now() - chrono::Duration::seconds(etime_secs as i64);
    started.to_rfc3339()
}

/// Validate a skill / agent / command file or directory name.
///
/// Delegates filesystem-traversal checks to `paths::validate_filename` and
/// adds a length cap so a malicious payload can't blow out filesystem limits.
pub(crate) fn validate_skill_name(name: &str) -> AppResult<()> {
    crate::paths::validate_filename(name)?;
    if name.len() > 64 {
        return Err(AppError::Validation("name too long (max 64)".to_string()));
    }
    Ok(())
}

#[tauri::command]
pub fn list_agents() -> Vec<AgentConfig> {
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
pub fn save_agent(agent: AgentConfig) -> AppResult<String> {
    validate_skill_name(&agent.filename)?;
    let agents_dir = get_agents_dir();
    fs::create_dir_all(&agents_dir)?;

    let content = format!(
        "---\nname: {}\ndescription: {}\nmodel: {}\ncolor: {}\n---\n\n{}",
        agent.name, agent.description, agent.model, agent.color, agent.body
    );

    let filepath = crate::paths::safe_new_file(&agents_dir, "", &agent.filename)?;
    fs::write(&filepath, content)?;
    Ok("Agent saved".to_string())
}

#[tauri::command]
pub fn delete_agent(filename: String) -> AppResult<String> {
    validate_skill_name(&filename)?;
    let agents_dir = get_agents_dir();
    let filepath = agents_dir.join(&filename);
    if filepath.exists() {
        // Confirm canonicalized path stays under agents_dir before unlinking.
        let resolved = crate::paths::safe_join(&agents_dir, &filename)?;
        fs::remove_file(&resolved)?;
    }
    Ok("Agent deleted".to_string())
}

#[tauri::command]
pub fn list_commands() -> Vec<CommandConfig> {
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
pub fn save_command(command: CommandConfig) -> AppResult<String> {
    validate_skill_name(&command.filename)?;
    let commands_dir = get_commands_dir();
    fs::create_dir_all(&commands_dir)?;

    let content = format!(
        "---\ndescription: {}\n---\n\n{}",
        command.description, command.body
    );

    let filepath = crate::paths::safe_new_file(&commands_dir, "", &command.filename)?;
    fs::write(&filepath, content)?;
    Ok("Command saved".to_string())
}

#[tauri::command]
pub fn delete_command(filename: String) -> AppResult<String> {
    validate_skill_name(&filename)?;
    let commands_dir = get_commands_dir();
    let filepath = commands_dir.join(&filename);
    if filepath.exists() {
        let resolved = crate::paths::safe_join(&commands_dir, &filename)?;
        fs::remove_file(&resolved)?;
    }
    Ok("Command deleted".to_string())
}

#[tauri::command]
pub fn list_skills() -> Vec<SkillConfig> {
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

#[tauri::command]
pub fn save_skill(skill: SkillConfig) -> AppResult<String> {
    validate_skill_name(&skill.name)?;
    let skills_dir = get_skills_dir();
    fs::create_dir_all(&skills_dir)?;

    let content = format!(
        "---\nname: {}\ndescription: {}\n---\n\n{}",
        skill.name, skill.description, skill.body.trim()
    );

    // Confirm the target directory lands under skills_dir before writing.
    let skills_canonical = skills_dir
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize skills_dir: {}", e)))?;
    let target_dir = skills_canonical.join(&skill.name);
    fs::create_dir_all(&target_dir)?;
    let target_file = target_dir.join("SKILL.md");
    fs::write(&target_file, content)?;
    Ok("Skill saved".to_string())
}

#[tauri::command]
pub fn delete_skill(name: String) -> AppResult<String> {
    validate_skill_name(&name)?;
    let skills_dir = get_skills_dir();
    let dir_path = skills_dir.join(&name);
    if dir_path.is_dir() {
        let resolved = crate::paths::safe_join(&skills_dir, &name)?;
        fs::remove_dir_all(&resolved)?;
        return Ok("Skill deleted".to_string());
    }
    let file_basename = format!("{}.md", name);
    let file_path = skills_dir.join(&file_basename);
    if file_path.is_file() {
        let resolved = crate::paths::safe_join(&skills_dir, &file_basename)?;
        fs::remove_file(&resolved)?;
        return Ok("Skill deleted".to_string());
    }
    Err(AppError::NotFound("Skill not found".to_string()))
}

#[tauri::command]
pub fn list_hooks() -> Vec<HookConfig> {
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
pub fn list_plugins() -> Vec<PluginInfo> {
    let settings_file = get_settings_file();
    let plugins_file = get_plugins_file();

    // Load enabled status from settings.json
    let mut enabled_plugins: HashMap<String, bool> = HashMap::new();
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
pub fn toggle_plugin(name: String, enabled: bool) -> AppResult<String> {
    let settings_file = get_settings_file();

    let mut settings: serde_json::Value = if settings_file.exists() {
        let content = fs::read_to_string(&settings_file)?;
        serde_json::from_str(&content).unwrap_or(serde_json::json!({}))
    } else {
        serde_json::json!({})
    };

    // Ensure enabledPlugins exists
    if settings.get("enabledPlugins").is_none() {
        settings["enabledPlugins"] = serde_json::json!({});
    }

    settings["enabledPlugins"][&name] = serde_json::json!(enabled);

    let content = serde_json::to_string_pretty(&settings)?;
    fs::write(&settings_file, content + "\n")?;

    Ok("Plugin toggled".to_string())
}

#[tauri::command]
pub fn list_active_agents() -> Vec<AgentInfo> {
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
            current_task: snap.current_task,
            activity: snap.activity,
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
pub fn kill_agent(pid: u32) -> AppResult<()> {
    let status = std::process::Command::new("kill")
        .arg(pid.to_string())
        .status()
        .map_err(|e| AppError::Process(format!("Failed to spawn kill: {}", e)))?;
    if !status.success() {
        return Err(AppError::Process(format!(
            "kill exited with status {:?}",
            status.code()
        )));
    }
    Ok(())
}

#[tauri::command]
pub fn scan_all_sessions() -> AppResult<usize> {
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

#[cfg(test)]
mod tests {
    #[test]
    fn validate_skill_name_rejects_traversal() {
        assert!(super::validate_skill_name("../escape").is_err());
        assert!(super::validate_skill_name("foo/bar").is_err());
        assert!(super::validate_skill_name(".env").is_err());
        assert!(super::validate_skill_name("").is_err());
    }

    #[test]
    fn validate_skill_name_accepts_normal() {
        assert!(super::validate_skill_name("my-skill").is_ok());
        assert!(super::validate_skill_name("skill_v2").is_ok());
    }

    #[test]
    fn validate_skill_name_rejects_too_long() {
        let long = "a".repeat(65);
        assert!(super::validate_skill_name(&long).is_err());
        let ok_len = "a".repeat(64);
        assert!(super::validate_skill_name(&ok_len).is_ok());
    }

    #[test]
    fn etime_parses_mm_ss() {
        assert_eq!(super::parse_etime("01:23"), 83);
    }

    #[test]
    fn etime_parses_hh_mm_ss() {
        assert_eq!(super::parse_etime("1:02:03"), 3723);
    }

    #[test]
    fn etime_parses_days() {
        assert_eq!(
            super::parse_etime("2-03:04:05"),
            2 * 86400 + 3 * 3600 + 4 * 60 + 5
        );
    }

    #[test]
    fn encodes_project_dir() {
        assert_eq!(
            super::encode_project_dir("/home/markmiddo/dev/misc/synthia"),
            "-home-markmiddo-dev-misc-synthia"
        );
    }
}
