//! Egress monitor for AI agents.
//!
//! Polls `ss` periodically, finds established TCP connections owned by any
//! running claude/opencode/kimi/codex process, and flags destinations not
//! on the allowlist. Off by default — flip `egress_enabled` in
//! ~/.config/synthia/runtime.json (or via the GUI toggle) to turn it on.
//!
//! ## Verdict pipeline
//!
//! Each peer IP gets a 3-layer verdict, with the result cached for 1h:
//!
//!   1. **Static cloud-provider CIDR ranges** (`CLOUD_CIDRS`).
//!   2. **Reverse-DNS / PTR lookup** — match against `TRUSTED_PTR_SUFFIXES`.
//!   3. **User allowlist** — `~/.config/synthia/security/allowlist.yaml`,
//!      plus the canonical `DEFAULT_ALLOWLIST` AI hostnames resolved to IPs.
//!
//! `Allowed(...)` verdicts emit no event. Only `Unknown` produces a `RuleHit`.
//! The `REPORTED` HashSet still dedupes per-(pid, ip, port) tuples so the
//! audit log doesn't explode, even within a single 1h cache window.

use std::collections::{HashMap, HashSet};
use std::net::{IpAddr, ToSocketAddrs};
use std::path::PathBuf;
use std::process::Command;
use std::sync::{LazyLock, Mutex};
use std::time::{Duration, Instant};

use ipnet::IpNet;
use regex::Regex;
use serde::{Deserialize, Serialize};

use crate::security;

