//! The hive: what Synthia's shared brain holds and who has been reaching into it.
//!
//! Memories are the Claude Code project memory files (`~/.claude/projects/*/memory/*.md`). Recalls come
//! from `~/.local/share/synthia/brain/recalls.jsonl`, appended by the PostToolUse hook in
//! `src/synthia/hooks/memory_recall_log.py`. Everything here is read only.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};
use std::time::{Duration, Instant, UNIX_EPOCH};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use super::squads::{Dirs, Member};
use crate::error::{AppError, AppResult};
use crate::state::AppState;

const SCAN_TTL: Duration = Duration::from_secs(60);
const LOG_TAIL_BYTES: u64 = 2 * 1024 * 1024;
const WEEK_MS: i64 = 7 * 86_400_000;
const ROW_CAP: usize = 80;
const BODY_CAP: usize = 20_000;

fn home() -> PathBuf {
    super::fleet::home_dir()
}

// ---------------------------------------------------------------------------
// Frontmatter and memory kinds
// ---------------------------------------------------------------------------

#[derive(Debug, Default, PartialEq, Clone)]
pub struct Front {
    pub name: String,
    pub description: String,
    pub meta_type: String,
}

fn unquote(v: &str) -> String {
    let v = v.trim();
    if v.starts_with('"') && v.ends_with('"') && v.len() >= 2 {
        if let Ok(s) = serde_json::from_str::<String>(v) {
            return s;
        }
        return v[1..v.len() - 1].to_string();
    }
    if v.starts_with('\'') && v.ends_with('\'') && v.len() >= 2 {
        return v[1..v.len() - 1].to_string();
    }
    v.to_string()
}

/// Split a markdown file into its frontmatter fields and the body.
pub fn parse_front(text: &str) -> (Front, &str) {
    let mut f = Front::default();
    let Some(rest) = text.strip_prefix("---\n") else { return (f, text) };
    let (block, body) = match rest.find("\n---") {
        Some(i) => (&rest[..i], rest[i + 4..].trim_start_matches(['\n', '\r'])),
        None => return (f, text),
    };
    let mut in_meta = false;
    for line in block.lines() {
        let indented = line.starts_with(' ') || line.starts_with('\t');
        let t = line.trim();
        if !indented {
            in_meta = t == "metadata:";
            if let Some(v) = t.strip_prefix("name:") {
                f.name = unquote(v);
            } else if let Some(v) = t.strip_prefix("description:") {
                f.description = unquote(v);
            } else if let Some(v) = t.strip_prefix("type:") {
                // Some files keep `type:` at the top level.
                f.meta_type = unquote(v);
            }
        } else if in_meta {
            if let Some(v) = t.strip_prefix("type:") {
                f.meta_type = unquote(v);
            }
        }
    }
    (f, body)
}

/// feedback | project | reference | bug | user | other. `metadata.type` wins, then the filename prefix
/// (`feedback_x.md` or `feedback-x.md`).
pub fn kind_of(front: &Front, file_name: &str) -> String {
    const KINDS: [&str; 5] = ["feedback", "project", "reference", "bug", "user"];
    let t = front.meta_type.to_ascii_lowercase();
    if KINDS.contains(&t.as_str()) {
        return t;
    }
    let lower = file_name.to_ascii_lowercase();
    for k in KINDS {
        if lower.starts_with(&format!("{k}_")) || lower.starts_with(&format!("{k}-")) {
            return k.to_string();
        }
    }
    "other".to_string()
}

