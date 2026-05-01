//! NeuralGuard security layer.
//!
//! Phase 1 (rules-based): scans tool_use entries from Claude session jsonl,
//! emits SecurityEvent records when a rule matches, persists them to
//! ~/.config/synthia/security/events.jsonl, and exposes Tauri commands.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Serialize, Deserialize, Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
#[serde(rename_all = "lowercase")]
pub enum Severity {
    Info,
    Low,
    Medium,
    High,
    Critical,
}

impl Severity {
    pub fn as_str(&self) -> &'static str {
        match self {
            Severity::Info => "info",
            Severity::Low => "low",
            Severity::Medium => "medium",
            Severity::High => "high",
            Severity::Critical => "critical",
        }
    }
}

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct SecurityEvent {
    pub id: String,
    pub ts: String,
    pub agent_pid: Option<u32>,
    pub agent_kind: Option<String>,
    pub agent_cwd: Option<String>,
    pub session_id: Option<String>,
    pub tool: String,
    pub rule: String,
    pub severity: Severity,
    pub matched: String,
    pub raw: Value,
    pub decision: String,
    pub actor: String,
}

pub struct RuleHit {
    pub rule: &'static str,
    pub severity: Severity,
    pub matched: String,
}

fn security_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security")
}

fn events_path() -> PathBuf {
    security_dir().join("events.jsonl")
}

fn cursor_path() -> PathBuf {
    security_dir().join("cursors.json")
}

pub fn ensure_dir() -> std::io::Result<()> {
    fs::create_dir_all(security_dir())
}

pub fn events_path_for_display() -> String {
    events_path().to_string_lossy().to_string()
}

pub fn policy_path_for_display() -> String {
    security_dir().join("policy.yaml").to_string_lossy().to_string()
}

/// Returns Vec<RuleHit> for a given tool_use input. Empty on clean.
pub fn evaluate_tool(tool: &str, input: &Value) -> Vec<RuleHit> {
    let mut hits = Vec::new();
    match tool {
        "Bash" => {
            if let Some(cmd) = input.get("command").and_then(|v| v.as_str()) {
                hits.extend(evaluate_bash(cmd));
            }
        }
        "Write" | "Edit" | "NotebookEdit" => {
            if let Some(path) = input.get("file_path").and_then(|v| v.as_str()) {
                hits.extend(evaluate_write(path));
            }
        }
        "Read" => {
            if let Some(path) = input.get("file_path").and_then(|v| v.as_str()) {
                hits.extend(evaluate_read(path));
            }
        }
        "WebFetch" => {
            if let Some(url) = input.get("url").and_then(|v| v.as_str()) {
                hits.extend(evaluate_fetch(url));
            }
        }
        _ => {}
    }
    hits
}

// Binaries whose args are usually quoted strings or scripts, not real
// commands. Skip binary-bound rules for the entire statement when one of
// these is the head binary.
fn is_quoting_binary(name: &str) -> bool {
    matches!(
        name,
        "echo" | "printf" | "gh" | "git" | "jq" | "awk" | "sed"
            | "python" | "python3" | "node" | "ruby" | "perl"
    )
}

fn split_statements(cmd: &str) -> Vec<&str> {
    // Split on `;`, `&&`, `||`. NOT on `|` — pipelines remain intact for
    // statement-level rules.
    let mut out = Vec::new();
    let bytes = cmd.as_bytes();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < bytes.len() {
        let b = bytes[i];
        let split_len = if b == b';' {
            1
        } else if i + 1 < bytes.len()
            && ((b == b'&' && bytes[i + 1] == b'&')
                || (b == b'|' && bytes[i + 1] == b'|'))
        {
            2
        } else {
            0
        };
        if split_len > 0 {
            let part = cmd[start..i].trim();
            if !part.is_empty() {
                out.push(part);
            }
            i += split_len;
            start = i;
            continue;
        }
        i += 1;
    }
    let last = cmd[start..].trim();
    if !last.is_empty() {
        out.push(last);
    }
    out
}

