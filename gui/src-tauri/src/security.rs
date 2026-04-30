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

fn evaluate_bash(cmd: &str) -> Vec<RuleHit> {
    let mut hits = Vec::new();
    let lower = cmd.to_lowercase();

    // Destructive rm
    if let Some(m) = match_first(&lower, &[
        r"rm\s+-rf?\s+/",
        r"rm\s+-rf?\s+~",
        r"rm\s+-rf?\s+\$home",
        r"rm\s+-rf?\s+--no-preserve-root",
    ]) {
        hits.push(RuleHit { rule: "destructive-rm", severity: Severity::Critical, matched: m });
    }

    // dd to block device
    if regex_match(&lower, r"\bdd\b.+of=/dev/(sd|nvme|hd)") {
        hits.push(RuleHit { rule: "dd-block-device", severity: Severity::Critical, matched: "dd of=/dev/...".to_string() });
    }

    // Pipe to shell
    if regex_match(&lower, r"(curl|wget|fetch)[^|]*\|\s*(sh|bash|zsh|fish)\b") {
        hits.push(RuleHit { rule: "pipe-to-shell", severity: Severity::Critical, matched: "curl/wget | sh".to_string() });
    }

    // Base64 + exec
    if regex_match(&lower, r"base64\s+(-d|--decode)[^|]*\|\s*(sh|bash|python|node)") {
        hits.push(RuleHit { rule: "base64-exec", severity: Severity::Critical, matched: "base64 -d | sh".to_string() });
    }

    // Privilege escalation
    if regex_match(&lower, r"\bsudo\b") {
        hits.push(RuleHit { rule: "sudo", severity: Severity::High, matched: "sudo".to_string() });
    }
    if regex_match(&lower, r"chmod\s+\+s\b") {
        hits.push(RuleHit { rule: "setuid-bit", severity: Severity::High, matched: "chmod +s".to_string() });
    }
    if regex_match(&lower, r"\bsetcap\b") {
        hits.push(RuleHit { rule: "setcap", severity: Severity::High, matched: "setcap".to_string() });
    }

    // Shell-rc tamper
    if regex_match(&lower, r">+\s*~?/?\.(bashrc|zshrc|profile|bash_profile|zprofile)\b") {
        hits.push(RuleHit { rule: "shell-rc-tamper", severity: Severity::High, matched: "rc-file write".to_string() });
    }

    // SSH key read
    if regex_match(&lower, r"~?/?\.ssh/(id_|authorized_keys|known_hosts)") {
        hits.push(RuleHit { rule: "ssh-key-access", severity: Severity::High, matched: "~/.ssh/...".to_string() });
    }

    // GPG / credentials
    if regex_match(&lower, r"~?/?\.gnupg/") {
        hits.push(RuleHit { rule: "gpg-access", severity: Severity::High, matched: "~/.gnupg/...".to_string() });
    }
    if regex_match(&lower, r"~?/?\.aws/credentials") {
        hits.push(RuleHit { rule: "aws-credentials", severity: Severity::High, matched: "~/.aws/credentials".to_string() });
    }

    // Network exfil pattern: tar/zip + curl/scp to non-localhost
    if regex_match(&lower, r"(curl|wget|scp|rsync)[^|;&\n]*(\.ssh|\.aws|\.gnupg|credentials|secret|token)") {
        hits.push(RuleHit { rule: "secret-exfil", severity: Severity::Critical, matched: "secret + network".to_string() });
    }

    // Mass kill
    if regex_match(&lower, r"\bpkill\s+-9\b|\bkillall\s+-9\b") {
        hits.push(RuleHit { rule: "mass-kill", severity: Severity::Medium, matched: "pkill -9".to_string() });
    }

    // Git remote rewrite
    if regex_match(&lower, r"git\s+remote\s+(set-url|add)\s+\S+\s+(http|git@)") {
        hits.push(RuleHit { rule: "git-remote-rewrite", severity: Severity::Medium, matched: "git remote set-url".to_string() });
    }

    // History tamper
    if regex_match(&lower, r"history\s+-c|>\s*~?/?\.(bash_history|zsh_history)") {
        hits.push(RuleHit { rule: "history-tamper", severity: Severity::Medium, matched: "history clear".to_string() });
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