// ---------------------------------------------------------------------------
// The scan (memories, vault, skills, roles, handbooks, connectors), cached for a minute
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MemoryMeta {
    pub path: String,
    pub name: String,
    pub description: String,
    pub kind: String,
    pub modified_ms: i64,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillInfo {
    pub name: String,
    pub description: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct Connected {
    pub local: Vec<String>,
    pub claude_ai: Vec<String>,
}

#[derive(Default)]
pub struct Scan {
    pub memories: Vec<MemoryMeta>,
    pub vault_notes: usize,
    pub skills: Vec<SkillInfo>,
    pub roles: Vec<String>,
    pub claude_md: usize,
    pub connected: Connected,
}

fn mtime_ms(path: &Path) -> i64 {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn sorted_entries(dir: &Path) -> Vec<PathBuf> {
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .map(|rd| rd.filter_map(|e| e.ok()).map(|e| e.path()).collect())
        .unwrap_or_default();
    v.sort();
    v
}

pub fn scan_memories(projects: &Path) -> Vec<MemoryMeta> {
    let mut out = Vec::new();
    for proj in sorted_entries(projects) {
        for f in sorted_entries(&proj.join("memory")) {
            let name = f.file_name().and_then(|n| n.to_str()).unwrap_or_default().to_string();
            if !name.ends_with(".md") || name == "MEMORY.md" || !f.is_file() {
                continue;
            }
            // Only the head of the file matters for the frontmatter.
            let head = read_head(&f, 4096);
            let (front, _) = parse_front(&head);
            out.push(MemoryMeta {
                path: f.to_string_lossy().into_owned(),
                name: if front.name.is_empty() { name.trim_end_matches(".md").to_string() } else { front.name.clone() },
                description: front.description.clone(),
                kind: kind_of(&front, &name),
                modified_ms: mtime_ms(&f),
            });
        }
    }
    out
}

fn read_head(path: &Path, n: usize) -> String {
    use std::io::Read;
    let mut buf = vec![0u8; n];
    let Ok(mut f) = std::fs::File::open(path) else { return String::new() };
    let got = f.read(&mut buf).unwrap_or(0);
    buf.truncate(got);
    String::from_utf8_lossy(&buf).into_owned()
}

/// Count `*.md` files under `root` (a few levels deep, skipping hidden folders).
pub fn count_markdown(root: &Path, depth: usize) -> usize {
    if depth == 0 {
        return 0;
    }
    let mut n = 0;
    for p in sorted_entries(root) {
        let name = p.file_name().and_then(|n| n.to_str()).unwrap_or_default();
        if name.starts_with('.') {
            continue;
        }
        if p.is_dir() {
            n += count_markdown(&p, depth - 1);
        } else if name.ends_with(".md") {
            n += 1;
        }
    }
    n
}

/// CLAUDE.md files under `root`, at most `depth` folders down; no hidden, node_modules or target folders.
pub fn count_handbooks(root: &Path, depth: usize) -> usize {
    let mut n = 0;
    for p in sorted_entries(root) {
        let name = p.file_name().and_then(|n| n.to_str()).unwrap_or_default();
        if name == "CLAUDE.md" && p.is_file() {
            n += 1;
        } else if depth > 0 && p.is_dir() && !name.starts_with('.') && name != "node_modules" && name != "target" {
            n += count_handbooks(&p, depth - 1);
        }
    }
    n
}

fn scan_skills(dir: &Path) -> Vec<SkillInfo> {
    sorted_entries(dir)
        .into_iter()
        .filter_map(|d| {
            let md = d.join("SKILL.md");
            if !md.is_file() {
                return None;
            }
            let (front, _) = parse_front(&read_head(&md, 4096));
            let dir_name = d.file_name()?.to_str()?.to_string();
            Some(SkillInfo {
                name: if front.name.is_empty() { dir_name } else { front.name },
                description: front.description,
            })
        })
        .collect()
}

fn scan_roles(dir: &Path) -> Vec<String> {
    sorted_entries(dir)
        .into_iter()
        .filter_map(|p| {
            let n = p.file_name()?.to_str()?;
            n.strip_suffix(".md").map(String::from)
        })
        .collect()
}

/// Server names only. The file also holds environment values and keys; those are never read out.
pub fn parse_connected(claude_json: &str) -> Connected {
    let Ok(v) = serde_json::from_str::<serde_json::Value>(claude_json) else { return Connected::default() };
    let mut local: Vec<String> = Vec::new();
    let mut add = |obj: Option<&serde_json::Value>| {
        if let Some(m) = obj.and_then(|o| o.as_object()) {
            for k in m.keys() {
                if !local.contains(k) {
                    local.push(k.clone());
                }
            }
        }
    };
    add(v.get("mcpServers"));
    if let Some(projects) = v.get("projects").and_then(|p| p.as_object()) {
        for p in projects.values() {
            add(p.get("mcpServers"));
        }
    }
    let claude_ai = v
        .get("claudeAiMcpEverConnected")
        .and_then(|a| a.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str())
                .map(|s| s.trim_start_matches("claude.ai ").to_string())
                .collect()
        })
        .unwrap_or_default();
    Connected { local, claude_ai }
}

fn do_scan(home: &Path) -> Scan {
    Scan {
        memories: scan_memories(&home.join(".claude/projects")),
        vault_notes: count_markdown(&home.join("vault"), 6),
        skills: scan_skills(&home.join(".claude/skills")),
        roles: scan_roles(&home.join(".claude/agents")),
        claude_md: usize::from(home.join(".claude/CLAUDE.md").is_file()) + count_handbooks(&home.join("dev"), 3),
        connected: std::fs::read_to_string(home.join(".claude.json"))
            .map(|t| parse_connected(&t))
            .unwrap_or_default(),
    }
}

type ScanCache = Mutex<Option<(Instant, Arc<Scan>)>>;
static SCAN: OnceLock<ScanCache> = OnceLock::new();

fn scan() -> Arc<Scan> {
    let cell = SCAN.get_or_init(|| Mutex::new(None));
    if let Some((at, s)) = cell.lock().as_ref() {
        if at.elapsed() < SCAN_TTL {
            return s.clone();
        }
    }
    let fresh = Arc::new(do_scan(&home()));
    *cell.lock() = Some((Instant::now(), fresh.clone()));
    fresh
}

// ---------------------------------------------------------------------------
// The recall log and who a recall belongs to
// ---------------------------------------------------------------------------

#[derive(Deserialize, Debug, Clone, PartialEq)]
pub struct RawRecall {
    pub at: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub file: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub cwd: String,
    pub pane: Option<String>,
}

fn at_ms(at: &str) -> Option<i64> {
    chrono::DateTime::parse_from_rfc3339(at).ok().map(|d| d.timestamp_millis())
}

/// Parse log lines at or after `since_ms`, skipping anything that is not a good entry.
pub fn parse_recalls(text: &str, since_ms: i64) -> Vec<(i64, RawRecall)> {
    text.lines()
        .filter_map(|l| serde_json::from_str::<RawRecall>(l).ok())
        .filter(|r| r.kind == "read" || r.kind == "write")
        .filter_map(|r| at_ms(&r.at).map(|t| (t, r)))
        .filter(|(t, _)| *t >= since_ms)
        .collect()
}

fn read_log_tail(path: &Path) -> String {
    use std::io::{Read, Seek, SeekFrom};
    let Ok(mut f) = std::fs::File::open(path) else { return String::new() };
    let len = f.metadata().map(|m| m.len()).unwrap_or(0);
    let start = len.saturating_sub(LOG_TAIL_BYTES);
    if f.seek(SeekFrom::Start(start)).is_err() {
        return String::new();
    }
    let mut buf = Vec::new();
    let _ = f.read_to_end(&mut buf);
    let text = String::from_utf8_lossy(&buf).into_owned();
    // A tail read starts mid-line: drop the partial first line.
    if start > 0 {
        text.split_once('\n').map(|(_, rest)| rest.to_string()).unwrap_or_default()
    } else {
        text
    }
}

#[derive(Serialize, Clone, Debug, PartialEq, Eq, Hash)]
#[serde(rename_all = "camelCase")]
pub struct Team {
    /// synthia | engineering | <squad id> | other
    pub key: String,
    pub label: String,
}

pub struct Attribution<'a> {
    pub registry: &'a HashMap<String, Member>,
    /// (pane id, title) of every pane in the live fleet.
    pub fleet: &'a [(String, String)],
    pub brain_cwd: &'a str,
}