fn split_pipeline(stmt: &str) -> Vec<&str> {
    // Split on `|` but skip `||`.
    let mut out = Vec::new();
    let bytes = stmt.as_bytes();
    let mut start = 0usize;
    let mut i = 0usize;
    while i < bytes.len() {
        if bytes[i] == b'|' && (i + 1 >= bytes.len() || bytes[i + 1] != b'|')
            && (i == 0 || bytes[i - 1] != b'|')
        {
            let part = stmt[start..i].trim();
            if !part.is_empty() {
                out.push(part);
            }
            i += 1;
            start = i;
            continue;
        }
        i += 1;
    }
    let last = stmt[start..].trim();
    if !last.is_empty() {
        out.push(last);
    }
    out
}

fn shlex_split(s: &str) -> Vec<String> {
    let mut out: Vec<String> = Vec::new();
    let mut cur = String::new();
    let mut in_single = false;
    let mut in_double = false;
    let mut chars = s.chars().peekable();
    while let Some(c) = chars.next() {
        match c {
            '\'' if !in_double => in_single = !in_single,
            '"' if !in_single => in_double = !in_double,
            '\\' if !in_single => {
                if let Some(&next) = chars.peek() {
                    cur.push(next);
                    chars.next();
                }
            }
            c if c.is_whitespace() && !in_single && !in_double => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
            _ => cur.push(c),
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

fn is_env_assign(tok: &str) -> bool {
    let bytes = tok.as_bytes();
    if bytes.is_empty() {
        return false;
    }
    let first = bytes[0];
    if !(first.is_ascii_alphabetic() || first == b'_') {
        return false;
    }
    for (i, &b) in bytes.iter().enumerate() {
        if b == b'=' {
            return i > 0;
        }
        if !(b.is_ascii_alphanumeric() || b == b'_') {
            return false;
        }
    }
    false
}

fn binary_of(segment: &str) -> Option<(String, String)> {
    let mut tokens = shlex_split(segment);
    while !tokens.is_empty() && is_env_assign(&tokens[0]) {
        tokens.remove(0);
    }
    if tokens.is_empty() {
        return None;
    }
    let bin_full = tokens.remove(0);
    let basename = std::path::Path::new(&bin_full)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(&bin_full)
        .to_string();
    Some((basename, tokens.join(" ")))
}

// (rule, severity, &[binary basenames], optional arg-pattern)
type BinRule = (&'static str, Severity, &'static [&'static str], Option<&'static str>);

const BASH_RULES: &[BinRule] = &[
    ("destructive-rm", Severity::Critical, &["rm"], Some(r"-[rR]f?\b.*(?:^|\s)(/|~|\$home|--no-preserve-root)")),
    ("dd-block-device", Severity::Critical, &["dd"], Some(r"of=/dev/(sd|nvme|hd)")),
    ("setuid-bit", Severity::High, &["chmod"], Some(r"\+s\b")),
    ("setcap", Severity::High, &["setcap"], None),
    ("ssh-key-access", Severity::High, &["cat", "less", "more", "head", "tail", "cp", "mv", "rm"], Some(r"~?/?\.ssh/(id_|authorized_keys|known_hosts)")),
    ("gpg-access", Severity::High, &["cat", "less", "more", "head", "tail", "cp", "mv", "rm", "tar", "zip"], Some(r"~?/?\.gnupg/")),
    ("aws-credentials", Severity::High, &["cat", "less", "more", "head", "tail", "cp", "mv"], Some(r"~?/?\.aws/credentials")),
    ("secret-exfil", Severity::Critical, &["curl", "wget", "scp", "rsync"], Some(r"(\.ssh|\.aws|\.gnupg|credentials|secret|token|api[_-]?key)")),
    ("mass-kill", Severity::Medium, &["pkill", "killall"], Some(r"-9\b")),
    ("git-remote-rewrite", Severity::Medium, &["git"], Some(r"\bremote\s+(set-url|add)\s+\S+\s+(https?:|git@)")),
    ("history-tamper", Severity::Medium, &["history"], Some(r"-c\b")),
];

const STMT_RULES: &[(&'static str, Severity, &'static str)] = &[
    ("pipe-to-shell", Severity::Critical, r"(?:^|[\s;&|])(curl|wget|fetch)\b[^|]*\|\s*(sh|bash|zsh|fish)\b"),
    ("base64-exec", Severity::Critical, r"\bbase64\s+(-d|--decode)\b[^|]*\|\s*(sh|bash|python|node)\b"),
    ("shell-rc-tamper", Severity::High, r">>?\s*~?/?\.(bashrc|zshrc|profile|bash_profile|zprofile)\b"),
    ("history-redir-tamper", Severity::Medium, r">\s*~?/?\.(bash_history|zsh_history)\b"),
    ("sudo", Severity::High, r"(?:^|[\s;&|])sudo\b"),
];

fn evaluate_bash(cmd: &str) -> Vec<RuleHit> {
    let mut hits: Vec<RuleHit> = Vec::new();
    let mut seen: std::collections::HashSet<(String, String)> = std::collections::HashSet::new();

    let mut emit = |rule: &'static str, sev: Severity, matched: String,
                    seen: &mut std::collections::HashSet<(String, String)>,
                    hits: &mut Vec<RuleHit>| {
        let key = (rule.to_string(), matched.clone());
        if seen.insert(key) {
            hits.push(RuleHit { rule, severity: sev, matched });
        }
    };

    let lower_full = cmd.to_lowercase();
    for stmt in split_statements(&lower_full) {
        // statement-level rules (full pipeline visible)
        for (rule, sev, pat) in STMT_RULES {
            if let Ok(re) = regex::Regex::new(pat) {
                if let Some(m) = re.find(stmt) {
                    emit(rule, *sev, m.as_str().to_string(), &mut seen, &mut hits);
                }
            }
        }

        let head = binary_of(stmt).map(|(b, _)| b);
        if head.as_deref().map(is_quoting_binary).unwrap_or(false) {
            continue;
        }

        for stage in split_pipeline(stmt) {
            let (binary, args) = match binary_of(stage) {
                Some(t) => t,
                None => continue,
            };
            if is_quoting_binary(&binary) {
                continue;
            }
            for (rule, sev, bins, pat) in BASH_RULES {
                if !bins.contains(&binary.as_str()) {
                    continue;
                }
                let matched = match pat {
                    None => binary.clone(),
                    Some(p) => match regex::Regex::new(p)
                        .ok()
                        .and_then(|r| r.find(&args).map(|m| m.as_str().to_string()))
                    {
                        Some(s) => s,
                        None => continue,
                    },
                };
                emit(rule, *sev, matched, &mut seen, &mut hits);
            }
        }
    }
    hits
}

fn evaluate_write(path: &str) -> Vec<RuleHit> {
    let lower = path.to_lowercase();
    let mut hits = Vec::new();
    if regex_match(&lower, r"\.ssh/(id_|authorized_keys)") {
        hits.push(RuleHit { rule: "ssh-key-write", severity: Severity::Critical, matched: path.to_string() });
    }
    if regex_match(&lower, r"\.(bashrc|zshrc|profile|bash_profile|zprofile)$") {
        hits.push(RuleHit { rule: "shell-rc-write", severity: Severity::High, matched: path.to_string() });
    }
    if regex_match(&lower, r"\.env(\.|$)") {
        hits.push(RuleHit { rule: "env-file-write", severity: Severity::Medium, matched: path.to_string() });
    }
    if regex_match(&lower, r"^/etc/") {
        hits.push(RuleHit { rule: "system-config-write", severity: Severity::High, matched: path.to_string() });
    }
    hits
}

fn evaluate_read(path: &str) -> Vec<RuleHit> {
    let lower = path.to_lowercase();
    let mut hits = Vec::new();
    if regex_match(&lower, r"\.ssh/(id_|authorized_keys)") {
        hits.push(RuleHit { rule: "ssh-key-read", severity: Severity::High, matched: path.to_string() });
    }
    if regex_match(&lower, r"\.aws/credentials|\.gnupg/") {
        hits.push(RuleHit { rule: "credentials-read", severity: Severity::High, matched: path.to_string() });
    }
    hits
}

fn evaluate_fetch(url: &str) -> Vec<RuleHit> {
    let lower = url.to_lowercase();
    let mut hits = Vec::new();
    // very loose IP-literal (often shellcode hosting)
    if regex_match(&lower, r"^https?://\d+\.\d+\.\d+\.\d+") {
        hits.push(RuleHit { rule: "fetch-ip-literal", severity: Severity::Medium, matched: url.to_string() });
    }
    if regex_match(&lower, r"\.onion/") {
        hits.push(RuleHit { rule: "fetch-onion", severity: Severity::High, matched: url.to_string() });
    }
    hits
}

/// Scan a string of text (e.g. tool result) for prompt-injection signatures.
pub fn evaluate_injection(text: &str) -> Vec<RuleHit> {
    let mut hits = Vec::new();
    let lower = text.to_lowercase();
    if regex_match(&lower, r"ignore\s+(all\s+)?previous\s+instructions") {
        hits.push(RuleHit { rule: "injection-ignore-previous", severity: Severity::High, matched: "ignore previous instructions".to_string() });
    }
    if regex_match(&lower, r"you\s+are\s+now\s+(a\s+)?[a-z\s]{0,30}(jailbreak|developer\s*mode|dan)") {
        hits.push(RuleHit { rule: "injection-roleplay", severity: Severity::High, matched: "roleplay/jailbreak".to_string() });
    }
    if regex_match(text, r"\[SYSTEM\]|<system>|###\s*system\s*###") {
        hits.push(RuleHit { rule: "injection-system-marker", severity: Severity::Medium, matched: "system marker".to_string() });
    }
    // Hidden unicode tag/zero-width
    if text.chars().any(|c| matches!(c as u32, 0x200B..=0x200F | 0xE0000..=0xE007F)) {
        hits.push(RuleHit { rule: "injection-hidden-unicode", severity: Severity::High, matched: "zero-width chars".to_string() });
    }
    hits
}

fn regex_match(text: &str, pattern: &str) -> bool {
    regex::Regex::new(pattern).map(|r| r.is_match(text)).unwrap_or(false)
}

fn match_first(text: &str, patterns: &[&str]) -> Option<String> {
    for p in patterns {
        if let Ok(r) = regex::Regex::new(p) {
            if let Some(m) = r.find(text) {
                return Some(m.as_str().to_string());
            }
        }
    }
    None
}

fn random_id() -> String {
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("evt_{:x}", nanos)
}

pub fn make_event(
    hit: RuleHit,
    tool: &str,
    raw: Value,
    agent_pid: Option<u32>,
    agent_kind: Option<&str>,
    agent_cwd: Option<&str>,
    session_id: Option<&str>,
    decision: &str,
    actor: &str,
) -> SecurityEvent {
    SecurityEvent {
        id: random_id(),
        ts: Utc::now().to_rfc3339(),
        agent_pid,
        agent_kind: agent_kind.map(|s| s.to_string()),
        agent_cwd: agent_cwd.map(|s| s.to_string()),
        session_id: session_id.map(|s| s.to_string()),
        tool: tool.to_string(),
        rule: hit.rule.to_string(),
        severity: hit.severity,
        matched: hit.matched,
        raw,
        decision: decision.to_string(),
        actor: actor.to_string(),
    }
}

pub fn append_events(events: &[SecurityEvent]) -> std::io::Result<()> {
    if events.is_empty() {
        return Ok(());
    }
    ensure_dir()?;
    let path = events_path();
    let mut f = OpenOptions::new().create(true).append(true).open(&path)?;
    for e in events {
        let line = serde_json::to_string(e).unwrap_or_default();
        writeln!(f, "{}", line)?;
    }
    Ok(())
}

pub fn recent_events_for_session(session_id: &str, scan_limit: usize, take: usize) -> Vec<SecurityEvent> {
    let path = events_path();
    let content = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };
    let mut out: Vec<SecurityEvent> = Vec::new();
    for line in content.lines().rev().take(scan_limit) {
        if let Ok(e) = serde_json::from_str::<SecurityEvent>(line) {
            if e.session_id.as_deref() == Some(session_id) {
                out.push(e);
                if out.len() >= take {
                    break;
                }
            }
        }
    }
    out.reverse();
    out
}

pub fn recent_max_severity_for_session(session_id: &str, scan_limit: usize) -> Option<Severity> {
    let path = events_path();
    let content = fs::read_to_string(&path).ok()?;
    let mut max_sev: Option<Severity> = None;
    for line in content.lines().rev().take(scan_limit) {
        if let Ok(e) = serde_json::from_str::<SecurityEvent>(line) {
            if e.session_id.as_deref() == Some(session_id) {
                if max_sev.map(|m| e.severity > m).unwrap_or(true) {
                    max_sev = Some(e.severity);
                }
            }
        }
    }
    max_sev
}

pub fn read_events(limit: usize) -> Vec<SecurityEvent> {
    let path = events_path();
    let content = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };
    let mut out: Vec<SecurityEvent> = content
        .lines()
        .rev()
        .take(limit)
        .filter_map(|l| serde_json::from_str(l).ok())
        .collect();
    out.reverse();
    out
}

pub fn clear_events() -> std::io::Result<()> {
    let path = events_path();
    if path.exists() {
        fs::remove_file(&path)?;
    }
    Ok(())
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
struct Cursors(std::collections::HashMap<String, u64>);

fn load_cursors() -> Cursors {
    fs::read_to_string(cursor_path())
        .ok()
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_default()
}

fn save_cursors(c: &Cursors) -> std::io::Result<()> {
    ensure_dir()?;
    let s = serde_json::to_string(c).unwrap_or_default();
    fs::write(cursor_path(), s)
}

/// Scan a session jsonl from the last cursor onward, evaluate each tool_use,
/// emit events, and persist new cursor. Returns the max severity seen in this
/// scan (None if no hits).
pub fn scan_session_incremental(
    session_path: &std::path::Path,
    agent_pid: Option<u32>,
    agent_kind: Option<&str>,
    agent_cwd: Option<&str>,
) -> Option<Severity> {
    let key = session_path.to_string_lossy().to_string();
    let mut cursors = load_cursors();
    let start = *cursors.0.get(&key).unwrap_or(&0);
    let content = match fs::read_to_string(session_path) {
        Ok(c) => c,
        Err(_) => return None,
    };
    let mut new_events = Vec::new();
    let mut max_sev: Option<Severity> = None;
    let mut line_idx: u64 = 0;
    for line in content.lines() {
        line_idx += 1;
        if line_idx <= start {
            continue;
        }
        let v: Value = match serde_json::from_str(line) {
            Ok(v) => v,
            Err(_) => continue,
        };
        let session_id = v.get("sessionId").and_then(|s| s.as_str());
        if v.get("type").and_then(|t| t.as_str()) != Some("assistant") {
            continue;
        }
        let content_arr = match v.get("message").and_then(|m| m.get("content")).and_then(|c| c.as_array()) {
            Some(arr) => arr,
            None => continue,
        };
        for item in content_arr {
            if item.get("type").and_then(|t| t.as_str()) != Some("tool_use") {
                continue;
            }
            let name = item.get("name").and_then(|s| s.as_str()).unwrap_or("");
            let input = item.get("input").cloned().unwrap_or(Value::Null);
            for hit in evaluate_tool(name, &input) {
                if max_sev.map(|m| hit.severity > m).unwrap_or(true) {
                    max_sev = Some(hit.severity);
                }
                new_events.push(make_event(
                    hit,
                    name,
                    input.clone(),
                    agent_pid,
                    agent_kind,
                    agent_cwd,
                    session_id,
                    "observed",
                    "rule-engine",
                ));
            }
        }
    }
    cursors.0.insert(key, line_idx);
    let _ = save_cursors(&cursors);
    let _ = append_events(&new_events);
    max_sev
}
