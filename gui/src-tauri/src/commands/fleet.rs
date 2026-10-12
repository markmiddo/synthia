//! Fleet reader: every herdr agent and its Claude sub-agents, as a live org chart.
//!
//! A background task polls `herdr api snapshot` every two seconds, adds sub-agents from the
//! Claude session transcripts, and emits a `fleet` event to the webview only when something
//! changed. Each snapshot is also merged into a per-day record under
//! `~/.local/share/synthia/orgcharts/` so past days can be replayed.

use std::collections::{BTreeMap, HashMap};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use tauri::{Emitter, Manager};

use super::squads::{read_registry, Dirs, Member};
use crate::error::{AppError, AppResult};
use crate::state::AppState;

const HERDR_TIMEOUT: Duration = Duration::from_secs(2);
const POLL_INTERVAL: Duration = Duration::from_secs(2);
/// A sub-agent whose transcript was written within this window is still working.
const SUBAGENT_LIVE_SECS: u64 = 60;
const SUBAGENT_CAP: usize = 12;
/// How long a vanished pane stays on the chart as "gone" before it drops off.
const GONE_GRACE_MS: i64 = 30_000;
/// Rewrite the day file at least this often so `lastSeen` stays fresh.
const DAY_HEARTBEAT_MS: i64 = 30_000;

// ---------------------------------------------------------------------------
// Wire types (camelCase to match the React side)
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SubAgent {
    pub id: String,
    pub description: String,
    pub agent_type: String,
    pub model: String,
    pub live: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct FleetNode {
    pub pane_id: String,
    pub agent: String,
    /// working | needs-you | done | idle | gone
    pub status: String,
    pub title: String,
    pub repo: String,
    pub cwd: String,
    pub session: Option<String>,
    /// Epoch milliseconds when this pane entered its current status (first seen by us).
    pub since_ms: i64,
    pub subagents: Vec<SubAgent>,
    /// Squad membership from the squad registry (all `None` for ordinary agents).
    pub squad: Option<String>,
    pub job: Option<String>,
    pub role: Option<String>,
    pub role_title: Option<String>,
    /// Pane id of the director this specialist reports to.
    pub parent: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct Fleet {
    pub nodes: Vec<FleetNode>,
    pub herdr_ok: bool,
    /// Plain-words reason when herdr could not be read.
    pub error: Option<String>,
}

// ---------------------------------------------------------------------------
// Parsing the herdr snapshot
// ---------------------------------------------------------------------------

#[derive(Deserialize, Debug, Clone)]
struct RawSession {
    value: Option<String>,
}

#[derive(Deserialize, Debug, Clone)]
struct RawAgent {
    pane_id: String,
    #[serde(default)]
    agent: String,
    #[serde(default)]
    agent_status: String,
    #[serde(default)]
    terminal_title_stripped: String,
    #[serde(default)]
    cwd: String,
    agent_session: Option<RawSession>,
}

#[derive(Deserialize)]
struct RawSnapshotFile {
    result: RawResult,
}
#[derive(Deserialize)]
struct RawResult {
    snapshot: RawSnapshot,
}
#[derive(Deserialize)]
struct RawSnapshot {
    #[serde(default)]
    agents: Vec<RawAgent>,
}

fn parse_snapshot(raw: &str) -> Result<Vec<RawAgent>, String> {
    serde_json::from_str::<RawSnapshotFile>(raw)
        .map(|f| f.result.snapshot.agents)
        .map_err(|e| format!("unexpected herdr snapshot format: {e}"))
}

/// herdr statuses: idle, working, blocked, done, unknown.
fn map_status(raw: &str) -> &'static str {
    match raw {
        "working" => "working",
        "blocked" => "needs-you",
        "done" => "done",
        _ => "idle",
    }
}

/// Repo name for a working directory: the first segment under `<home>/dev/eventflo/`,
/// otherwise the last path segment.
fn repo_name(cwd: &str, home: &Path) -> String {
    let eventflo = home.join("dev").join("eventflo");
    if let Ok(rest) = Path::new(cwd).strip_prefix(&eventflo) {
        if let Some(first) = rest.components().next() {
            return first.as_os_str().to_string_lossy().into_owned();
        }
        return "eventflo".to_string();
    }
    Path::new(cwd)
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| cwd.to_string())
}