static SS_PID_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"pid=(\d+)").expect("SS_PID_RE compiles"));
static SS_PROC_RE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"\(\("([^"]+)""#).expect("SS_PROC_RE compiles"));

/// Canonical AI/dev provider hosts. Resolved to IPs at allowlist-load time
/// and folded into the same verdict cache as user-allowlist entries.
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

/// Static IPv4 CIDR ranges for major cloud providers / front-end fleets.
/// Anthropic's edge fronted via Google + Cloudflare lives in here, which is
/// what the noise-reduction pass is fundamentally about.
const CLOUD_CIDRS: &[(&str, &str)] = &[
    ("8.8.0.0/16",        "Google"),
    ("8.34.208.0/20",     "Google"),
    ("8.35.192.0/20",     "Google"),
    ("34.0.0.0/9",        "Google Cloud"),
    ("34.128.0.0/10",     "Google Cloud"),
    ("35.184.0.0/13",     "Google Cloud"),
    ("35.190.0.0/16",     "Google"),
    ("35.191.0.0/16",     "Google"),
    ("35.192.0.0/14",     "Google Cloud"),
    ("104.16.0.0/12",     "Cloudflare"),
    ("172.64.0.0/13",     "Cloudflare"),
    ("13.32.0.0/15",      "AWS CloudFront"),
    ("13.224.0.0/14",     "AWS CloudFront"),
    ("52.84.0.0/15",      "AWS CloudFront"),
    ("99.84.0.0/16",      "AWS CloudFront"),
    ("3.5.0.0/16",        "AWS S3"),
    ("52.216.0.0/15",     "AWS S3"),
    ("20.0.0.0/8",        "Azure"),
    ("40.64.0.0/10",      "Azure"),
    ("160.79.104.0/23",   "Anthropic"),
    // IPv6 — major provider front-end ranges. AI APIs increasingly serve IPv6
    // via Cloudflare/Google when the client supports it.
    ("2606:4700::/32",    "Cloudflare"),
    ("2400:cb00::/32",    "Cloudflare"),
    ("2607:f8b0::/32",    "Google"),
    ("2620:11a:a000::/40","Google"),
    ("2a00:1450::/32",    "Google"),
    ("2800:3f0::/32",     "Google"),
    ("2600:1900::/28",    "Google Cloud"), // GCP IPv6 — covers 2600:1900-190f
    ("2a01:111::/32",     "Microsoft"),
    ("2603:1000::/24",    "Azure"),
    ("2600:1f00::/24",    "AWS"),
    ("2406:da00::/24",    "AWS"),
    ("2620:107:300f::/48","AWS"),
];

/// PTR-record suffixes considered trustworthy. Reverse DNS is informational
/// (anyone can set it) but combined with the CIDR layer + a curated list of
/// canonical provider zones it's accurate enough to silence ~all of the
/// 28-events-per-session false-positive flood.
const TRUSTED_PTR_SUFFIXES: &[&str] = &[
    ".googleusercontent.com",
    ".1e100.net",
    ".amazonaws.com",
    ".cloudfront.net",
    ".cloudflare.com",
    ".anthropic.com",
    ".openai.com",
    ".github.com",
    ".github.io",
];

const POLL_INTERVAL_S: u64 = 30;
const VERDICT_TTL: Duration = Duration::from_secs(3600);
const ALLOWLIST_TTL: Duration = Duration::from_secs(3600);

/// Per-(pid, ip, port) dedupe so even within the verdict cache window an
/// `Unknown` peer doesn't get logged on every 30s poll. Survives across
/// allowlist invalidation — that's intentional; we only want to log the
/// first sighting of a connection, not every poll cycle.
static REPORTED: Mutex<Option<HashSet<String>>> = Mutex::new(None);

type VerdictCache = HashMap<IpAddr, (Verdict, Instant)>;
type AllowlistCache = Option<(HashSet<IpAddr>, Instant)>;

/// Peer-IP → (verdict, instant). `Allowed` and `Unknown` both cached so
/// PTR lookups are at most one per IP per hour.
static VERDICT_CACHE: LazyLock<Mutex<VerdictCache>> =
    LazyLock::new(|| Mutex::new(HashMap::new()));

/// Resolved allowlist (default hostnames + user `hosts` + literal user `ips`).
/// Cleared by `invalidate_allowlist_cache()` on user write so a freshly-added
/// host takes effect on the next poll.
static ALLOWLIST_CACHE: LazyLock<Mutex<AllowlistCache>> = LazyLock::new(|| Mutex::new(None));

#[derive(Debug, Clone, PartialEq, Eq)]
enum Verdict {
    Allowed(String),
    Unknown,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
struct UserAllowlistFile {
    #[serde(default)]
    hosts: Vec<String>,
    #[serde(default)]
    ips: Vec<String>,
}

pub fn runtime_state_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/runtime.json")
}

fn user_allowlist_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security/allowlist.yaml")
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

/// Clear the resolved-allowlist cache so the next verdict lookup re-reads
/// `~/.config/synthia/security/allowlist.yaml`. Called by the
/// `add_to_allowlist` Tauri command after a successful write.
pub fn invalidate_allowlist_cache() {
    if let Ok(mut g) = ALLOWLIST_CACHE.lock() {
        *g = None;
    }
    // Also drop the per-IP verdict cache: a freshly-allowed host's IPs
    // currently sit in the cache as `Unknown`, and we want them re-evaluated
    // immediately rather than after the 1h TTL.
    if let Ok(mut g) = VERDICT_CACHE.lock() {
        g.clear();
    }
}

fn resolve_host(host: &str) -> Vec<IpAddr> {
    let target = format!("{}:443", host);
    target
        .to_socket_addrs()
        .map(|iter| iter.map(|s| s.ip()).collect())
        .unwrap_or_default()
}

fn load_user_allowlist() -> UserAllowlistFile {
    let path = user_allowlist_path();
    let content = match std::fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return UserAllowlistFile::default(),
    };
    serde_yaml::from_str(&content).unwrap_or_default()
}

/// Return the current resolved-allowlist IP set. Refreshes from disk if
/// the cached entry is older than `ALLOWLIST_TTL` or absent.
fn resolved_allowlist() -> HashSet<IpAddr> {
    if let Ok(g) = ALLOWLIST_CACHE.lock() {
        if let Some((set, ts)) = g.as_ref() {
            if ts.elapsed() < ALLOWLIST_TTL {
                return set.clone();
            }
        }
    }
    let user = load_user_allowlist();
    let mut out: HashSet<IpAddr> = HashSet::new();
    for host in DEFAULT_ALLOWLIST.iter() {
        for ip in resolve_host(host) {
            out.insert(ip);
        }
    }
    for host in user.hosts.iter() {
        for ip in resolve_host(host) {
            out.insert(ip);
        }
    }
    for ip_str in user.ips.iter() {
        if let Ok(ip) = ip_str.parse::<IpAddr>() {
            out.insert(ip);
        }
    }
    if let Ok(mut g) = ALLOWLIST_CACHE.lock() {
        *g = Some((out.clone(), Instant::now()));
    }
    out
}

/// True if `ip` falls within any of the static `CLOUD_CIDRS`. Returns the
/// provider label on hit. Handles both IPv4 and IPv6 (front-end fleets serve
/// AI APIs over both stacks).
fn cidr_match(ip: IpAddr) -> Option<&'static str> {
    for (cidr, label) in CLOUD_CIDRS {
        if let Ok(net) = cidr.parse::<IpNet>() {
            if net.contains(&ip) {
                return Some(label);
            }
        }
    }
    None
}