fn cap(s: &str) -> String {
    let mut c = s.chars();
    c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
}

/// Squad member by pane first, then a fleet agent (Engineering), then the Synthia brain (no pane,
/// working in the brain's folder), else Other.
pub fn attribute(pane: Option<&str>, cwd: &str, a: &Attribution) -> (Team, String) {
    if let Some(p) = pane {
        if let Some(m) = a.registry.get(p) {
            let who = if m.title.is_empty() { m.role.clone() } else { m.title.clone() };
            return (Team { key: m.squad.clone(), label: format!("{} · {}", cap(&m.squad), who) }, who);
        }
        if let Some((_, title)) = a.fleet.iter().find(|(id, _)| id == p) {
            return (Team { key: "engineering".into(), label: format!("Engineering · {title}") }, title.clone());
        }
    }
    if pane.is_none() && !a.brain_cwd.is_empty() && cwd.trim_end_matches('/') == a.brain_cwd.trim_end_matches('/') {
        return (Team { key: "synthia".into(), label: "Synthia".into() }, String::new());
    }
    (Team { key: "other".into(), label: "Other".into() }, String::new())
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RecallEntry {
    pub at_ms: i64,
    pub kind: String,
    pub title: String,
    pub file: String,
    pub team: Team,
    pub who: String,
}

fn expand_home(p: &str, home: &Path) -> String {
    match p.strip_prefix("~/") {
        Some(rest) => home.join(rest).to_string_lossy().into_owned(),
        None => p.to_string(),
    }
}

/// `cwd` and `journal_dir` from `~/.config/synthia/brain.yaml`.
fn brain_config(home: &Path) -> (String, PathBuf) {
    let default_cwd = home.join("dev/eventflo").to_string_lossy().into_owned();
    let default_journal = home.join(".config/synthia/journal");
    let Ok(text) = std::fs::read_to_string(home.join(".config/synthia/brain.yaml")) else {
        return (default_cwd, default_journal);
    };
    let v: serde_yaml::Value = serde_yaml::from_str(&text).unwrap_or(serde_yaml::Value::Null);
    let get = |k: &str| v.get(k).and_then(|x| x.as_str()).map(|s| expand_home(s, home));
    (get("cwd").unwrap_or(default_cwd), get("journal_dir").map(PathBuf::from).unwrap_or(default_journal))
}

fn recall_entries(state: &AppState, since_ms: i64) -> Vec<RecallEntry> {
    let home = home();
    let raw = parse_recalls(&read_log_tail(&home.join(".local/share/synthia/brain/recalls.jsonl")), since_ms);
    let registry = super::squads::read_registry_all(&Dirs::for_home(&home).desk);
    let fleet: Vec<(String, String)> = state.fleet.lock().latest_nodes().into_iter().map(|n| (n.pane_id, n.title)).collect();
    let (brain_cwd, _) = brain_config(&home);
    let ctx = Attribution { registry: &registry, fleet: &fleet, brain_cwd: &brain_cwd };
    let mut out: Vec<RecallEntry> = raw
        .into_iter()
        .map(|(t, r)| {
            let (team, who) = attribute(r.pane.as_deref(), &r.cwd, &ctx);
            RecallEntry { at_ms: t, kind: r.kind, title: r.title, file: r.file, team, who }
        })
        .collect();
    out.sort_by_key(|e| e.at_ms);
    out
}

fn local_midnight_ms() -> i64 {
    use chrono::{Local, TimeZone};
    let d = Local::now().date_naive().and_hms_opt(0, 0, 0).unwrap();
    Local.from_local_datetime(&d).earliest().map(|t| t.timestamp_millis()).unwrap_or(0)
}

fn now_ms() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct KindCount {
    pub kind: String,
    pub count: usize,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LastRecall {
    pub title: String,
    pub at_ms: i64,
    pub kind: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct BrainOverview {
    pub total: usize,
    pub kinds: Vec<KindCount>,
    pub recalled_today: usize,
    pub written_today: usize,
    pub vault_notes: usize,
    pub skills: usize,
    pub roles: usize,
    pub claude_md: usize,
    pub squads: usize,
    pub connectors: usize,
    /// The newest recall for each team, whatever day it was.
    pub last_by_team: BTreeMap<String, LastRecall>,
}

pub fn count_kinds(memories: &[MemoryMeta]) -> Vec<KindCount> {
    let mut m: BTreeMap<&str, usize> = BTreeMap::new();
    for x in memories {
        *m.entry(x.kind.as_str()).or_default() += 1;
    }
    let order = ["reference", "project", "feedback", "bug", "user", "other"];
    order
        .iter()
        .filter_map(|k| m.get(k).map(|c| KindCount { kind: (*k).to_string(), count: *c }))
        .collect()
}

#[tauri::command]
pub fn brain_overview(state: tauri::State<'_, AppState>) -> BrainOverview {
    let s = scan();
    let entries = recall_entries(&state, now_ms() - 30 * 86_400_000);
    let midnight = local_midnight_ms();
    let mut last: BTreeMap<String, LastRecall> = BTreeMap::new();
    for e in &entries {
        last.insert(e.team.key.clone(), LastRecall { title: e.title.clone(), at_ms: e.at_ms, kind: e.kind.clone() });
    }
    BrainOverview {
        total: s.memories.len(),
        kinds: count_kinds(&s.memories),
        recalled_today: entries.iter().filter(|e| e.at_ms >= midnight && e.kind == "read").count(),
        written_today: entries.iter().filter(|e| e.at_ms >= midnight && e.kind == "write").count(),
        vault_notes: s.vault_notes,
        skills: s.skills.len(),
        roles: s.roles.len(),
        claude_md: s.claude_md,
        squads: super::squads::list_squads(&Dirs::for_home(&home())).len(),
        connectors: s.connected.local.len() + s.connected.claude_ai.len(),
        last_by_team: last,
    }
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MemoryRow {
    #[serde(flatten)]
    pub meta: MemoryMeta,
    pub recalls_7d: usize,
    pub recalled_today: usize,
    pub teams_7d: Vec<String>,
}

/// Memories ranked by recalls this week, then by how recently they changed; optionally filtered by a
/// name or description search.
pub fn rank_memories(memories: &[MemoryMeta], entries: &[RecallEntry], midnight: i64, query: Option<&str>) -> Vec<MemoryRow> {
    let q = query.map(|q| q.trim().to_lowercase()).filter(|q| !q.is_empty());
    let mut rows: Vec<MemoryRow> = memories
        .iter()
        .filter(|m| match &q {
            Some(q) => m.name.to_lowercase().contains(q) || m.description.to_lowercase().contains(q),
            None => true,
        })
        .map(|m| {
            let mine: Vec<&RecallEntry> = entries.iter().filter(|e| e.file == m.path).collect();
            let mut teams: Vec<String> = mine.iter().map(|e| e.team.label.split(" · ").next().unwrap_or("").to_string()).collect();
            teams.sort();
            teams.dedup();
            MemoryRow {
                meta: m.clone(),
                recalls_7d: mine.len(),
                recalled_today: mine.iter().filter(|e| e.at_ms >= midnight).count(),
                teams_7d: teams,
            }
        })
        .collect();
    rows.sort_by(|a, b| b.recalls_7d.cmp(&a.recalls_7d).then(b.meta.modified_ms.cmp(&a.meta.modified_ms)));
    rows.truncate(ROW_CAP);
    rows
}

#[tauri::command]
pub fn brain_memories(query: Option<String>, state: tauri::State<'_, AppState>) -> Vec<MemoryRow> {
    let s = scan();
    let entries = recall_entries(&state, now_ms() - WEEK_MS);
    rank_memories(&s.memories, &entries, local_midnight_ms(), query.as_deref())
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct MemoryBody {
    pub name: String,
    pub kind: String,
    pub description: String,
    pub body: String,
}

/// A memory file path is valid when, after resolving symlinks, it is `<projects>/<project>/memory/<file>.md`.
pub fn validate_memory_path(projects: &Path, path: &str) -> AppResult<PathBuf> {
    let root = projects.canonicalize().map_err(|_| AppError::NotFound("memory folders".into()))?;
    let real = Path::new(path).canonicalize().map_err(|_| AppError::NotFound(format!("memory: {path}")))?;
    let rel = real.strip_prefix(&root).map_err(|_| AppError::Path("that file is not a memory".into()))?;
    let parts: Vec<_> = rel.components().collect();
    let ok = parts.len() == 3
        && parts[1].as_os_str() == "memory"
        && real.extension().is_some_and(|e| e == "md")
        && real.is_file();
    if ok {
        Ok(real)
    } else {
        Err(AppError::Path("that file is not a memory".into()))
    }
}

#[tauri::command]
pub fn brain_memory(path: String) -> AppResult<MemoryBody> {
    let real = validate_memory_path(&home().join(".claude/projects"), &path)?;
    let text = std::fs::read_to_string(&real)?;
    let (front, body) = parse_front(&text);
    let file_name = real.file_name().and_then(|n| n.to_str()).unwrap_or_default();
    Ok(MemoryBody {
        name: if front.name.is_empty() { file_name.trim_end_matches(".md").to_string() } else { front.name.clone() },
        kind: kind_of(&front, file_name),
        description: front.description.clone(),
        body: body.chars().take(BODY_CAP).collect(),
    })
}

#[tauri::command]
pub fn brain_recalls(since: i64, state: tauri::State<'_, AppState>) -> Vec<RecallEntry> {
    let mut v = recall_entries(&state, since);
    let n = v.len();
    if n > 300 {
        v.drain(..n - 300);
    }
    v
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SkillsInfo {
    pub skills: Vec<SkillInfo>,
    pub roles: Vec<String>,
    pub claude_md: usize,
    pub squads: usize,
}

#[tauri::command]
pub fn brain_skills() -> SkillsInfo {
    let s = scan();
    SkillsInfo {
        skills: s.skills.clone(),
        roles: s.roles.clone(),
        claude_md: s.claude_md,
        squads: super::squads::list_squads(&Dirs::for_home(&home())).len(),
    }
}

#[tauri::command]
pub fn brain_connected() -> Connected {
    scan().connected.clone()
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct JournalEntry {
    pub name: String,
    /// The first lines of the newest day's journal.
    pub text: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct BrainNow {
    pub session_id: Option<String>,
    pub session_date: Option<String>,
    pub session_modified_ms: Option<i64>,
    pub journal: Option<JournalEntry>,
    pub ledger_done: usize,
    pub ledger_calls: usize,
    pub ledger_waiting: usize,
}

pub fn newest_journal(dir: &Path, lines: usize) -> Option<JournalEntry> {
    let mut files: Vec<PathBuf> = sorted_entries(dir).into_iter().filter(|p| p.extension().is_some_and(|e| e == "md")).collect();
    files.sort();
    let f = files.pop()?;
    let text = std::fs::read_to_string(&f).ok()?;
    Some(JournalEntry {
        name: f.file_name()?.to_str()?.trim_end_matches(".md").to_string(),
        text: text.lines().take(lines).collect::<Vec<_>>().join("\n"),
    })
}

#[tauri::command]
pub fn brain_now() -> BrainNow {
    let home = home();
    let session_path = home.join(".local/share/synthia/brain/session.json");
    let session: Option<serde_json::Value> = std::fs::read_to_string(&session_path).ok().and_then(|t| serde_json::from_str(&t).ok());
    let text = |k: &str| session.as_ref().and_then(|s| s.get(k)).and_then(|v| v.as_str()).map(String::from);
    let ledger = super::today::today_ledger();
    BrainNow {
        session_id: text("session_id"),
        session_date: text("date"),
        session_modified_ms: session.is_some().then(|| mtime_ms(&session_path)),
        journal: newest_journal(&brain_config(&home).1, 40),
        ledger_done: ledger.done_count,
        ledger_calls: ledger.call_count,
        ledger_waiting: ledger.waiting_count,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn temp() -> PathBuf {
        let d = std::env::temp_dir().join(format!("synthia-brain-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&d).unwrap();
        d
    }

    const MEM: &str = "---\nname: project-synthia-jarvis\ndescription: \"Synthia \\\"Jarvis\\\" rebuild: brain moved\"\nmetadata:\n  node_type: memory\n  type: project\n  modified: 2026-10-12\n---\n\nBody line.\n";

    #[test]
    fn frontmatter_and_kinds() {
        let (f, body) = parse_front(MEM);
        assert_eq!(f.name, "project-synthia-jarvis");
        assert_eq!(f.description, "Synthia \"Jarvis\" rebuild: brain moved");
        assert_eq!(f.meta_type, "project");
        assert_eq!(body, "Body line.\n");
        assert_eq!(kind_of(&f, "x.md"), "project");
        // metadata.type wins over a different filename prefix.
        assert_eq!(kind_of(&f, "feedback_x.md"), "project");
        let none = Front::default();
        for (name, want) in [
            ("feedback_rules.md", "feedback"),
            ("project-squads.md", "project"),
            ("reference_ops.md", "reference"),
            ("bug_flaky.md", "bug"),
            ("user_profile.md", "user"),
            ("kimi-cli-path-collision.md", "other"),
            ("gui-tauri-build-mode.md", "other"),
        ] {
            assert_eq!(kind_of(&none, name), want, "{name}");
        }
        let odd = Front { meta_type: "weird".into(), ..Default::default() };
        assert_eq!(kind_of(&odd, "reference_x.md"), "reference");
        assert_eq!(parse_front("no frontmatter").0, Front::default());
    }

    #[test]
    fn scan_counts_by_kind_and_skips_the_index() {
        let root = temp();
        let mem = root.join("-home-me-proj/memory");
        fs::create_dir_all(&mem).unwrap();
        fs::write(mem.join("MEMORY.md"), "# index").unwrap();
        fs::write(mem.join("a.md"), MEM).unwrap();
        fs::write(mem.join("feedback_b.md"), "---\nname: b\ndescription: rule\n---\nx").unwrap();
        fs::write(mem.join("notes.txt"), "x").unwrap();
        let m = scan_memories(&root);
        assert_eq!(m.len(), 2);
        let kinds = count_kinds(&m);
        assert_eq!(kinds, [KindCount { kind: "project".into(), count: 1 }, KindCount { kind: "feedback".into(), count: 1 }]);
        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn attribution_prefers_squad_then_fleet_then_brain_then_other() {
        let mut registry = HashMap::new();
        registry.insert(
            "w1:p2".to_string(),
            Member { squad: "growth".into(), job: "j".into(), role: "growth-writer".into(), title: "Writer".into(), parent: None, ended_at: Some("2026-10-13".into()) },
        );
        let fleet = vec![("w9:p1".to_string(), "Admin panel PR 175".to_string()), ("w1:p2".to_string(), "ignored".to_string())];
        let a = Attribution { registry: &registry, fleet: &fleet, brain_cwd: "/home/u/dev/eventflo" };
        let (t, who) = attribute(Some("w1:p2"), "/x", &a);
        assert_eq!((t.key.as_str(), t.label.as_str(), who.as_str()), ("growth", "Growth · Writer", "Writer"));
        let (t, who) = attribute(Some("w9:p1"), "/x", &a);
        assert_eq!((t.key.as_str(), t.label.as_str(), who.as_str()), ("engineering", "Engineering · Admin panel PR 175", "Admin panel PR 175"));
        assert_eq!(attribute(None, "/home/u/dev/eventflo/", &a).0.key, "synthia");
        assert_eq!(attribute(None, "/elsewhere", &a).0.key, "other");
        // A pane we know nothing about is not the brain, even in the brain's folder.
        assert_eq!(attribute(Some("w7:p7"), "/home/u/dev/eventflo", &a).0.key, "other");
    }

    #[test]
    fn recall_log_parsing_skips_junk_and_old_entries() {
        let log = concat!(
            "{\"at\":\"2026-10-13T08:21:05.123Z\",\"kind\":\"read\",\"file\":\"/m/a.md\",\"title\":\"A\",\"cwd\":\"/x\",\"session_id\":\"s\",\"pane\":null}\n",
            "not json\n",
            "{\"at\":\"2026-10-13T08:30:00Z\",\"kind\":\"write\",\"file\":\"/m/b.md\",\"title\":\"B\",\"cwd\":\"/x\",\"pane\":\"w1:p1\"}\n",
            "{\"at\":\"2026-10-12T08:30:00Z\",\"kind\":\"read\",\"file\":\"/m/c.md\",\"title\":\"C\",\"cwd\":\"/x\"}\n",
            "{\"at\":\"bad\",\"kind\":\"read\",\"file\":\"/m/d.md\"}\n",
            "{\"at\":\"2026-10-13T09:00:00Z\",\"kind\":\"delete\",\"file\":\"/m/e.md\"}\n",
        );
        let since = chrono::DateTime::parse_from_rfc3339("2026-10-13T00:00:00Z").unwrap().timestamp_millis();
        let got = parse_recalls(log, since);
        let titles: Vec<&str> = got.iter().map(|(_, r)| r.title.as_str()).collect();
        assert_eq!(titles, ["A", "B"]);
        assert_eq!(got[1].1.pane.as_deref(), Some("w1:p1"));
    }

    #[test]
    fn memory_path_must_be_a_memory_file() {
        let root = temp();
        let mem = root.join("-p/memory");
        fs::create_dir_all(&mem).unwrap();
        fs::write(mem.join("a.md"), MEM).unwrap();
        fs::write(root.join("-p/other.md"), "x").unwrap();
        fs::write(root.join("secret.md"), "x").unwrap();
        let ok = mem.join("a.md");
        assert!(validate_memory_path(&root, ok.to_str().unwrap()).is_ok());
        assert!(validate_memory_path(&root, root.join("-p/other.md").to_str().unwrap()).is_err());
        assert!(validate_memory_path(&root, root.join("secret.md").to_str().unwrap()).is_err());
        assert!(validate_memory_path(&root, "/etc/passwd").is_err());
        let sneaky = format!("{}/../../../etc/passwd", mem.display());
        assert!(validate_memory_path(&root, &sneaky).is_err());
        let outside = root.join("outside.md");
        fs::write(&outside, "s").unwrap();
        std::os::unix::fs::symlink(&outside, mem.join("link.md")).unwrap();
        assert!(validate_memory_path(&root, mem.join("link.md").to_str().unwrap()).is_err());
        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn ranking_uses_recalls_then_recency_and_search_filters() {
        let meta = |name: &str, d: &str, t: i64| MemoryMeta { path: format!("/m/{name}.md"), name: name.into(), description: d.into(), kind: "feedback".into(), modified_ms: t };
        let mems = [meta("old", "alpha rule", 1), meta("new", "beta rule", 9), meta("used", "gamma", 2)];
        let team = Team { key: "growth".into(), label: "Growth · Writer".into() };
        let entry = |f: &str, at: i64| RecallEntry { at_ms: at, kind: "read".into(), title: "t".into(), file: f.into(), team: team.clone(), who: "Writer".into() };
        let entries = [entry("/m/used.md", 100), entry("/m/used.md", 5)];
        let rows = rank_memories(&mems, &entries, 50, None);
        assert_eq!(rows.iter().map(|r| r.meta.name.as_str()).collect::<Vec<_>>(), ["used", "new", "old"]);
        assert_eq!((rows[0].recalls_7d, rows[0].recalled_today), (2, 1));
        assert_eq!(rows[0].teams_7d, ["Growth"]);
        let found = rank_memories(&mems, &entries, 50, Some("ALPHA"));
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].meta.name, "old");
    }

    #[test]
    fn connectors_are_names_only_and_deduplicated() {
        let json = r#"{"mcpServers":{"tavily":{"env":{"KEY":"secret"}},"eva-core":{}},"projects":{"/a":{"mcpServers":{"astrology":{}, "tavily":{}}}},"claudeAiMcpEverConnected":["claude.ai Gmail","claude.ai Slack"]}"#;
        let c = parse_connected(json);
        assert_eq!(c.local, ["eva-core", "tavily", "astrology"]);
        assert_eq!(c.claude_ai, ["Gmail", "Slack"]);
        assert!(!format!("{c:?}").contains("secret"));
        assert_eq!(parse_connected("nope"), Connected::default());
    }

    #[test]
    fn newest_journal_takes_the_latest_day_and_first_lines() {
        let d = temp();
        fs::write(d.join("2026-10-12.md"), "old").unwrap();
        fs::write(d.join("2026-10-13.md"), (0..60).map(|i| format!("line {i}")).collect::<Vec<_>>().join("\n")).unwrap();
        let j = newest_journal(&d, 40).unwrap();
        assert_eq!(j.name, "2026-10-13");
        assert_eq!(j.text.lines().count(), 40);
        assert!(newest_journal(&d.join("missing"), 40).is_none());
        fs::remove_dir_all(d).ok();
    }
}