// ---------------------------------------------------------------------------
// Sub-agents from Claude transcripts
// ---------------------------------------------------------------------------

/// Claude names a project directory after the cwd with `/` and `.` replaced by `-`.
fn project_dir_name(cwd: &str) -> String {
    cwd.chars().map(|c| if c == '/' || c == '.' { '-' } else { c }).collect()
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct SubAgentMeta {
    #[serde(default)]
    description: String,
    #[serde(default)]
    agent_type: String,
    #[serde(default)]
    model: String,
}

fn mtime(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// Sub-agents of one Claude session, newest first, capped. Live means the transcript
/// was modified in the last minute.
fn read_subagents(projects_root: &Path, cwd: &str, session: &str, now: SystemTime) -> Vec<SubAgent> {
    if session.is_empty() || session.contains('/') || session.contains("..") {
        return Vec::new();
    }
    let dir = projects_root.join(project_dir_name(cwd)).join(session).join("subagents");
    let Ok(entries) = std::fs::read_dir(&dir) else {
        return Vec::new();
    };
    let mut metas: Vec<(SystemTime, String, PathBuf, bool)> = Vec::new();
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else { continue };
        let Some(stem) = name.strip_suffix(".meta.json") else { continue };
        let transcript = dir.join(format!("{stem}.jsonl"));
        let modified = mtime(&transcript).or_else(|| mtime(&path));
        let Some(modified) = modified else { continue };
        let live = now
            .duration_since(modified)
            .map(|d| d.as_secs() <= SUBAGENT_LIVE_SECS)
            .unwrap_or(true);
        metas.push((modified, stem.to_string(), path, live));
    }
    metas.sort_by_key(|m| std::cmp::Reverse(m.0));
    metas
        .into_iter()
        .filter_map(|(_, id, path, live)| {
            let meta: SubAgentMeta = serde_json::from_str(&std::fs::read_to_string(path).ok()?).ok()?;
            Some(SubAgent {
                id,
                description: meta.description,
                agent_type: meta.agent_type,
                model: meta.model,
                live,
            })
        })
        .take(SUBAGENT_CAP)
        .collect()
}

// ---------------------------------------------------------------------------
// Tracker: "in this state since", and panes that vanished
// ---------------------------------------------------------------------------

#[derive(Default)]
pub struct FleetTracker {
    /// pane id -> (raw status, epoch ms we first saw it in that status)
    since: HashMap<String, (String, i64)>,
    last_nodes: Vec<FleetNode>,
    /// pane id -> (node frozen as gone, epoch ms to drop it)
    gone: HashMap<String, (FleetNode, i64)>,
}

impl FleetTracker {
    fn update(
        &mut self,
        agents: &[RawAgent],
        now_ms: i64,
        home: &Path,
        registry: &HashMap<String, Member>,
        subagents_for: &dyn Fn(&RawAgent) -> Vec<SubAgent>,
    ) -> Vec<FleetNode> {
        let mut nodes = Vec::with_capacity(agents.len());
        for a in agents {
            let entry = self
                .since
                .entry(a.pane_id.clone())
                .and_modify(|e| {
                    if e.0 != a.agent_status {
                        *e = (a.agent_status.clone(), now_ms);
                    }
                })
                .or_insert_with(|| (a.agent_status.clone(), now_ms));
            let repo = repo_name(&a.cwd, home);
            let title = if a.terminal_title_stripped.trim().is_empty() {
                format!("{} in {}", a.agent, repo)
            } else {
                a.terminal_title_stripped.trim().to_string()
            };
            let member = registry.get(&a.pane_id);
            let some = |s: &str| if s.is_empty() { None } else { Some(s.to_string()) };
            nodes.push(FleetNode {
                squad: member.and_then(|m| some(&m.squad)),
                job: member.and_then(|m| some(&m.job)),
                role: member.and_then(|m| some(&m.role)),
                role_title: member.and_then(|m| some(&m.title)),
                parent: member.and_then(|m| m.parent.clone()),
                pane_id: a.pane_id.clone(),
                agent: a.agent.clone(),
                status: map_status(&a.agent_status).to_string(),
                title,
                repo,
                cwd: a.cwd.clone(),
                session: a.agent_session.as_ref().and_then(|s| s.value.clone()),
                since_ms: entry.1,
                subagents: subagents_for(a),
            });
        }

        let present: Vec<&str> = nodes.iter().map(|n| n.pane_id.as_str()).collect();
        for prev in &self.last_nodes {
            if prev.status != "gone"
                && !present.contains(&prev.pane_id.as_str())
                && !self.gone.contains_key(&prev.pane_id)
            {
                let mut frozen = prev.clone();
                frozen.status = "gone".to_string();
                frozen.since_ms = now_ms;
                for s in &mut frozen.subagents {
                    s.live = false;
                }
                self.gone.insert(prev.pane_id.clone(), (frozen, now_ms + GONE_GRACE_MS));
            }
        }
        self.gone.retain(|pane, (_, expires)| *expires > now_ms && !present.contains(&pane.as_str()));
        self.since.retain(|pane, _| present.contains(&pane.as_str()));

        self.last_nodes = nodes.clone();
        let mut gone: Vec<&(FleetNode, i64)> = self.gone.values().collect();
        gone.sort_by(|a, b| a.0.pane_id.cmp(&b.0.pane_id));
        nodes.extend(gone.into_iter().map(|(n, _)| n.clone()));
        nodes
    }
}

/// Turn the raw output of `herdr api snapshot` (or the reason it failed) into a `Fleet`.
fn build_fleet(
    raw: Result<String, String>,
    tracker: &mut FleetTracker,
    home: &Path,
    registry: &HashMap<String, Member>,
    now: SystemTime,
) -> Fleet {
    let now_ms = now.duration_since(UNIX_EPOCH).map(|d| d.as_millis() as i64).unwrap_or(0);
    let agents = match raw.and_then(|r| parse_snapshot(&r)) {
        Ok(a) => a,
        Err(error) => {
            return Fleet { nodes: Vec::new(), herdr_ok: false, error: Some(error) };
        }
    };
    let projects = home.join(".claude").join("projects");
    let nodes = tracker.update(&agents, now_ms, home, registry, &|a: &RawAgent| {
        match (&a.agent[..], a.agent_session.as_ref().and_then(|s| s.value.as_deref())) {
            ("claude", Some(session)) => read_subagents(&projects, &a.cwd, session, now),
            _ => Vec::new(),
        }
    });
    Fleet { nodes, herdr_ok: true, error: None }
}

// ---------------------------------------------------------------------------
// Daily record
// ---------------------------------------------------------------------------

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct DaySubAgent {
    pub description: String,
    pub agent_type: String,
    pub model: String,
    pub first_seen: i64,
    pub last_seen: i64,
    pub last_live: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct DayNode {
    pub pane_id: String,
    pub agent: String,
    pub title: String,
    pub repo: String,
    pub session: Option<String>,
    pub first_seen: i64,
    pub last_seen: i64,
    pub last_status: String,
    pub subagents: BTreeMap<String, DaySubAgent>,
}

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct DayChart {
    pub date: String,
    pub nodes: BTreeMap<String, DayNode>,
}

/// Merge one snapshot into the day's chart. Returns true when something other than a
/// `lastSeen` timestamp changed (a new node, a new status, a new title or sub-agent).
fn merge_day(chart: &mut DayChart, fleet: &Fleet, now_ms: i64) -> bool {
    let mut changed = false;
    for n in &fleet.nodes {
        // A session id survives a pane being moved; fall back to the pane id.
        let key = n.session.clone().unwrap_or_else(|| n.pane_id.clone());
        let node = chart.nodes.entry(key).or_insert_with(|| {
            changed = true;
            DayNode { first_seen: now_ms, ..DayNode::default() }
        });
        if node.last_status != n.status || node.title != n.title || node.pane_id != n.pane_id {
            changed = true;
        }
        node.pane_id = n.pane_id.clone();
        node.agent = n.agent.clone();
        node.title = n.title.clone();
        node.repo = n.repo.clone();
        node.session = n.session.clone();
        node.last_status = n.status.clone();
        node.last_seen = now_ms;
        for s in &n.subagents {
            let sub = node.subagents.entry(s.id.clone()).or_insert_with(|| {
                changed = true;
                DaySubAgent { first_seen: now_ms, ..DaySubAgent::default() }
            });
            if sub.last_live != s.live {
                changed = true;
            }
            sub.description = s.description.clone();
            sub.agent_type = s.agent_type.clone();
            sub.model = s.model.clone();
            sub.last_live = s.live;
            sub.last_seen = now_ms;
        }
    }
    changed
}

fn orgcharts_dir() -> PathBuf {
    home_dir().join(".local/share/synthia/orgcharts")
}

fn valid_date(date: &str) -> bool {
    date.len() == 10 && chrono::NaiveDate::parse_from_str(date, "%Y-%m-%d").is_ok()
}

fn read_day(dir: &Path, date: &str) -> AppResult<DayChart> {
    if !valid_date(date) {
        return Err(AppError::Validation(format!("bad date: {date}")));
    }
    let name = format!("{date}.json");
    crate::paths::validate_filename(&name)?;
    match std::fs::read_to_string(dir.join(&name)) {
        Ok(text) => Ok(serde_json::from_str(&text)?),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            Ok(DayChart { date: date.to_string(), nodes: BTreeMap::new() })
        }
        Err(e) => Err(e.into()),
    }
}

fn write_day(dir: &Path, chart: &DayChart) -> AppResult<()> {
    std::fs::create_dir_all(dir)?;
    let name = format!("{}.json", chart.date);
    crate::paths::validate_filename(&name)?;
    let tmp = dir.join(format!("{name}.tmp"));
    std::fs::write(&tmp, serde_json::to_string_pretty(chart)?)?;
    std::fs::rename(&tmp, dir.join(name))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// herdr process calls
// ---------------------------------------------------------------------------

async fn run_herdr(args: &[&str]) -> Result<String, String> {
    let mut cmd = tokio::process::Command::new("herdr");
    cmd.args(args).kill_on_drop(true);
    match tokio::time::timeout(HERDR_TIMEOUT, cmd.output()).await {
        Err(_) => Err("herdr did not answer within two seconds".to_string()),
        Ok(Err(e)) if e.kind() == std::io::ErrorKind::NotFound => {
            Err("herdr is not installed or not on the PATH".to_string())
        }
        Ok(Err(e)) => Err(format!("could not run herdr: {e}")),
        Ok(Ok(out)) if !out.status.success() => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            Err(format!("herdr is not running ({})", stderr.trim()))
        }
        Ok(Ok(out)) => Ok(String::from_utf8_lossy(&out.stdout).into_owned()),
    }
}

pub(super) fn home_dir() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string()))
}