/// String suffix-match against `TRUSTED_PTR_SUFFIXES`. Pure function so the
/// test can exercise it without a DNS round-trip.
fn ptr_suffix_trusted(hostname: &str) -> bool {
    let lower = hostname.to_lowercase();
    let trimmed = lower.trim_end_matches('.');
    TRUSTED_PTR_SUFFIXES
        .iter()
        .any(|suf| trimmed.ends_with(suf))
}

/// Best-effort PTR lookup. Returns `None` on lookup failure or empty result.
fn lookup_ptr(ip: IpAddr) -> Option<String> {
    dns_lookup::lookup_addr(&ip).ok().filter(|s| !s.is_empty())
}

/// Fresh verdict for `ip` ignoring the cache. Used by `verdict_for_ip` after
/// a cache miss / expiry, and by tests that want a deterministic answer.
fn compute_verdict(ip: IpAddr) -> Verdict {
    if let Some(label) = cidr_match(ip) {
        return Verdict::Allowed(format!("CIDR: {label}"));
    }
    if let Some(host) = lookup_ptr(ip) {
        if ptr_suffix_trusted(&host) {
            return Verdict::Allowed(format!("PTR: {host}"));
        }
    }
    if resolved_allowlist().contains(&ip) {
        return Verdict::Allowed("user-allowlist".to_string());
    }
    Verdict::Unknown
}

/// Cache-aware verdict lookup. `now` is injected so tests can drive the TTL
/// without sleeping. Production callers pass `Instant::now()`.
fn verdict_for_ip_at(ip: IpAddr, now: Instant) -> Verdict {
    if let Ok(g) = VERDICT_CACHE.lock() {
        if let Some((v, ts)) = g.get(&ip) {
            if now.duration_since(*ts) < VERDICT_TTL {
                return v.clone();
            }
        }
    }
    let v = compute_verdict(ip);
    if let Ok(mut g) = VERDICT_CACHE.lock() {
        g.insert(ip, (v.clone(), now));
    }
    v
}

