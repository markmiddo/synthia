//! The "Today" scorecard: ledger counts, merged PRs, squad output and what is due. Everything here
//! is read only; nothing writes to the ledger or the inbox.

use std::path::Path;
use std::sync::OnceLock;
use std::time::{Duration, Instant, UNIX_EPOCH};

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};

const LIST_CAP: usize = 40;
const SHIPPED_TTL: Duration = Duration::from_secs(300);
const GH_TIMEOUT: Duration = Duration::from_secs(20);

// ---------------------------------------------------------------------------
// Ledger
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct LedgerItem {
    pub id: String,
    pub title: String,
    pub detail: String,
    pub recommendation: Option<String>,
    pub undo: Option<String>,
    pub created_at: i64,
    pub links: Vec<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct LedgerSummary {
    pub done_count: usize,
    pub call_count: usize,
    pub waiting_count: usize,
    /// Newest first, capped.
    pub done: Vec<LedgerItem>,
    pub calls: Vec<LedgerItem>,
    pub waiting: Vec<LedgerItem>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct RawLedgerItem {
    #[serde(default)]
    id: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    status: String,
    #[serde(default)]
    created_at: i64,
    detail: Option<String>,
    recommendation: Option<String>,
    undo: Option<String>,
    answer: Option<String>,
    #[serde(default)]
    links: Vec<String>,
}

impl RawLedgerItem {
    fn into_item(self) -> LedgerItem {
        LedgerItem {
            id: self.id,
            title: self.title,
            detail: self.detail.unwrap_or_default(),
            recommendation: self.recommendation,
            undo: self.undo,
            created_at: self.created_at,
            links: self.links,
        }
    }
}

/// Today's done and call items (by local day) and every unresolved blocked item, any day.
/// A blocked item is resolved once it is `answered` or carries an `answer`.
pub fn summarize_ledger(raw: &[String], day_start_ms: i64, day_end_ms: i64) -> LedgerSummary {
    let mut s = LedgerSummary::default();
    let mut done = Vec::new();
    let mut calls = Vec::new();
    let mut waiting = Vec::new();
    for text in raw {
        let Ok(item) = serde_json::from_str::<RawLedgerItem>(text) else {
            continue;
        };
        let today = item.created_at >= day_start_ms && item.created_at < day_end_ms;
        match item.kind.as_str() {
            "done" if today => done.push(item.into_item()),
            "call" if today => calls.push(item.into_item()),
            "blocked" if item.status == "open" && item.answer.is_none() => {
                waiting.push(item.into_item())
            }
            _ => {}
        }
    }
    for v in [&mut done, &mut calls, &mut waiting] {
        v.sort_by_key(|a| std::cmp::Reverse(a.created_at));
    }
    s.done_count = done.len();
    s.call_count = calls.len();
    s.waiting_count = waiting.len();
    for (v, out) in [
        (done, &mut s.done),
        (calls, &mut s.calls),
        (waiting, &mut s.waiting),
    ] {
        *out = v.into_iter().take(LIST_CAP).collect();
    }
    s
}

fn local_day_bounds_ms() -> (i64, i64) {
    use chrono::{Duration as D, Local, TimeZone};
    let today = Local::now().date_naive();
    let start = Local
        .from_local_datetime(&today.and_hms_opt(0, 0, 0).unwrap())
        .earliest();
    let start = start.map(|d| d.timestamp_millis()).unwrap_or(0);
    let end = start + D::hours(24).num_milliseconds();
    (start, end)
}

fn read_dir_texts(dir: &Path, ext: &str) -> Vec<String> {
    let Ok(rd) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    rd.filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == ext))
        .filter_map(|p| std::fs::read_to_string(p).ok())
        .collect()
}

#[tauri::command]
pub fn today_ledger() -> LedgerSummary {
    let dir = super::fleet::home_dir().join(".claude/ledger/items");
    let (start, end) = local_day_bounds_ms();
    summarize_ledger(&read_dir_texts(&dir, "json"), start, end)
}

// ---------------------------------------------------------------------------
// Inbox
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct DueItem {
    pub id: String,
    pub kind: String,
    pub title: String,
    pub due: String,
    pub overdue: bool,
}

#[derive(Deserialize)]
struct InboxFile {
    #[serde(default)]
    items: Vec<RawInboxItem>,
}