async fn collect(state: &AppState) -> Fleet {
    let raw = run_herdr(&["api", "snapshot"]).await;
    let mut tracker = state.fleet.lock();
    let registry = read_registry(&Dirs::for_home(&home_dir()).desk);
    build_fleet(raw, &mut tracker, &home_dir(), &registry, SystemTime::now())
}

/// Arguments for focusing a pane. Pane ids look like `w6521f9f5734061:p1Q0`.
fn focus_args(pane_id: &str) -> AppResult<Vec<String>> {
    let ok = !pane_id.is_empty()
        && pane_id.len() <= 64
        && !pane_id.starts_with('-')
        && pane_id.chars().all(|c| c.is_ascii_alphanumeric() || c == ':' || c == '_' || c == '-');
    if !ok {
        return Err(AppError::Validation(format!("bad pane id: {pane_id}")));
    }
    Ok(vec!["agent".into(), "focus".into(), pane_id.into()])
}

// ---------------------------------------------------------------------------
// Tauri surface
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn fleet_snapshot(state: tauri::State<'_, AppState>) -> Result<Fleet, AppError> {
    Ok(collect(&state).await)
}

#[tauri::command]
pub async fn fleet_focus(pane_id: String) -> AppResult<()> {
    let args = focus_args(&pane_id)?;
    let refs: Vec<&str> = args.iter().map(String::as_str).collect();
    run_herdr(&refs).await.map(|_| ()).map_err(AppError::Process)
}

