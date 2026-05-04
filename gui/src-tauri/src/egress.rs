//! Egress monitor for AI agents.
//!
//! Polls `ss` periodically, finds established TCP connections owned by any
//! running claude/opencode/kimi/codex process, and flags destinations not
//! on the allowlist. Off by default — flip `egress_enabled` in
//! ~/.config/synthia/runtime.json (or via the GUI toggle) to turn it on.

use std::collections::HashSet;
use std::net::ToSocketAddrs;
use std::path::PathBuf;
use std::process::Command;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use regex::Regex;

use crate::security;

static SS_PID_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"pid=(\d+)").expect("SS_PID_RE compiles"));
static SS_PROC_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"\(\("([^"]+)""#).expect("SS_PROC_RE compiles"));

const DEFAULT_ALLOWLIST: &[&str] = &[
    "api.anthropic.com",
    "claude.ai",
    "console.anthropic.com",
    "api.openai.com",
    "api.x.ai",
    "api.deepseek.com",
    "api.moonshot.cn",
    "api.moonshot.ai",
    "github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
    "registry.npmjs.org",
    "pypi.org",
    "files.pythonhosted.org",
    "deb.debian.org",
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "dl.google.com",
    "huggingface.co",
    "cdn-lfs.huggingface.co",
];

const POLL_INTERVAL_S: u64 = 30;
const RESOLVE_TTL_S: u64 = 600;

static REPORTED: Mutex<Option<HashSet<String>>> = Mutex::new(None);

pub fn runtime_state_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/runtime.json")
}

pub fn is_enabled() -> bool {
    let path = runtime_state_path();
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return false,
    };
    serde_json::from_str::<serde_json::Value>(&content)
        .ok()
        .and_then(|v| v.get("egress_enabled").and_then(|b| b.as_bool()))
        .unwrap_or(false)
}

fn resolve_allowlist() -> HashSet<String> {
    let mut out = HashSet::new();
    for host in DEFAULT_ALLOWLIST {
        let target = format!("{}:443", host);
        if let Ok(iter) = target.to_socket_addrs() {
            for addr in iter {
                out.insert(addr.ip().to_string());
            }
        }
    }
    out
}

fn list_ai_pids(self_pid: u32) -> HashSet<u32> {
    crate::commands::agents::list_ai_processes(self_pid)
        .into_iter()
        .map(|(pid, _, _, _)| pid)
        .collect()
}

fn read_proc_cwd(pid: u32) -> Option<String> {
    std::fs::read_link(format!("/proc/{}/cwd", pid))
        .ok()
        .and_then(|p| p.to_str().map(|s| s.to_string()))
}

#[derive(Debug)]
struct Connection {
    pid: u32,
    process: String,
    peer_ip: String,
    peer_port: u16,
}

fn poll_connections() -> Vec<Connection> {
    let out = match Command::new("ss")
        .args(["-Hntp", "state", "established"])
        .output()
    {
        Ok(o) if o.status.success() => o,
        _ => return Vec::new(),
    };
    let stdout = String::from_utf8_lossy(&out.stdout);
    let mut rows = Vec::new();
    for line in stdout.lines() {
        let toks: Vec<&str> = line.split_whitespace().collect();
        if toks.len() < 5 {
            continue;
        }
        let peer = toks[3];
        let users = toks[4];
        let (peer_ip, peer_port) = match peer.rsplit_once(':') {
            Some((ip, port)) => (ip.trim_start_matches('[').trim_end_matches(']').to_string(),
                                 port.parse::<u16>().unwrap_or(0)),
            None => continue,
        };
        let pid = SS_PID_RE
            .captures(users)
            .and_then(|c| c.get(1))
            .and_then(|m| m.as_str().parse::<u32>().ok());
        let process = SS_PROC_RE
            .captures(users)
            .and_then(|c| c.get(1))
            .map(|m| m.as_str().to_string())
            .unwrap_or_default();
        if let Some(pid) = pid {
            rows.push(Connection { pid, process, peer_ip, peer_port });
        }
    }
    rows
}

fn poll_once(allowlist: &HashSet<String>, ai_pids: &HashSet<u32>) {
    let mut reported = match REPORTED.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    let set = reported.get_or_insert_with(HashSet::new);
    for c in poll_connections() {
        if !ai_pids.contains(&c.pid) {
            continue;
        }
        if allowlist.contains(&c.peer_ip) {
            continue;
        }
        // skip local + private
        if c.peer_ip.starts_with("127.")
            || c.peer_ip.starts_with("10.")
            || c.peer_ip.starts_with("192.168.")
            || c.peer_ip.starts_with("169.254.")
            || c.peer_ip == "::1"
        {
            continue;
        }
        let key = format!("{}:{}:{}", c.pid, c.peer_ip, c.peer_port);
        if !set.insert(key.clone()) {
            continue;
        }
        let cwd = read_proc_cwd(c.pid);
        let hit = security::RuleHit {
            rule: "egress-unknown-host",
            severity: security::Severity::Medium,
            matched: format!("{}:{} (proc {})", c.peer_ip, c.peer_port, c.process),
        };
        let raw = serde_json::json!({
            "pid": c.pid,
            "process": c.process,
            "peer_ip": c.peer_ip,
            "peer_port": c.peer_port,
        });
        let event = security::make_event(
            hit,
            "Network",
            raw,
            Some(c.pid),
            Some("claude"),
            cwd.as_deref(),
            None,
            "observed",
            "egress-monitor",
        );
        let _ = security::append_events(&[event]);
    }
}

pub fn spawn_watcher() {
    std::thread::spawn(|| {
        let mut allowlist = resolve_allowlist();
        let mut allowlist_ts = Instant::now();
        loop {
            std::thread::sleep(Duration::from_secs(POLL_INTERVAL_S));
            if !is_enabled() {
                continue;
            }
            if allowlist_ts.elapsed().as_secs() > RESOLVE_TTL_S {
                allowlist = resolve_allowlist();
                allowlist_ts = Instant::now();
            }
            let self_pid = std::process::id();
            let pids = list_ai_pids(self_pid);
            if pids.is_empty() {
                continue;
            }
            poll_once(&allowlist, &pids);
        }
    });
}