#[derive(Deserialize)]
struct RawInboxItem {
    #[serde(default)]
    id: String,
    #[serde(default)]
    kind: String,
    #[serde(default)]
    title: String,
    #[serde(default)]
    status: String,
    due: Option<String>,
}

/// Open inbox items due on or before `today` (`YYYY-MM-DD`), oldest due first.
pub fn due_items(text: &str, today: &str) -> Vec<DueItem> {
    let Ok(file) = serde_json::from_str::<InboxFile>(text) else {
        return Vec::new();
    };
    let mut out: Vec<DueItem> = file
        .items
        .into_iter()
        .filter(|i| i.status == "open")
        .filter_map(|i| {
            let due = i.due?;
            // ISO dates compare correctly as strings.
            (due.as_str() <= today).then(|| DueItem {
                overdue: due.as_str() < today,
                id: i.id,
                kind: i.kind,
                title: i.title,
                due,
            })
        })
        .collect();
    out.sort_by(|a, b| a.due.cmp(&b.due));
    out
}

#[tauri::command]
pub fn today_inbox() -> Vec<DueItem> {
    let path = super::fleet::home_dir().join(".claude/tasks/inbox.json");
    let today = chrono::Local::now().format("%Y-%m-%d").to_string();
    std::fs::read_to_string(path)
        .map(|t| due_items(&t, &today))
        .unwrap_or_default()
}

// ---------------------------------------------------------------------------
// Squad output
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct SquadOutput {
    pub deliverables: usize,
    pub jobs_finished: usize,
}

fn mtime_ms(path: &Path) -> Option<i64> {
    let t = std::fs::metadata(path).ok()?.modified().ok()?;
    Some(t.duration_since(UNIX_EPOCH).ok()?.as_millis() as i64)
}

/// Files written to any job's `out/` today, and jobs whose state is `done` and were last touched today.
pub fn squad_output(desk: &Path, day_start_ms: i64) -> SquadOutput {
    let mut o = SquadOutput::default();
    let Ok(squads) = std::fs::read_dir(desk) else {
        return o;
    };
    for squad in squads.filter_map(|e| e.ok()).filter(|e| e.path().is_dir()) {
        let Ok(jobs) = std::fs::read_dir(squad.path().join("jobs")) else {
            continue;
        };
        for job in jobs.filter_map(|e| e.ok()).filter(|e| e.path().is_dir()) {
            let dir = job.path();
            if let Ok(files) = std::fs::read_dir(dir.join("out")) {
                o.deliverables += files
                    .filter_map(|e| e.ok())
                    .filter(|e| {
                        e.path().is_file() && !e.file_name().to_string_lossy().starts_with('.')
                    })
                    .filter(|e| mtime_ms(&e.path()).is_some_and(|m| m >= day_start_ms))
                    .count();
            }
            let status = dir.join("status.json");
            let done = std::fs::read_to_string(&status)
                .ok()
                .and_then(|t| serde_json::from_str::<serde_json::Value>(&t).ok())
                .and_then(|v| v.get("state").and_then(|s| s.as_str()).map(String::from))
                .is_some_and(|s| s == "done");
            if done && mtime_ms(&status).is_some_and(|m| m >= day_start_ms) {
                o.jobs_finished += 1;
            }
        }
    }
    o
}

#[tauri::command]
pub fn today_squad_output() -> SquadOutput {
    let desk = super::squads::Dirs::for_home(&super::fleet::home_dir()).desk;
    squad_output(&desk, local_day_bounds_ms().0)
}