#[tauri::command]
pub fn fleet_day(date: String) -> AppResult<DayChart> {
    read_day(&orgcharts_dir(), &date)
}

/// Poll herdr every two seconds for the life of the app; emit `fleet` when it changes
/// and keep the day record current.
pub fn spawn_emitter(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        let mut ticker = tokio::time::interval(POLL_INTERVAL);
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut last: Option<Fleet> = None;
        let mut chart: Option<DayChart> = None;
        let mut last_write_ms = 0_i64;
        loop {
            ticker.tick().await;
            let fleet = {
                let state = app.state::<AppState>();
                collect(&state).await
            };
            if last.as_ref() != Some(&fleet) {
                if let Err(e) = app.emit("fleet", &fleet) {
                    eprintln!("fleet: emit failed: {e}");
                }
                last = Some(fleet.clone());
            }
            if !fleet.herdr_ok {
                continue;
            }
            let now = chrono::Local::now();
            let (date, now_ms) = (now.format("%Y-%m-%d").to_string(), now.timestamp_millis());
            if chart.as_ref().map(|c| c.date.as_str()) != Some(date.as_str()) {
                chart = Some(read_day(&orgcharts_dir(), &date).unwrap_or(DayChart {
                    date: date.clone(),
                    nodes: BTreeMap::new(),
                }));
            }
            if let Some(chart) = chart.as_mut() {
                let structural = merge_day(chart, &fleet, now_ms);
                if structural || now_ms - last_write_ms >= DAY_HEARTBEAT_MS {
                    match write_day(&orgcharts_dir(), chart) {
                        Ok(()) => last_write_ms = now_ms,
                        Err(e) => eprintln!("fleet: could not write the day record: {e}"),
                    }
                }
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    const FIXTURE: &str = include_str!("fleet_fixtures/herdr_snapshot.json");
    const HOME: &str = "/home/user";

    fn temp(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("synthia-fleet-{name}-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn at(secs: u64) -> SystemTime {
        UNIX_EPOCH + Duration::from_secs(secs)
    }

    #[test]
    fn parses_the_recorded_snapshot() {
        let agents = parse_snapshot(FIXTURE).unwrap();
        assert_eq!(agents.len(), 4);
        assert_eq!(agents[0].pane_id, "w1:p1");
        assert_eq!(agents[0].terminal_title_stripped, "Gallery drafts PR");
        assert_eq!(
            agents[0].agent_session.as_ref().and_then(|s| s.value.as_deref()),
            Some("11111111-1111-4111-8111-111111111111")
        );
        assert!(agents[3].agent_session.is_none());
    }

    #[test]
    fn rejects_a_malformed_snapshot_with_a_reason() {
        assert!(parse_snapshot("not json").unwrap_err().contains("unexpected herdr snapshot"));
        assert!(parse_snapshot("{\"result\":{}}").is_err());
    }

    #[test]
    fn maps_every_herdr_status() {
        assert_eq!(map_status("working"), "working");
        assert_eq!(map_status("blocked"), "needs-you");
        assert_eq!(map_status("done"), "done");
        assert_eq!(map_status("idle"), "idle");
        assert_eq!(map_status("unknown"), "idle");
        assert_eq!(map_status(""), "idle");
    }

    #[test]
    fn repo_is_first_segment_under_eventflo_else_last_segment() {
        let home = Path::new(HOME);
        assert_eq!(repo_name("/home/user/dev/eventflo/eva-ai", home), "eva-ai");
        assert_eq!(repo_name("/home/user/dev/eventflo/eva-ai/src/deep", home), "eva-ai");
        assert_eq!(repo_name("/home/user/dev/eventflo", home), "eventflo");
        assert_eq!(repo_name("/home/user/dev/misc/synthia/.worktrees/jarvis-see", home), "jarvis-see");
        assert_eq!(repo_name("/home/user/dev/personal", home), "personal");
    }

    #[test]
    fn project_dir_replaces_slashes_and_dots() {
        assert_eq!(
            project_dir_name("/home/user/dev/misc/synthia/.worktrees/x"),
            "-home-user-dev-misc-synthia--worktrees-x"
        );
    }

    fn write_sub(dir: &Path, id: &str, desc: &str, modified_secs: u64, with_transcript: bool) {
        let meta = dir.join(format!("{id}.meta.json"));
        fs::write(
            &meta,
            format!("{{\"agentType\":\"general-purpose\",\"description\":\"{desc}\",\"model\":\"opus\"}}"),
        )
        .unwrap();
        let file = if with_transcript {
            let t = dir.join(format!("{id}.jsonl"));
            fs::write(&t, "{}").unwrap();
            t
        } else {
            meta
        };
        let f = fs::OpenOptions::new().write(true).open(&file).unwrap();
        f.set_modified(at(modified_secs)).unwrap();
    }

    #[test]
    fn finds_subagents_with_liveness_newest_first() {
        let root = temp("subs");
        let dir = root.join("-home-user-dev-misc-synthia").join("sess-1").join("subagents");
        fs::create_dir_all(&dir).unwrap();
        write_sub(&dir, "agent-old", "Old research", 1_000, true);
        write_sub(&dir, "agent-live", "Build the HUD", 10_000, true);
        write_sub(&dir, "agent-bare", "No transcript yet", 9_000, false);
        fs::write(dir.join("notes.txt"), "ignored").unwrap();

        let subs = read_subagents(&root, "/home/user/dev/misc/synthia", "sess-1", at(10_030));
        let ids: Vec<&str> = subs.iter().map(|s| s.id.as_str()).collect();
        assert_eq!(ids, ["agent-live", "agent-bare", "agent-old"]);
        assert!(subs[0].live);
        assert!(!subs[1].live);
        assert!(!subs[2].live);
        assert_eq!(subs[0].description, "Build the HUD");
        assert_eq!(subs[0].agent_type, "general-purpose");
        assert_eq!(subs[0].model, "opus");
        fs::remove_dir_all(root).ok();
    }

    #[test]
    fn caps_subagents_and_survives_missing_or_hostile_input() {
        let root = temp("cap");
        let dir = root.join("-p").join("s").join("subagents");
        fs::create_dir_all(&dir).unwrap();
        for i in 0..20 {
            write_sub(&dir, &format!("agent-{i:02}"), "x", 1_000 + i, true);
        }
        fs::write(dir.join("agent-bad.meta.json"), "{not json").unwrap();
        assert_eq!(read_subagents(&root, "/p", "s", at(5_000)).len(), SUBAGENT_CAP);
        assert!(read_subagents(&root, "/p", "missing", at(5_000)).is_empty());
        assert!(read_subagents(&root, "/p", "../escape", at(5_000)).is_empty());
        assert!(read_subagents(&root, "/p", "", at(5_000)).is_empty());
        fs::remove_dir_all(root).ok();
    }

    fn fleet_at(tracker: &mut FleetTracker, raw: &str, secs: u64) -> Fleet {
        build_fleet(Ok(raw.to_string()), tracker, Path::new(HOME), &HashMap::new(), at(secs))
    }

    #[test]
    fn builds_nodes_and_tracks_time_in_state() {
        let mut tracker = FleetTracker::default();
        let first = fleet_at(&mut tracker, FIXTURE, 100);
        assert!(first.herdr_ok);
        let statuses: Vec<&str> = first.nodes.iter().map(|n| n.status.as_str()).collect();
        assert_eq!(statuses, ["working", "needs-you", "done", "idle"]);
        assert_eq!(first.nodes[0].repo, "eva-ai");
        assert_eq!(first.nodes[1].repo, "eventflo");
        assert_eq!(first.nodes[0].since_ms, 100_000);

        // Same status later: the clock keeps running from first sight.
        let again = fleet_at(&mut tracker, FIXTURE, 160);
        assert_eq!(again.nodes[0].since_ms, 100_000);
        assert_eq!(again, fleet_at(&mut tracker, FIXTURE, 170));

        // A status change resets it.
        let changed = FIXTURE.replacen("\"working\"", "\"done\"", 1);
        let after = fleet_at(&mut tracker, &changed, 200);
        assert_eq!(after.nodes[0].status, "done");
        assert_eq!(after.nodes[0].since_ms, 200_000);
        assert_eq!(after.nodes[1].since_ms, 100_000);
    }

    #[test]
    fn missing_title_falls_back_to_agent_and_repo() {
        let raw = r#"{"result":{"snapshot":{"agents":[
            {"pane_id":"p1","agent":"codex","agent_status":"idle","cwd":"/home/user/dev/personal"}]}}}"#;
        let mut tracker = FleetTracker::default();
        let fleet = fleet_at(&mut tracker, raw, 1);
        assert_eq!(fleet.nodes[0].title, "codex in personal");
    }

    #[test]
    fn vanished_panes_show_as_gone_then_drop_off() {
        let mut tracker = FleetTracker::default();
        fleet_at(&mut tracker, FIXTURE, 100);
        let one_left = r#"{"result":{"snapshot":{"agents":[
            {"pane_id":"w1:p1","agent":"claude","agent_status":"working","cwd":"/home/user/dev/eventflo/eva-ai"}]}}}"#;
        let during = fleet_at(&mut tracker, one_left, 110);
        assert_eq!(during.nodes.len(), 4);
        assert!(during.nodes[1..].iter().all(|n| n.status == "gone"));
        assert_eq!(during.nodes[1].since_ms, 110_000);
        let after = fleet_at(&mut tracker, one_left, 110 + GONE_GRACE_MS as u64 / 1000 + 1);
        assert_eq!(after.nodes.len(), 1);
    }

    fn member(squad: &str, role: &str, title: &str, parent: Option<&str>) -> Member {
        Member {
            squad: squad.into(),
            job: "2026-10-13-posts".into(),
            role: role.into(),
            title: title.into(),
            parent: parent.map(String::from),
            ended_at: None,
        }
    }

    #[test]
    fn registry_members_are_attached_to_fleet_nodes_by_pane_id() {
        let mut registry = HashMap::new();
        registry.insert("w1:p1".to_string(), member("growth", "growth-director", "Director", None));
        registry.insert("w1:p2".to_string(), member("growth", "growth-writer", "Writer", Some("w1:p1")));
        registry.insert("w9:p9".to_string(), member("growth", "growth-seo", "SEO", Some("w1:p1")));
        let mut tracker = FleetTracker::default();
        let fleet = build_fleet(Ok(FIXTURE.to_string()), &mut tracker, Path::new(HOME), &registry, at(100));
        let n = &fleet.nodes;
        assert_eq!(n[0].squad.as_deref(), Some("growth"));
        assert_eq!(n[0].role.as_deref(), Some("growth-director"));
        assert_eq!(n[0].parent, None);
        assert_eq!(n[1].role_title.as_deref(), Some("Writer"));
        assert_eq!(n[1].parent.as_deref(), Some("w1:p1"));
        assert_eq!(n[1].job.as_deref(), Some("2026-10-13-posts"));
        // Ordinary agents carry nothing; registry entries with no pane are ignored.
        assert!(n[2].squad.is_none() && n[2].role.is_none() && n[2].parent.is_none());
        assert_eq!(n.len(), 4);
        let json = serde_json::to_value(&fleet).unwrap();
        assert_eq!(json["nodes"][1]["roleTitle"], "Writer");
        assert!(json["nodes"][2]["squad"].is_null());
    }

    #[test]
    fn herdr_failure_becomes_a_plain_reason_not_an_empty_chart() {
        let mut tracker = FleetTracker::default();
        let fleet = build_fleet(
            Err("herdr is not installed or not on the PATH".into()),
            &mut tracker,
            Path::new(HOME),
            &HashMap::new(),
            at(1),
        );
        assert!(!fleet.herdr_ok);
        assert!(fleet.nodes.is_empty());
        assert_eq!(fleet.error.as_deref(), Some("herdr is not installed or not on the PATH"));
    }

    #[test]
    fn claude_nodes_pick_up_their_subagents() {
        let home = temp("home");
        let dir = home
            .join(".claude/projects/-home-user-dev-eventflo-eva-ai/11111111-1111-4111-8111-111111111111/subagents");
        fs::create_dir_all(&dir).unwrap();
        write_sub(&dir, "agent-a", "Check the migration", 990, true);
        let mut tracker = FleetTracker::default();
        let fleet = build_fleet(Ok(FIXTURE.to_string()), &mut tracker, &home, &HashMap::new(), at(1_000));
        assert_eq!(fleet.nodes[0].subagents.len(), 1);
        assert!(fleet.nodes[0].subagents[0].live);
        assert!(fleet.nodes[1].subagents.is_empty());
        assert!(fleet.nodes[3].subagents.is_empty(), "only claude agents have sub-agents");
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn day_merge_keeps_first_seen_and_flags_real_changes_only() {
        let mut tracker = FleetTracker::default();
        let fleet = fleet_at(&mut tracker, FIXTURE, 100);
        let mut chart = DayChart { date: "2026-10-12".into(), nodes: BTreeMap::new() };
        assert!(merge_day(&mut chart, &fleet, 100_000));
        assert_eq!(chart.nodes.len(), 4);
        let key = "11111111-1111-4111-8111-111111111111";
        assert_eq!(chart.nodes[key].first_seen, 100_000);
        assert_eq!(chart.nodes[key].last_status, "working");
        assert!(chart.nodes.contains_key("w1:p4"), "no session falls back to the pane id");

        assert!(!merge_day(&mut chart, &fleet, 130_000), "only lastSeen moved");
        assert_eq!(chart.nodes[key].first_seen, 100_000);
        assert_eq!(chart.nodes[key].last_seen, 130_000);

        let done = FIXTURE.replacen("\"working\"", "\"done\"", 1);
        let fleet2 = fleet_at(&mut tracker, &done, 140);
        assert!(merge_day(&mut chart, &fleet2, 140_000));
        assert_eq!(chart.nodes[key].last_status, "done");
        assert_eq!(chart.nodes[key].first_seen, 100_000);
    }

    #[test]
    fn day_file_round_trips_and_missing_day_is_empty() {
        let dir = temp("day");
        let mut tracker = FleetTracker::default();
        let fleet = fleet_at(&mut tracker, FIXTURE, 100);
        let mut chart = DayChart { date: "2026-10-12".into(), nodes: BTreeMap::new() };
        merge_day(&mut chart, &fleet, 100_000);
        write_day(&dir, &chart).unwrap();
        assert_eq!(read_day(&dir, "2026-10-12").unwrap(), chart);
        let empty = read_day(&dir, "2026-10-11").unwrap();
        assert_eq!(empty.date, "2026-10-11");
        assert!(empty.nodes.is_empty());
        assert!(!dir.join("2026-10-12.json.tmp").exists());
        fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn day_reads_reject_anything_but_a_date() {
        let dir = temp("baddate");
        for bad in ["../etc/passwd", "2026-13-40", "2026-10-1", "", "2026-10-12.json", "latest"] {
            assert!(read_day(&dir, bad).is_err(), "{bad} should be rejected");
        }
        fs::remove_dir_all(dir).ok();
    }

    #[test]
    fn focus_args_accept_pane_ids_and_reject_anything_else() {
        assert_eq!(
            focus_args("w6521f9f5734061:p1Q0").unwrap(),
            ["agent", "focus", "w6521f9f5734061:p1Q0"]
        );
        for bad in ["", "p1; rm -rf /", "--help", "a b", "p1\n"] {
            assert!(focus_args(bad).is_err(), "{bad:?} should be rejected");
        }
        assert!(focus_args(&"p".repeat(65)).is_err());
    }
}