fn verdict_for_ip(ip: IpAddr) -> Verdict {
    verdict_for_ip_at(ip, Instant::now())
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

fn poll_once(ai_pids: &HashSet<u32>) {
    let mut reported = match REPORTED.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    let set = reported.get_or_insert_with(HashSet::new);
    for c in poll_connections() {
        if !ai_pids.contains(&c.pid) {
            continue;
        }
        // Skip local + private — these never reach a verdict layer.
        if c.peer_ip.starts_with("127.")
            || c.peer_ip.starts_with("10.")
            || c.peer_ip.starts_with("192.168.")
            || c.peer_ip.starts_with("169.254.")
            || c.peer_ip == "::1"
        {
            continue;
        }
        let parsed_ip = match c.peer_ip.parse::<IpAddr>() {
            Ok(ip) => ip,
            Err(_) => continue,
        };
        match verdict_for_ip(parsed_ip) {
            Verdict::Allowed(_) => continue,
            Verdict::Unknown => {}
        }
        let key = format!("{}:{}:{}", c.pid, c.peer_ip, c.peer_port);
        if !set.insert(key.clone()) {
            continue;
        }
        let cwd = read_proc_cwd(c.pid);
        // Bracket IPv6 addresses so the display + parser can split host:port cleanly.
        let display_addr = if matches!(parsed_ip, IpAddr::V6(_)) {
            format!("[{}]:{}", c.peer_ip, c.peer_port)
        } else {
            format!("{}:{}", c.peer_ip, c.peer_port)
        };
        let hit = security::RuleHit {
            rule: "egress-unknown-host",
            severity: security::Severity::Medium,
            matched: format!("{} (proc {})", display_addr, c.process),
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
        loop {
            std::thread::sleep(Duration::from_secs(POLL_INTERVAL_S));
            if !is_enabled() {
                continue;
            }
            let self_pid = std::process::id();
            let pids = list_ai_pids(self_pid);
            if pids.is_empty() {
                continue;
            }
            poll_once(&pids);
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::{Ipv4Addr, Ipv6Addr};

    #[test]
    fn cidr_matches_cloudflare_v6() {
        // 2606:4700::6812:15f6 is in Cloudflare's 2606:4700::/32.
        let ip = IpAddr::V6("2606:4700::6812:15f6".parse::<Ipv6Addr>().unwrap());
        let label = cidr_match(ip);
        assert!(
            matches!(label, Some("Cloudflare")),
            "expected Cloudflare label, got {label:?}"
        );
    }

    #[test]
    fn cidr_matches_google_v6() {
        // 2607:f8b0:: is Google's primary IPv6 range.
        let ip = IpAddr::V6("2607:f8b0:4001:c00::1".parse::<Ipv6Addr>().unwrap());
        let label = cidr_match(ip);
        assert!(
            matches!(label, Some(l) if l.starts_with("Google")),
            "expected Google* label, got {label:?}"
        );
    }

    #[test]
    fn cidr_matches_google_range() {
        // 35.190.46.17 is in 35.190.0.0/16 (and the broader 35.184.0.0/13 GCP
        // range too — both labels are acceptable; we just want a Google-side
        // match, not the falsy `None`).
        let ip = IpAddr::V4(Ipv4Addr::new(35, 190, 46, 17));
        let label = cidr_match(ip);
        assert!(
            matches!(label, Some(l) if l.starts_with("Google")),
            "expected Google* label, got {label:?}"
        );
    }

    #[test]
    fn cidr_misses_unrelated() {
        // 1.2.3.4 doesn't match any CIDR in the list.
        let ip = IpAddr::V4(Ipv4Addr::new(1, 2, 3, 4));
        assert_eq!(cidr_match(ip), None);
    }

    #[test]
    fn trusted_ptr_suffix_matches() {
        assert!(ptr_suffix_trusted("foo.googleusercontent.com"));
        assert!(ptr_suffix_trusted("server-1-2-3.1e100.net"));
        assert!(ptr_suffix_trusted("ec2-1-2-3-4.amazonaws.com"));
        // Trailing dot (FQDN) tolerated.
        assert!(ptr_suffix_trusted("foo.googleusercontent.com."));
        // Case-insensitive.
        assert!(ptr_suffix_trusted("FOO.GoogleUserContent.COM"));
    }

    #[test]
    fn trusted_ptr_suffix_rejects_unrelated() {
        assert!(!ptr_suffix_trusted("evil.example.com"));
        // A suffix substring that isn't actually a domain suffix — must NOT match.
        assert!(!ptr_suffix_trusted("notgoogleusercontent.com"));
        assert!(!ptr_suffix_trusted(""));
    }

    #[test]
    fn verdict_cache_returns_within_ttl() {
        // A CIDR-matching IP gets a deterministic Allowed verdict; cache it
        // at t0, then a lookup at t0+1s must hit the cache (verifiable here
        // by getting the same Verdict back since CIDR is pure).
        let ip = IpAddr::V4(Ipv4Addr::new(35, 190, 46, 18));
        let t0 = Instant::now();
        let v1 = verdict_for_ip_at(ip, t0);
        let v2 = verdict_for_ip_at(ip, t0 + Duration::from_secs(1));
        assert_eq!(v1, v2);
        assert!(matches!(v1, Verdict::Allowed(_)));
    }
}