// ---------------------------------------------------------------------------
// Shipped: merged PRs across the org (via gh, cached)
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct Shipped {
    /// False when gh could not answer; the HUD then shows nothing rather than a wrong zero.
    pub ok: bool,
    pub items: Vec<ShippedPr>,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct ShippedPr {
    pub number: u64,
    pub title: String,
    pub repo: String,
    pub url: String,
}

#[derive(Deserialize)]
struct GhPr {
    number: u64,
    #[serde(default)]
    title: String,
    #[serde(default)]
    url: String,
    repository: Option<GhRepo>,
}

#[derive(Deserialize)]
struct GhRepo {
    #[serde(default)]
    name: String,
}

pub fn parse_shipped(text: &str) -> Option<Vec<ShippedPr>> {
    let prs: Vec<GhPr> = serde_json::from_str(text).ok()?;
    Some(
        prs.into_iter()
            .filter(|p| p.url.starts_with("https://github.com/"))
            .map(|p| ShippedPr {
                number: p.number,
                title: p.title,
                repo: p.repository.map(|r| r.name).unwrap_or_default(),
                url: p.url,
            })
            .collect(),
    )
}

pub fn shipped_args(date: &str) -> Vec<String> {
    ["search", "prs", "--owner", "eventfloHQ", "--merged"]
        .iter()
        .map(|s| s.to_string())
        .chain([
            format!(">={date}"),
            "--json".into(),
            "number,title,repository,url".into(),
            "--limit".into(),
            "100".into(),
        ])
        .collect()
}

static SHIPPED_CACHE: OnceLock<Mutex<Option<(Instant, String, Shipped)>>> = OnceLock::new();

#[tauri::command]
pub async fn today_shipped() -> Shipped {
    let date = chrono::Local::now().format("%Y-%m-%d").to_string();
    let cache = SHIPPED_CACHE.get_or_init(|| Mutex::new(None));
    if let Some((at, d, s)) = cache.lock().as_ref() {
        if d == &date && at.elapsed() < SHIPPED_TTL {
            return s.clone();
        }
    }
    let mut cmd = tokio::process::Command::new("gh");
    cmd.args(shipped_args(&date))
        .stdin(std::process::Stdio::null())
        .kill_on_drop(true);
    let result = match tokio::time::timeout(GH_TIMEOUT, cmd.output()).await {
        Ok(Ok(out)) if out.status.success() => parse_shipped(&String::from_utf8_lossy(&out.stdout))
            .map(|items| Shipped { ok: true, items }),
        _ => None,
    };
    match result {
        Some(s) => {
            *cache.lock() = Some((Instant::now(), date, s.clone()));
            s
        }
        // Failing quietly: keep showing the last good answer for today if there is one.
        None => match cache.lock().as_ref() {
            Some((_, d, s)) if d == &date => s.clone(),
            _ => Shipped::default(),
        },
    }
}

// ---------------------------------------------------------------------------
// Release status (GitHub project board)
// ---------------------------------------------------------------------------

const RELEASE_PROJECT: &str = "16";
const RELEASE_OWNER: &str = "eventfloHQ";
const RELEASE_TTL: Duration = Duration::from_secs(600);
const STATUS_ORDER: [&str; 7] = [
    "Backlog",
    "Ready",
    "In progress",
    "In review",
    "Testing",
    "Ready for Prod",
    "Done",
];

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct StatusCount {
    pub status: String,
    pub count: usize,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct ReleaseStatus {
    pub ok: bool,
    pub title: String,
    pub url: String,
    pub total: usize,
    pub counts: Vec<StatusCount>,
}

/// Count board items by their Status field, in board order (known columns first, then any others).
pub fn count_statuses(item_list_json: &str) -> Option<Vec<StatusCount>> {
    let v: serde_json::Value = serde_json::from_str(item_list_json).ok()?;
    let items = v.get("items")?.as_array()?;
    let mut counts: Vec<StatusCount> = Vec::new();
    for item in items {
        let status = item
            .get("status")
            .and_then(|s| s.as_str())
            .unwrap_or("No status")
            .to_string();
        match counts.iter_mut().find(|c| c.status == status) {
            Some(c) => c.count += 1,
            None => counts.push(StatusCount { status, count: 1 }),
        }
    }
    let rank = |s: &str| {
        STATUS_ORDER
            .iter()
            .position(|k| *k == s)
            .unwrap_or(STATUS_ORDER.len())
    };
    counts.sort_by_key(|c| rank(&c.status));
    Some(counts)
}

pub fn release_args() -> (Vec<String>, Vec<String>) {
    let a = |v: &[&str]| v.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    (
        a(&[
            "project",
            "view",
            RELEASE_PROJECT,
            "--owner",
            RELEASE_OWNER,
            "--format",
            "json",
        ]),
        a(&[
            "project",
            "item-list",
            RELEASE_PROJECT,
            "--owner",
            RELEASE_OWNER,
            "--format",
            "json",
            "--limit",
            "300",
        ]),
    )
}

async fn gh_json(args: Vec<String>) -> Option<String> {
    let mut cmd = tokio::process::Command::new("gh");
    cmd.args(args)
        .stdin(std::process::Stdio::null())
        .kill_on_drop(true);
    match tokio::time::timeout(GH_TIMEOUT, cmd.output()).await {
        Ok(Ok(out)) if out.status.success() => {
            Some(String::from_utf8_lossy(&out.stdout).into_owned())
        }
        _ => None,
    }
}

static RELEASE_CACHE: OnceLock<Mutex<Option<(Instant, ReleaseStatus)>>> = OnceLock::new();

#[tauri::command]
pub async fn today_release() -> ReleaseStatus {
    let cache = RELEASE_CACHE.get_or_init(|| Mutex::new(None));
    if let Some((at, r)) = cache.lock().as_ref() {
        if at.elapsed() < RELEASE_TTL {
            return r.clone();
        }
    }
    let (view_args, list_args) = release_args();
    let fresh = async {
        let list = gh_json(list_args).await?;
        let counts = count_statuses(&list)?;
        let view: Option<serde_json::Value> = gh_json(view_args)
            .await
            .and_then(|t| serde_json::from_str(&t).ok());
        let text = |k: &str| {
            view.as_ref()
                .and_then(|v| v.get(k))
                .and_then(|t| t.as_str())
                .map(String::from)
        };
        Some(ReleaseStatus {
            ok: true,
            title: text("title").unwrap_or_else(|| "Release".into()),
            url: text("url").unwrap_or_else(|| {
                format!("https://github.com/orgs/{RELEASE_OWNER}/projects/{RELEASE_PROJECT}")
            }),
            total: counts.iter().map(|c| c.count).sum(),
            counts,
        })
    }
    .await;
    match fresh {
        Some(r) => {
            *cache.lock() = Some((Instant::now(), r.clone()));
            r
        }
        None => cache
            .lock()
            .as_ref()
            .map(|(_, r)| r.clone())
            .unwrap_or_default(),
    }
}

// ---------------------------------------------------------------------------
// Next meeting (Google Calendar)
// ---------------------------------------------------------------------------

const CAL_TTL: Duration = Duration::from_secs(300);

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct CalEvent {
    pub title: String,
    pub start_ms: i64,
    pub link: String,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct NextMeeting {
    /// ok | not_connected | unavailable
    pub state: String,
    pub next: Option<CalEvent>,
    pub more_today: usize,
}

/// The next timed (not all-day) event starting at or after `now_ms`, and how many timed events follow it.
pub fn parse_events(json: &str, now_ms: i64) -> Option<(Option<CalEvent>, usize)> {
    let v: serde_json::Value = serde_json::from_str(json).ok()?;
    let items = v.get("items")?.as_array()?;
    let mut events: Vec<CalEvent> = items
        .iter()
        .filter(|e| e.get("status").and_then(|s| s.as_str()) != Some("cancelled"))
        .filter_map(|e| {
            let start = e.get("start")?.get("dateTime")?.as_str()?;
            let start_ms = chrono::DateTime::parse_from_rfc3339(start)
                .ok()?
                .timestamp_millis();
            Some(CalEvent {
                title: e
                    .get("summary")
                    .and_then(|t| t.as_str())
                    .unwrap_or("(no title)")
                    .to_string(),
                start_ms,
                link: e
                    .get("htmlLink")
                    .and_then(|t| t.as_str())
                    .unwrap_or_default()
                    .to_string(),
            })
        })
        .filter(|e| e.start_ms >= now_ms)
        .collect();
    events.sort_by_key(|e| e.start_ms);
    let more = events.len().saturating_sub(1);
    Some((events.into_iter().next(), more))
}

static CAL_CACHE: OnceLock<Mutex<Option<(Instant, NextMeeting)>>> = OnceLock::new();

/// A bearer token from the email-triage helper. Kept in memory only: never logged, never in argv.
async fn calendar_token() -> Option<String> {
    let script = super::fleet::home_dir().join(".claude/skills/email-triage/refresh-token.sh");
    let mut cmd = tokio::process::Command::new(script);
    cmd.arg("eventflo")
        .stdin(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .kill_on_drop(true);
    let out = tokio::time::timeout(Duration::from_secs(20), cmd.output())
        .await
        .ok()?
        .ok()?;
    let token = String::from_utf8_lossy(&out.stdout).trim().to_string();
    (out.status.success() && !token.is_empty()).then_some(token)
}

async fn fetch_meeting() -> NextMeeting {
    use chrono::{Duration as D, Local, TimeZone, Utc};
    let unavailable = || NextMeeting {
        state: "unavailable".into(),
        ..Default::default()
    };
    let Some(token) = calendar_token().await else {
        return NextMeeting {
            state: "not_connected".into(),
            ..Default::default()
        };
    };
    let now = Utc::now();
    let tomorrow = Local::now().date_naive() + D::days(1);
    let end = Local
        .from_local_datetime(&tomorrow.and_hms_opt(0, 0, 0).unwrap())
        .earliest()
        .map(|d| d.with_timezone(&Utc))
        .unwrap_or(now + D::hours(24));
    let fmt = |t: chrono::DateTime<Utc>| t.format("%Y-%m-%dT%H:%M:%SZ").to_string();
    let client = reqwest::Client::new();
    let resp = client
        .get("https://www.googleapis.com/calendar/v3/calendars/primary/events")
        .query(&[
            ("timeMin", fmt(now)),
            ("timeMax", fmt(end)),
            ("singleEvents", "true".into()),
            ("orderBy", "startTime".into()),
            ("maxResults", "10".into()),
        ])
        .bearer_auth(&token)
        .timeout(Duration::from_secs(15))
        .send()
        .await;
    let Ok(resp) = resp else { return unavailable() };
    if matches!(resp.status().as_u16(), 401 | 403) {
        return NextMeeting {
            state: "not_connected".into(),
            ..Default::default()
        };
    }
    if !resp.status().is_success() {
        return unavailable();
    }
    let Ok(text) = resp.text().await else {
        return unavailable();
    };
    match parse_events(&text, now.timestamp_millis()) {
        Some((next, more_today)) => NextMeeting {
            state: "ok".into(),
            next,
            more_today,
        },
        None => unavailable(),
    }
}

#[tauri::command]
pub async fn today_meeting() -> NextMeeting {
    let cache = CAL_CACHE.get_or_init(|| Mutex::new(None));
    if let Some((at, m)) = cache.lock().as_ref() {
        if at.elapsed() < CAL_TTL {
            return m.clone();
        }
    }
    let m = fetch_meeting().await;
    *cache.lock() = Some((Instant::now(), m.clone()));
    m
}

// ---------------------------------------------------------------------------
// Spend today (share of the weekly Claude limit used since the first reading today)
// ---------------------------------------------------------------------------

const KEEP_DAYS: i64 = 14;
const MIN_GAP_MS: i64 = 10 * 60_000;

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq)]
pub struct Reading {
    pub t: i64,
    pub pct: f64,
    pub resets: String,
}

#[derive(Serialize, Deserialize, Default)]
struct UsageDays {
    #[serde(default)]
    readings: Vec<Reading>,
}

#[derive(Serialize, Clone, Debug, PartialEq, Default)]
#[serde(rename_all = "camelCase")]
pub struct SpendToday {
    pub ok: bool,
    /// Percentage points of the weekly limit used today.
    pub percent: f64,
    /// Running spend at each of today's readings, for the sparkline.
    pub points: Vec<f64>,
}

/// A reset moment compared to the minute: the API's sub-second jitter is not a reset.
fn reset_key(r: &str) -> &str {
    r.get(..16).unwrap_or(r)
}

/// Spend since the first reading in `readings`: each stretch inside one weekly window counts
/// (last - first); a reset starts a new stretch, so usage before the reset is kept.
pub fn spend(readings: &[Reading]) -> SpendToday {
    if readings.is_empty() {
        return SpendToday::default();
    }
    let mut total = 0.0;
    let mut points = Vec::with_capacity(readings.len());
    let mut seg_first = &readings[0];
    let mut seg_last = &readings[0];
    for r in readings {
        if reset_key(&r.resets) != reset_key(&seg_first.resets) {
            total += (seg_last.pct - seg_first.pct).max(0.0);
            seg_first = r;
        }
        seg_last = r;
        points.push(total + (r.pct - seg_first.pct).max(0.0));
    }
    total += (seg_last.pct - seg_first.pct).max(0.0);
    SpendToday {
        ok: true,
        percent: total,
        points,
    }
}

fn usage_path(home: &Path) -> std::path::PathBuf {
    home.join(".local/share/synthia/usage-days.json")
}

fn read_usage(path: &Path) -> UsageDays {
    std::fs::read_to_string(path)
        .ok()
        .and_then(|t| serde_json::from_str(&t).ok())
        .unwrap_or_default()
}

/// Add a reading unless it repeats the last one, and drop anything older than 14 days.
pub fn push_reading(days: &mut Vec<Reading>, r: Reading) {
    let skip = days
        .last()
        .is_some_and(|l| l.pct == r.pct && l.resets == r.resets && r.t - l.t < MIN_GAP_MS);
    if !skip {
        days.push(r.clone());
    }
    let cutoff = r.t - KEEP_DAYS * 86_400_000;
    days.retain(|x| x.t >= cutoff);
}

/// Called after every good usage fetch. Fails quietly.
pub fn record_usage(home: &Path, seven_day_pct: f64, resets_at: &str) {
    let path = usage_path(home);
    let mut file = read_usage(&path);
    let t = chrono::Utc::now().timestamp_millis();
    push_reading(
        &mut file.readings,
        Reading {
            t,
            pct: seven_day_pct,
            resets: resets_at.to_string(),
        },
    );
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(text) = serde_json::to_string(&file) {
        let tmp = path.with_extension("tmp");
        if std::fs::write(&tmp, text).is_ok() {
            let _ = std::fs::rename(&tmp, &path);
        }
    }
}

#[tauri::command]
pub fn today_spend() -> SpendToday {
    let file = read_usage(&usage_path(&super::fleet::home_dir()));
    let (start, end) = local_day_bounds_ms();
    let today: Vec<Reading> = file
        .readings
        .into_iter()
        .filter(|r| r.t >= start && r.t < end)
        .collect();
    spend(&today)
}

/// Open a merged PR in the browser. Only github.com links.
#[tauri::command]
pub fn open_url(url: String) -> AppResult<()> {
    if !valid_github_url(&url) {
        return Err(AppError::Validation(
            "I only open GitHub and Google Calendar links".into(),
        ));
    }
    let mut child = std::process::Command::new("xdg-open")
        .arg(&url)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .map_err(|e| AppError::Process(format!("could not run xdg-open: {e}")))?;
    std::thread::spawn(move || {
        let _ = child.wait();
    });
    Ok(())
}

pub fn valid_github_url(url: &str) -> bool {
    [
        "https://github.com/",
        "https://calendar.google.com/",
        "https://www.google.com/calendar/",
    ]
    .iter()
    .any(|p| url.starts_with(p))
        && url.len() <= 300
        && url
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || "/-_.#?=&%:~+".contains(c))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::SystemTime;

    fn item(id: &str, kind: &str, status: &str, at: i64, extra: &str) -> String {
        format!(
            r#"{{"id":"{id}","kind":"{kind}","title":"t-{id}","status":"{status}","createdAt":{at}{extra}}}"#
        )
    }

    #[test]
    fn ledger_counts_today_and_every_unresolved_blocked_item() {
        let (start, end) = (1_000_000, 1_000_000 + 86_400_000);
        let raw = vec![
            item("d1", "done", "seen", start + 5, ""),
            item("d2", "done", "open", start + 50, ""),
            item("d-old", "done", "seen", start - 1, ""),
            item("d-tomorrow", "done", "seen", end, ""),
            item(
                "c1",
                "call",
                "seen",
                start + 9,
                r#","detail":"why","undo":"revert""#,
            ),
            item("c-old", "call", "seen", start - 100, ""),
            item(
                "b-open",
                "blocked",
                "open",
                start - 9_999_999,
                r#","recommendation":"yes""#,
            ),
            item("b-seen", "blocked", "seen", start + 1, ""),
            item(
                "b-answered",
                "blocked",
                "answered",
                start + 2,
                r#","answer":"yes""#,
            ),
            item(
                "b-answer-only",
                "blocked",
                "seen",
                start + 3,
                r#","answer":"no""#,
            ),
            "{not json".to_string(),
            item("x", "mystery", "open", start + 1, ""),
        ];
        let s = summarize_ledger(&raw, start, end);
        assert_eq!((s.done_count, s.call_count, s.waiting_count), (2, 1, 1));
        assert_eq!(s.done[0].id, "d2", "newest first");
        assert_eq!(s.calls[0].detail, "why");
        assert_eq!(s.calls[0].undo.as_deref(), Some("revert"));
        let ids: Vec<&str> = s.waiting.iter().map(|i| i.id.as_str()).collect();
        assert_eq!(
            ids,
            ["b-open"],
            "waiting = open only (matches the ledger panel), any day"
        );
        assert_eq!(s.waiting[0].recommendation.as_deref(), Some("yes"));
    }

    #[test]
    fn ledger_lists_are_capped_but_counts_are_not() {
        let raw: Vec<String> = (0..60)
            .map(|i| item(&format!("d{i}"), "done", "seen", 10 + i, ""))
            .collect();
        let s = summarize_ledger(&raw, 0, 1000);
        assert_eq!((s.done_count, s.done.len()), (60, LIST_CAP));
    }

    #[test]
    fn inbox_keeps_open_items_due_today_or_overdue() {
        let text = r#"{"items":[
          {"id":"a","kind":"pay","title":"Pay Vishal","due":"2026-10-10","status":"open"},
          {"id":"b","kind":"reply","title":"Reply Josh","due":"2026-10-13","status":"open"},
          {"id":"c","kind":"note","title":"Later","due":"2026-10-20","status":"open"},
          {"id":"d","kind":"note","title":"No due","due":null,"status":"open"},
          {"id":"e","kind":"pay","title":"Paid","due":"2026-10-01","status":"done"},
          {"id":"f","kind":"note","title":"Expired","due":"2026-10-01","status":"expired"}]}"#;
        let got = due_items(text, "2026-10-13");
        let view: Vec<(&str, bool)> = got.iter().map(|d| (d.id.as_str(), d.overdue)).collect();
        assert_eq!(view, [("a", true), ("b", false)]);
        assert!(due_items("{bad", "2026-10-13").is_empty());
        assert!(due_items(r#"{"nope":1}"#, "2026-10-13").is_empty());
    }

    #[test]
    fn shipped_parses_gh_json_and_builds_a_plain_argument_array() {
        let text = r#"[{"number":7,"title":"Fix it","url":"https://github.com/eventfloHQ/eva-ai/pull/7","repository":{"name":"eva-ai","nameWithOwner":"eventfloHQ/eva-ai"}},
                       {"number":8,"title":"Odd","url":"file:///etc/passwd","repository":null}]"#;
        let prs = parse_shipped(text).unwrap();
        assert_eq!(prs.len(), 1);
        assert_eq!((prs[0].repo.as_str(), prs[0].number), ("eva-ai", 7));
        assert!(parse_shipped("nonsense").is_none());
        let args = shipped_args("2026-10-13");
        assert_eq!(
            args[..5],
            ["search", "prs", "--owner", "eventfloHQ", "--merged"]
        );
        assert_eq!(args[5], ">=2026-10-13");
        assert!(valid_github_url(
            "https://github.com/eventfloHQ/eva-ai/pull/7"
        ));
        assert!(valid_github_url(
            "https://www.google.com/calendar/event?eid=abc123"
        ));
        assert!(!valid_github_url("https://evil.com/x"));
        assert!(!valid_github_url("https://github.com.evil.com/x"));
        assert!(!valid_github_url("https://github.com/a b; rm"));
    }

    #[test]
    fn squad_output_counts_todays_files_and_finished_jobs() {
        let desk = std::env::temp_dir().join(format!("synthia-today-{}", uuid::Uuid::new_v4()));
        let job = desk.join("growth/jobs/2026-10-13-x");
        fs::create_dir_all(job.join("out")).unwrap();
        fs::write(job.join("out/a.md"), "x").unwrap();
        fs::write(job.join("out/.hidden"), "x").unwrap();
        fs::write(job.join("status.json"), r#"{"state":"done"}"#).unwrap();
        let running = desk.join("growth/jobs/2026-10-13-y");
        fs::create_dir_all(&running).unwrap();
        fs::write(running.join("status.json"), r#"{"state":"working"}"#).unwrap();
        let now_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as i64;
        let o = squad_output(&desk, now_ms - 60_000);
        assert_eq!((o.deliverables, o.jobs_finished), (1, 1));
        let tomorrow = squad_output(&desk, now_ms + 86_400_000);
        assert_eq!((tomorrow.deliverables, tomorrow.jobs_finished), (0, 0));
        assert_eq!(
            squad_output(&desk.join("missing"), 0),
            SquadOutput::default()
        );
        fs::remove_dir_all(desk).ok();
    }

    fn rd(t: i64, pct: f64, resets: &str) -> Reading {
        Reading {
            t,
            pct,
            resets: resets.into(),
        }
    }

    #[test]
    fn spend_is_current_minus_first_reading_of_the_day() {
        let r = [
            rd(1, 30.0, "2026-10-16T09:00:00Z"),
            rd(2, 33.0, "2026-10-16T09:00:00Z"),
            rd(3, 36.5, "2026-10-16T09:00:00.4Z"),
        ];
        let s = spend(&r);
        assert!(s.ok);
        assert!((s.percent - 6.5).abs() < 1e-9);
        assert_eq!(s.points.len(), 3);
        assert_eq!(s.points[0], 0.0);
        assert_eq!(spend(&[]), SpendToday::default());
    }

    #[test]
    fn spend_keeps_pre_reset_usage_across_a_weekly_reset() {
        let r = [
            rd(1, 90.0, "2026-10-14T09:00:00Z"),
            rd(2, 97.0, "2026-10-14T09:00:00Z"),
            rd(3, 2.0, "2026-10-21T09:00:00Z"),
            rd(4, 5.0, "2026-10-21T09:00:00Z"),
        ];
        let s = spend(&r);
        assert!(
            (s.percent - 10.0).abs() < 1e-9,
            "7 before the reset + 3 after"
        );
        assert_eq!(s.points, [0.0, 7.0, 7.0, 10.0]);
    }

    #[test]
    fn readings_are_deduped_and_pruned_to_fourteen_days() {
        let day = 86_400_000;
        let mut v = vec![rd(0, 1.0, "a"), rd(20 * day, 5.0, "a")];
        push_reading(&mut v, rd(20 * day + 1000, 5.0, "a"));
        assert_eq!(v.len(), 1, "old reading pruned, repeat skipped");
        push_reading(&mut v, rd(20 * day + 2000, 6.0, "a"));
        push_reading(&mut v, rd(20 * day + MIN_GAP_MS + 5000, 6.0, "a"));
        assert_eq!(v.len(), 3);
    }

    #[test]
    fn release_counts_by_status_in_board_order() {
        let json = r#"{"items":[{"status":"Done"},{"status":"In review"},{"status":"Done"},{"status":"Backlog"},{"status":"Weird"},{}]}"#;
        let c = count_statuses(json).unwrap();
        let view: Vec<(&str, usize)> = c.iter().map(|x| (x.status.as_str(), x.count)).collect();
        assert_eq!(
            view,
            [
                ("Backlog", 1),
                ("In review", 1),
                ("Done", 2),
                ("Weird", 1),
                ("No status", 1)
            ]
        );
        assert!(count_statuses("nope").is_none());
        assert!(count_statuses(r#"{"x":1}"#).is_none());
        let (view_args, list_args) = release_args();
        assert_eq!(view_args[..3], ["project", "view", "16"]);
        assert!(list_args.contains(&"300".to_string()));
    }

    #[test]
    fn calendar_picks_the_next_timed_event_and_counts_the_rest() {
        let json = r#"{"items":[
          {"summary":"All day","start":{"date":"2026-10-13"},"htmlLink":"https://x/0"},
          {"summary":"Past","start":{"dateTime":"2026-10-13T08:00:00+11:00"},"htmlLink":"https://x/p"},
          {"summary":"Standup","start":{"dateTime":"2026-10-13T10:30:00+11:00"},"htmlLink":"https://x/1"},
          {"summary":"Cancelled","status":"cancelled","start":{"dateTime":"2026-10-13T10:45:00+11:00"}},
          {"summary":"Dentist","start":{"dateTime":"2026-10-13T14:00:00+11:00"},"htmlLink":"https://x/2"},
          {"summary":"Pub","start":{"dateTime":"2026-10-13T17:00:00+11:00"}}]}"#;
        let now = chrono::DateTime::parse_from_rfc3339("2026-10-13T09:00:00+11:00")
            .unwrap()
            .timestamp_millis();
        let (next, more) = parse_events(json, now).unwrap();
        let next = next.unwrap();
        assert_eq!(
            (next.title.as_str(), next.link.as_str(), more),
            ("Standup", "https://x/1", 2)
        );
        assert_eq!(parse_events(r#"{"items":[]}"#, now).unwrap(), (None, 0));
        assert!(parse_events("{bad", now).is_none());
    }
}
