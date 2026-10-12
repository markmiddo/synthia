//! The HUD Inbox: finished squad and brain jobs, one JSON file per item.
//!
//! Layout: `~/.local/share/synthia/inbox/items/<id>.json`, written by the Python side. The HUD owns three
//! fields only (`state`, `note`, `decided_at`); every other field, including ones this code does not know,
//! is left exactly as the Python side wrote it. Writes re-read the file, change those fields, and rename a
//! temp file into place.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::squads::{Dirs, Member};
use crate::error::{AppError, AppResult};

const MAX_NOTE_CHARS: usize = 4000;
const MAX_TEXT_BYTES: u64 = 512 * 1024;
const PREVIEW_W: u32 = 1600;
const PREVIEW_QUALITY: u8 = 85;
const STATES: [&str; 4] = ["new", "approved", "sent_back", "archived"];

#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct Deliverable {
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub kind: String,
    #[serde(default)]
    pub bytes: u64,
}

/// What a round of feedback was about: one deliverable, or the whole job (no path).
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct FeedbackTarget {
    pub path: Option<String>,
    #[serde(default)]
    pub title: String,
}

/// One round of Mark's feedback on an item. HUD-owned: the item's `feedback` array.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct FeedbackEntry {
    #[serde(default)]
    pub at: String,
    pub target: Option<FeedbackTarget>,
    #[serde(default)]
    pub note: String,
    /// Who got it: the director's role title, or "revision job".
    #[serde(default)]
    pub routed_to: String,
    /// The revision job started for it, when there was one.
    pub job: Option<String>,
}

/// Wire shape (snake_case, as stored). Every field is optional so an older or newer file still lists.
#[derive(Serialize, Deserialize, Clone, Debug, PartialEq, Default)]
pub struct InboxItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub created_at: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub squad: String,
    #[serde(default)]
    pub job: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub summary_md: String,
    #[serde(default)]
    pub desk: String,
    #[serde(default)]
    pub deliverables: Vec<Deliverable>,
    #[serde(default)]
    pub director: String,
    #[serde(default)]
    pub state: String,
    pub note: Option<String>,
    pub decided_at: Option<String>,
    #[serde(default)]
    pub feedback: Vec<FeedbackEntry>,
}

fn items_dir(home: &Path) -> PathBuf {
    home.join(".local/share/synthia/inbox/items")
}

/// `[0-9A-Za-z_-]{1,96}`
pub fn valid_item_id(id: &str) -> bool {
    !id.is_empty() && id.len() <= 96 && id.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-')
}

fn check_id(id: &str) -> AppResult<()> {
    if valid_item_id(id) {
        Ok(())
    } else {
        Err(AppError::Validation(format!("bad inbox id: {id}")))
    }
}

fn item_path(dir: &Path, id: &str) -> AppResult<PathBuf> {
    check_id(id)?;
    Ok(dir.join(format!("{id}.json")))
}

fn parse_item(text: &str) -> Option<InboxItem> {
    let mut item: InboxItem = serde_json::from_str(text).ok()?;
    if item.state.is_empty() {
        item.state = "new".into();
    }
    (valid_item_id(&item.id)).then_some(item)
}

fn state_rank(s: &str) -> u8 {
    match s {
        "new" => 0,
        "approved" | "sent_back" => 1,
        _ => 2,
    }
}

/// New first, then decided, then archived; newest first within each group.
pub fn sort_items(items: &mut [InboxItem]) {
    items.sort_by(|a, b| {
        state_rank(&a.state)
            .cmp(&state_rank(&b.state))
            .then_with(|| {
                let (ka, kb) = if state_rank(&a.state) == 0 {
                    (&a.created_at, &b.created_at)
                } else {
                    (a.decided_at.as_ref().unwrap_or(&a.created_at), b.decided_at.as_ref().unwrap_or(&b.created_at))
                };
                kb.cmp(ka)
            })
    });
}

pub fn list_items(dir: &Path, state: Option<&str>) -> Vec<InboxItem> {
    let Ok(rd) = std::fs::read_dir(dir) else { return Vec::new() };
    let mut items: Vec<InboxItem> = rd
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "json"))
        .filter_map(|p| std::fs::read_to_string(p).ok())
        .filter_map(|t| parse_item(&t))
        .filter(|i| state.is_none_or(|s| i.state == s))
        .collect();
    sort_items(&mut items);
    items
}

pub fn get_item(dir: &Path, id: &str) -> AppResult<InboxItem> {
    let path = item_path(dir, id)?;
    let text = std::fs::read_to_string(&path).map_err(|_| AppError::NotFound(format!("inbox item {id}")))?;
    parse_item(&text).ok_or_else(|| AppError::Json(format!("inbox item {id} is unreadable")))
}

/// Re-read an item, let `change` edit the raw JSON object, and write it back atomically. Every key the
/// closure does not touch stays exactly as it was on disk, unknown keys included.
fn update_item(dir: &Path, id: &str, change: impl FnOnce(&mut serde_json::Map<String, serde_json::Value>)) -> AppResult<InboxItem> {
    let path = item_path(dir, id)?;
    // Re-read right before writing so a concurrent change by the Python side is kept.
    let text = std::fs::read_to_string(&path).map_err(|_| AppError::NotFound(format!("inbox item {id}")))?;
    let mut value: serde_json::Value = serde_json::from_str(&text)?;
    let obj = value.as_object_mut().ok_or_else(|| AppError::Json("inbox item is not an object".into()))?;
    change(obj);
    let out = serde_json::to_string_pretty(&value)?;
    let tmp = dir.join(format!(".{id}.json.tmp-{}", std::process::id()));
    std::fs::write(&tmp, out)?;
    std::fs::rename(&tmp, &path).inspect_err(|_| {
        let _ = std::fs::remove_file(&tmp);
    })?;
    parse_item(&std::fs::read_to_string(&path)?).ok_or_else(|| AppError::Json("inbox item is unreadable after saving".into()))
}

fn opt_value(v: Option<String>) -> serde_json::Value {
    v.map(serde_json::Value::from).unwrap_or(serde_json::Value::Null)
}

/// Change only `state`, `note` and `decided_at`; every other key stays as written. `note` and
/// `decided_at` are left alone unless given.
pub fn write_decision(dir: &Path, id: &str, state: &str, note: Option<Option<String>>, decided_at: Option<Option<String>>) -> AppResult<InboxItem> {
    if !STATES.contains(&state) {
        return Err(AppError::Validation(format!("bad state: {state}")));
    }
    update_item(dir, id, |obj| {
        obj.insert("state".into(), state.into());
        if let Some(n) = note {
            obj.insert("note".into(), opt_value(n));
        }
        if let Some(d) = decided_at {
            obj.insert("decided_at".into(), opt_value(d));
        }
    })
}

/// Mark an item sent back and append one round to its `feedback` thread, in one write.
pub fn write_feedback(dir: &Path, id: &str, entry: &FeedbackEntry) -> AppResult<InboxItem> {
    let entry_json = serde_json::to_value(entry)?;
    update_item(dir, id, |obj| {
        obj.insert("state".into(), "sent_back".into());
        obj.insert("note".into(), entry.note.clone().into());
        obj.insert("decided_at".into(), entry.at.clone().into());
        let thread = obj.entry("feedback").or_insert_with(|| serde_json::Value::Array(Vec::new()));
        if let Some(arr) = thread.as_array_mut() {
            arr.push(entry_json);
        } else {
            *thread = serde_json::Value::Array(vec![entry_json]);
        }
    })
}

fn now_iso() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%SZ").to_string()
}

fn clean_note(note: &str) -> AppResult<String> {
    let n: String = note.chars().filter(|c| *c != '\0').collect::<String>().trim().to_string();
    if n.is_empty() {
        return Err(AppError::Validation("write a note first".into()));
    }
    if n.chars().count() > MAX_NOTE_CHARS {
        return Err(AppError::Validation("that note is too long".into()));
    }
    Ok(n)
}

// ---------------------------------------------------------------------------
// Files an item points at
// ---------------------------------------------------------------------------

fn is_inside(root: &Path, path: &Path) -> bool {
    match (root.canonicalize(), path.canonicalize()) {
        (Ok(r), Ok(p)) => p.starts_with(r),
        _ => false,
    }
}

/// A file named by an item: it must exist and, once symlinks are resolved, sit inside the item's own
/// `desk/out` folder or the squads root.
pub fn validate_item_file(item: &InboxItem, squads_root: &Path, path: &str) -> AppResult<PathBuf> {
    let real = Path::new(path).canonicalize().map_err(|_| AppError::NotFound(format!("file: {path}")))?;
    if !real.is_file() {
        return Err(AppError::Path("that is not a file".into()));
    }
    let in_out = !item.desk.is_empty() && is_inside(&Path::new(&item.desk).join("out"), &real);
    if in_out || is_inside(squads_root, &real) {
        Ok(real)
    } else {
        Err(AppError::Path("that file is outside the job's folder".into()))
    }
}

fn read_text(path: &Path) -> AppResult<String> {
    let len = std::fs::metadata(path)?.len();
    if len > MAX_TEXT_BYTES {
        return Err(AppError::Validation("that file is too big to show here".into()));
    }
    Ok(String::from_utf8_lossy(&std::fs::read(path)?).into_owned())
}

pub struct Preview {
    pub data_url: String,
    /// True when the JPEG came from the cache (read by the tests).
    #[allow(dead_code)]
    pub cache_hit: bool,
}

fn preview_key(path: &Path, max_w: u32, quality: u8) -> AppResult<String> {
    use sha1::{Digest, Sha1};
    let meta = std::fs::metadata(path)?;
    let mtime = meta.modified().ok().and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok()).map(|d| d.as_nanos()).unwrap_or(0);
    let mut h = Sha1::new();
    h.update(format!("{}|{mtime}|{}|{max_w}|{quality}", path.display(), meta.len()));
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}

fn jpeg_data_url(bytes: &[u8]) -> String {
    use base64::Engine;
    format!("data:image/jpeg;base64,{}", base64::engine::general_purpose::STANDARD.encode(bytes))
}

/// A downscaled JPEG of an image, cached on disk by path, mtime and size. Any size of png or jpg works;
/// a file that will not decode is an error, never a blank.
pub fn make_preview(path: &Path, cache_dir: &Path, max_w: u32, quality: u8) -> AppResult<Preview> {
    let cached = cache_dir.join(format!("{}.jpg", preview_key(path, max_w, quality)?));
    if let Ok(bytes) = std::fs::read(&cached) {
        if !bytes.is_empty() {
            return Ok(Preview { data_url: jpeg_data_url(&bytes), cache_hit: true });
        }
    }
    let img = image::open(path).map_err(|e| AppError::Validation(format!("couldn't decode that image: {e}")))?;
    let img = if img.width() > max_w {
        let h = ((img.height() as u64 * max_w as u64) / img.width() as u64).max(1) as u32;
        img.resize_exact(max_w, h, image::imageops::FilterType::Triangle)
    } else {
        img
    };
    let rgb = img.to_rgb8();
    let mut buf = Vec::new();
    image::codecs::jpeg::JpegEncoder::new_with_quality(&mut buf, quality)
        .encode(rgb.as_raw(), rgb.width(), rgb.height(), image::ColorType::Rgb8)
        .map_err(|e| AppError::Validation(format!("couldn't encode the preview: {e}")))?;
    // A cache that cannot be written is not an error: the preview still shows.
    if std::fs::create_dir_all(cache_dir).is_ok() {
        let tmp = cached.with_extension(format!("tmp-{}", std::process::id()));
        if std::fs::write(&tmp, &buf).is_ok() && std::fs::rename(&tmp, &cached).is_err() {
            let _ = std::fs::remove_file(&tmp);
        }
    }
    Ok(Preview { data_url: jpeg_data_url(&buf), cache_hit: false })
}

pub fn preview_cache_dir(home: &Path) -> PathBuf {
    home.join(".cache/synthia/inbox-previews")
}

// ---------------------------------------------------------------------------
// Sending back
// ---------------------------------------------------------------------------

/// `week-of-posts` from `2026-10-13-week-of-posts`: lowercase letters, digits and dashes only.
pub fn job_slug(job: &str) -> String {
    let bytes = job.as_bytes();
    let dated = bytes.len() > 11 && bytes[4] == b'-' && bytes[7] == b'-' && bytes[10] == b'-' && bytes[..4].iter().all(u8::is_ascii_digit);
    let base = if dated { &job[11..] } else { job };
    let slug: String = base
        .to_ascii_lowercase()
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '-' })
        .collect::<String>()
        .trim_matches('-')
        .chars()
        .take(40)
        .collect();
    if slug.is_empty() { "job".into() } else { slug }
}

/// What the director (or the revision job) is told: where the work is, what it is called, Mark's note
/// word for word, and what to do about it.
pub fn feedback_message(item: &InboxItem, target: Option<&FeedbackTarget>, note: &str) -> String {
    let (what, instruction) = match target {
        Some(t) if t.path.is_some() => (
            format!("Deliverable: {} (\"{}\")", t.path.as_deref().unwrap_or_default(), t.title),
            "Revise only this deliverable. If its text changes, re-run the editor on it. Re-deliver it to out/, then call `synthia-squad done` again.",
        ),
        _ => (
            format!("Deliverable: the whole job (desk {})", item.desk),
            "Revise whatever this note is about and nothing else. If any text changes, re-run the editor on it. Re-deliver to out/, then call `synthia-squad done` again.",
        ),
    };
    format!("Mark sent this back{}.\n{what}\nMark's note, word for word: {note}\n{instruction}", if item.title.is_empty() { String::new() } else { format!(" ({})", item.title) })
}

/// Arguments for `synthia-squad`: ask the live director, or start a revision job.
pub fn send_back_args(item: &InboxItem, message: &str, live_director: Option<&str>) -> Vec<String> {
    match live_director {
        Some(director) => vec!["ask".into(), director.into(), message.into()],
        None => vec![
            "start".into(),
            item.squad.clone(),
            format!("Revise job {} (desk {}). Inbox item: {}.\n{message}", item.job, item.desk, item.id),
            "--slug".into(),
            format!("revise-{}", job_slug(&item.job)),
        ],
    }
}

/// The job id a `synthia-squad start` printed, else the id the engine will have given it today.
pub fn revision_job_id(stdout: &str, slug: &str, today: &str) -> String {
    for tok in stdout.split(|c: char| c.is_whitespace() || c == '/' || c == '"' || c == '\'' || c == ',') {
        let b = tok.as_bytes();
        if b.len() > 11 && b[4] == b'-' && b[7] == b'-' && b[10] == b'-' && b[..4].iter().all(u8::is_ascii_digit) && tok.contains(&format!("revise-{slug}")) {
            return tok.trim_end_matches(['.', ':', ';']).to_string();
        }
    }
    format!("{today}-revise-{slug}")
}

/// The agent name of the item's director if it is live in the registry.
pub fn live_director(item: &InboxItem, registry: &std::collections::HashMap<String, Member>) -> Option<String> {
    registry
        .values()
        .find(|m| {
            m.ended_at.is_none()
                && !m.agent_name.is_empty()
                && m.squad == item.squad
                && (m.agent_name == item.director || (m.parent.is_none() && m.job == item.job))
        })
        .map(|m| m.agent_name.clone())
}

// ---------------------------------------------------------------------------
// Tauri surface
// ---------------------------------------------------------------------------

fn home() -> PathBuf {
    super::fleet::home_dir()
}

#[tauri::command]
pub fn inbox_list(state: Option<String>) -> Vec<InboxItem> {
    list_items(&items_dir(&home()), state.as_deref())
}

#[tauri::command]
pub fn inbox_get(id: String) -> AppResult<InboxItem> {
    get_item(&items_dir(&home()), &id)
}

/// approved | archived | sent_back (without a re-run) | new.
#[tauri::command]
pub fn inbox_decide(id: String, state: String, note: Option<String>) -> AppResult<InboxItem> {
    let note = note.map(|n| clean_note(&n)).transpose()?;
    write_decision(&items_dir(&home()), &id, &state, note.map(Some), Some(Some(now_iso())))
}

/// Put an item back exactly as it was (Undo).
#[tauri::command]
pub fn inbox_restore(id: String, state: String, note: Option<String>, decided_at: Option<String>) -> AppResult<InboxItem> {
    write_decision(&items_dir(&home()), &id, &state, Some(note), Some(decided_at))
}

#[derive(Serialize, Clone, Debug, PartialEq)]
pub struct SendBack {
    /// asked | started
    pub how: String,
    pub detail: String,
    pub routed_to: String,
    pub job: Option<String>,
}

#[tauri::command]
pub async fn inbox_send_back(id: String, note: String, target: Option<FeedbackTarget>) -> AppResult<SendBack> {
    let note = clean_note(&note)?;
    let dir = items_dir(&home());
    let item = get_item(&dir, &id)?;
    super::squads::check_squad_id(&item.squad)?;
    if let Some(p) = target.as_ref().and_then(|t| t.path.as_deref()) {
        // Only a file this item actually delivered can be named.
        if !item.deliverables.iter().any(|d| d.path == p) {
            return Err(AppError::Validation("that file is not part of this item".into()));
        }
    }
    let registry = super::squads::read_registry(&Dirs::for_home(&home()).desk);
    let live = live_director(&item, &registry);
    let role_title = live
        .as_deref()
        .and_then(|a| registry.values().find(|m| m.agent_name == a).map(|m| if m.title.is_empty() { m.role.clone() } else { m.title.clone() }));
    let message = feedback_message(&item, target.as_ref(), &note);
    let args = send_back_args(&item, &message, live.as_deref());
    let slug = job_slug(&item.job);
    let result = super::squads::run_squad(args).await;
    let (routed_to, job) = match (&live, &result) {
        (Some(d), Ok(_)) => (role_title.unwrap_or_else(|| d.clone()), None),
        (None, Ok(out)) => ("revision job".to_string(), Some(revision_job_id(out, &slug, &chrono::Local::now().format("%Y-%m-%d").to_string()))),
        (_, Err(_)) => ("not delivered".to_string(), None),
    };
    // The round is recorded whether or not the squad could be reached, so nothing Mark wrote is lost.
    write_feedback(&dir, &id, &FeedbackEntry { at: now_iso(), target, note, routed_to: routed_to.clone(), job: job.clone() })?;
    match result {
        Ok(out) => Ok(SendBack { how: if live.is_some() { "asked" } else { "started" }.into(), detail: out, routed_to, job }),
        Err(AppError::Process(e)) => Err(AppError::Process(format!("It is marked sent back, but I could not reach the squad: {e}"))),
        Err(e) => Err(e),
    }
}

fn file_for(id: &str, path: &str) -> AppResult<PathBuf> {
    let home = home();
    let item = get_item(&items_dir(&home), id)?;
    validate_item_file(&item, &Dirs::for_home(&home).desk, path)
}

/// Text of a markdown or JSON deliverable.
#[tauri::command]
pub fn inbox_read_file(id: String, path: String) -> AppResult<String> {
    read_text(&file_for(&id, &path)?)
}

/// A downscaled JPEG preview (a data URL) of a png or jpg of any size.
#[tauri::command]
pub async fn inbox_image(id: String, path: String) -> AppResult<String> {
    let real = file_for(&id, &path)?;
    let cache = preview_cache_dir(&home());
    tokio::task::spawn_blocking(move || make_preview(&real, &cache, PREVIEW_W, PREVIEW_QUALITY).map(|p| p.data_url))
        .await
        .map_err(|e| AppError::Process(format!("preview task failed: {e}")))?
}

#[tauri::command]
pub fn inbox_open_file(id: String, path: String) -> AppResult<()> {
    let real = file_for(&id, &path)?;
    let mut child = std::process::Command::new("xdg-open")
        .arg(&real)
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::fs;

    fn temp() -> PathBuf {
        let d = std::env::temp_dir().join(format!("synthia-inbox-{}", uuid::Uuid::new_v4()));
        fs::create_dir_all(&d).unwrap();
        d
    }

    const FULL: &str = r###"{"version":1,"id":"growth-1","created_at":"2026-10-13T08:00:00Z","source":"squad","squad":"growth",
      "job":"2026-10-13-week-of-posts","title":"Growth: week of posts","summary_md":"## Done\n- two posts","desk":"/d/job",
      "deliverables":[{"path":"/d/job/out/a.json","name":"a.json","kind":"json","bytes":10}],"director":"growth-director",
      "state":"new","note":null,"decided_at":null,"notified":{"desk":true,"telegram":false,"email":false},"future_field":{"x":1}}"###;

    #[test]
    fn parses_full_and_minimal_items() {
        let i = parse_item(FULL).unwrap();
        assert_eq!((i.id.as_str(), i.squad.as_str(), i.state.as_str()), ("growth-1", "growth", "new"));
        assert_eq!(i.deliverables[0].kind, "json");
        assert_eq!(i.director, "growth-director");
        let min = parse_item(r#"{"id":"x"}"#).unwrap();
        assert_eq!(min.state, "new", "a missing state reads as new");
        assert!(parse_item("not json").is_none());
        assert!(parse_item(r#"{"id":"../evil"}"#).is_none());
        assert!(parse_item(r#"{"title":"no id"}"#).is_none());
    }

    #[test]
    fn list_sorts_new_first_then_decided_then_archived() {
        let d = temp();
        let put = |id: &str, state: &str, created: &str, decided: &str| {
            fs::write(
                d.join(format!("{id}.json")),
                format!(r#"{{"id":"{id}","state":"{state}","created_at":"{created}","decided_at":{}}}"#, if decided.is_empty() { "null".into() } else { format!("\"{decided}\"") }),
            )
            .unwrap();
        };
        put("old-new", "new", "2026-10-12T01:00:00Z", "");
        put("new-new", "new", "2026-10-13T01:00:00Z", "");
        put("appr", "approved", "2026-10-10T01:00:00Z", "2026-10-13T05:00:00Z");
        put("back", "sent_back", "2026-10-09T01:00:00Z", "2026-10-13T06:00:00Z");
        put("arch", "archived", "2026-10-13T09:00:00Z", "2026-10-13T09:30:00Z");
        fs::write(d.join("junk.json"), "{bad").unwrap();
        fs::write(d.join("note.txt"), "x").unwrap();
        let ids: Vec<String> = list_items(&d, None).into_iter().map(|i| i.id).collect();
        assert_eq!(ids, ["new-new", "old-new", "back", "appr", "arch"]);
        assert_eq!(list_items(&d, Some("archived")).len(), 1);
        assert!(list_items(&d.join("missing"), None).is_empty());
        fs::remove_dir_all(d).ok();
    }

    #[test]
    fn decide_changes_only_the_hud_fields() {
        let d = temp();
        fs::write(d.join("growth-1.json"), FULL).unwrap();
        let after = write_decision(&d, "growth-1", "sent_back", Some(Some("tighten the intro".into())), Some(Some("2026-10-13T09:00:00Z".into()))).unwrap();
        assert_eq!((after.state.as_str(), after.note.as_deref(), after.decided_at.as_deref()), ("sent_back", Some("tighten the intro"), Some("2026-10-13T09:00:00Z")));
        let v: serde_json::Value = serde_json::from_str(&fs::read_to_string(d.join("growth-1.json")).unwrap()).unwrap();
        // Everything the Python side wrote survives, including fields this code has never heard of.
        assert_eq!(v["notified"]["desk"], true);
        assert_eq!(v["future_field"]["x"], 1);
        assert_eq!(v["summary_md"], "## Done\n- two posts");
        assert_eq!(v["deliverables"][0]["bytes"], 10);
        assert_eq!(v["director"], "growth-director");
        // Approving without a note keeps the old note; restore can clear fields.
        let approved = write_decision(&d, "growth-1", "approved", None, Some(Some("t".into()))).unwrap();
        assert_eq!(approved.note.as_deref(), Some("tighten the intro"));
        let restored = write_decision(&d, "growth-1", "new", Some(None), Some(None)).unwrap();
        assert_eq!((restored.state.as_str(), restored.note, restored.decided_at), ("new", None, None));
        // A concurrent change by the other side is picked up, not clobbered.
        let mut v2: serde_json::Value = serde_json::from_str(&fs::read_to_string(d.join("growth-1.json")).unwrap()).unwrap();
        v2["notified"]["telegram"] = true.into();
        fs::write(d.join("growth-1.json"), v2.to_string()).unwrap();
        write_decision(&d, "growth-1", "archived", None, None).unwrap();
        let v3: serde_json::Value = serde_json::from_str(&fs::read_to_string(d.join("growth-1.json")).unwrap()).unwrap();
        assert_eq!(v3["notified"]["telegram"], true);
        assert_eq!(v3["state"], "archived");
        assert!(fs::read_dir(&d).unwrap().filter_map(|e| e.ok()).all(|e| !e.file_name().to_string_lossy().contains(".tmp")), "no temp file is left behind");
        assert!(write_decision(&d, "growth-1", "weird", None, None).is_err());
        assert!(write_decision(&d, "missing", "approved", None, None).is_err());
        assert!(write_decision(&d, "../escape", "approved", None, None).is_err());
        fs::remove_dir_all(d).ok();
    }

    #[test]
    fn ids_and_notes_are_validated() {
        for ok in ["a", "growth-1", "A_b-9", &"x".repeat(96)] {
            assert!(valid_item_id(ok), "{ok}");
        }
        for bad in ["", "a b", "a/b", "..", "a.b", &"x".repeat(97), "é"] {
            assert!(!valid_item_id(bad), "{bad}");
        }
        assert!(item_path(Path::new("/x"), "../etc").is_err());
        assert_eq!(clean_note("  fix it \0 ").unwrap(), "fix it");
        assert!(clean_note("   ").is_err());
        assert!(clean_note(&"x".repeat(MAX_NOTE_CHARS + 1)).is_err());
    }

    #[test]
    fn files_must_sit_in_the_items_desk_out_or_the_squads_root() {
        let root = temp();
        let desk = root.join("squads/growth/jobs/j1");
        fs::create_dir_all(desk.join("out")).unwrap();
        fs::write(desk.join("out/post.md"), "x").unwrap();
        fs::write(desk.join("brief.md"), "x").unwrap();
        let other = root.join("elsewhere");
        fs::create_dir_all(&other).unwrap();
        fs::write(other.join("secret.md"), "s").unwrap();
        let elsewhere_desk = root.join("custom-desk");
        fs::create_dir_all(elsewhere_desk.join("out")).unwrap();
        fs::write(elsewhere_desk.join("out/x.md"), "x").unwrap();

        let squads = root.join("squads");
        let item = InboxItem { desk: desk.to_string_lossy().into(), ..Default::default() };
        let ok = |p: &Path| validate_item_file(&item, &squads, p.to_str().unwrap());
        assert!(ok(&desk.join("out/post.md")).is_ok());
        assert!(ok(&desk.join("brief.md")).is_ok(), "inside the squads root is allowed");
        assert!(ok(&other.join("secret.md")).is_err());
        assert!(ok(Path::new("/etc/passwd")).is_err());
        assert!(ok(&desk.join("out/missing.md")).is_err());
        assert!(ok(&desk.join("out")).is_err(), "a folder is not a file");
        let sneaky = format!("{}/out/../../../../../elsewhere/secret.md", desk.display());
        assert!(validate_item_file(&item, &squads, &sneaky).is_err());
        // An item whose desk is outside the squads root may still read its own out/ folder.
        let item2 = InboxItem { desk: elsewhere_desk.to_string_lossy().into(), ..Default::default() };
        assert!(validate_item_file(&item2, &squads, elsewhere_desk.join("out/x.md").to_str().unwrap()).is_ok());
        assert!(validate_item_file(&item2, &squads, other.join("secret.md").to_str().unwrap()).is_err());
        // A symlink out of the folder is refused.
        std::os::unix::fs::symlink(other.join("secret.md"), desk.join("out/link.md")).unwrap();
        let item3 = InboxItem { desk: desk.to_string_lossy().into(), ..Default::default() };
        assert!(validate_item_file(&item3, &root.join("nowhere"), desk.join("out/link.md").to_str().unwrap()).is_err());
        fs::remove_dir_all(root).ok();
    }

    fn big_png(path: &Path, w: u32, h: u32) {
        let img = image::RgbImage::from_fn(w, h, |x, y| image::Rgb([(x % 251) as u8, (y % 241) as u8, ((x + y) % 239) as u8]));
        img.save(path).unwrap();
    }

    #[test]
    fn previews_are_downscaled_jpegs_that_are_cached() {
        use base64::Engine;
        let d = temp();
        let cache = d.join("cache");
        let src = d.join("cover.png");
        big_png(&src, 3000, 1200);
        let first = make_preview(&src, &cache, 1600, 85).unwrap();
        assert!(!first.cache_hit);
        let b64 = first.data_url.strip_prefix("data:image/jpeg;base64,").unwrap();
        let bytes = base64::engine::general_purpose::STANDARD.decode(b64).unwrap();
        let decoded = image::load_from_memory(&bytes).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (1600, 640), "resized to 1600 wide, aspect kept");
        assert!(bytes.len() < fs::metadata(&src).unwrap().len() as usize, "smaller than the original");
        assert_eq!(fs::read_dir(&cache).unwrap().filter_map(|e| e.ok()).filter(|e| e.path().extension().is_some_and(|x| x == "jpg")).count(), 1);
        let second = make_preview(&src, &cache, 1600, 85).unwrap();
        assert!(second.cache_hit, "the second call reads the cache");
        assert_eq!(first.data_url, second.data_url);
        // A changed file is a new cache entry; a different width is too.
        big_png(&src, 2000, 1000);
        assert!(!make_preview(&src, &cache, 1600, 85).unwrap().cache_hit);
        assert!(!make_preview(&src, &cache, 320, 80).unwrap().cache_hit);
        // Small images are not enlarged.
        let small = d.join("small.png");
        big_png(&small, 200, 100);
        let p = make_preview(&small, &cache, 1600, 85).unwrap();
        let sb = base64::engine::general_purpose::STANDARD.decode(p.data_url.strip_prefix("data:image/jpeg;base64,").unwrap()).unwrap();
        assert_eq!(image::load_from_memory(&sb).unwrap().width(), 200);
        fs::remove_dir_all(d).ok();
    }

    #[test]
    fn a_file_that_will_not_decode_is_an_error() {
        let d = temp();
        fs::write(d.join("bad.png"), b"definitely not a png").unwrap();
        fs::write(d.join("a.txt"), "x").unwrap();
        assert!(make_preview(&d.join("bad.png"), &d.join("c"), 1600, 85).is_err());
        assert!(make_preview(&d.join("a.txt"), &d.join("c"), 1600, 85).is_err());
        assert!(make_preview(&d.join("missing.png"), &d.join("c"), 1600, 85).is_err());
        fs::remove_dir_all(d).ok();
    }

    #[test]
    fn feedback_threads_append_without_touching_other_fields() {
        let d = temp();
        fs::write(d.join("growth-1.json"), FULL).unwrap();
        let target = Some(FeedbackTarget { path: Some("/d/job/out/a.json".into()), title: "Bush doof guide".into() });
        let one = FeedbackEntry { at: "2026-10-13T09:41:00Z".into(), target, note: "too formal".into(), routed_to: "Marketing Director".into(), job: None };
        let after = write_feedback(&d, "growth-1", &one).unwrap();
        assert_eq!((after.state.as_str(), after.note.as_deref(), after.feedback.len()), ("sent_back", Some("too formal"), 1));
        let two = FeedbackEntry { at: "2026-10-13T10:00:00Z".into(), target: None, note: "still off".into(), routed_to: "revision job".into(), job: Some("2026-10-13-revise-week-of-posts".into()) };
        let after = write_feedback(&d, "growth-1", &two).unwrap();
        assert_eq!(after.feedback.len(), 2);
        assert_eq!(after.feedback[0].target.as_ref().unwrap().title, "Bush doof guide");
        assert_eq!(after.feedback[1].job.as_deref(), Some("2026-10-13-revise-week-of-posts"));
        let v: serde_json::Value = serde_json::from_str(&fs::read_to_string(d.join("growth-1.json")).unwrap()).unwrap();
        assert_eq!(v["notified"]["desk"], true);
        assert_eq!(v["future_field"]["x"], 1);
        assert_eq!(v["feedback"][1]["note"], "still off");
        fs::remove_dir_all(d).ok();
    }

    #[test]
    fn send_back_asks_a_live_director_or_starts_a_revision_job() {
        let item = parse_item(FULL).unwrap();
        let target = FeedbackTarget { path: Some("/d/job/out/a.json".into()), title: "Bush doof guide".into() };
        let msg = feedback_message(&item, Some(&target), "The bush doof post reads too formal.");
        assert!(msg.contains("/d/job/out/a.json"), "the file path");
        assert!(msg.contains("Bush doof guide"), "the title");
        assert!(msg.contains("The bush doof post reads too formal."), "the note verbatim");
        assert!(msg.contains("Revise only this deliverable") && msg.contains("re-run the editor") && msg.contains("out/") && msg.contains("synthia-squad done"));
        let whole = feedback_message(&item, None, "everything is off");
        assert!(whole.contains("the whole job (desk /d/job)") && whole.contains("everything is off"));
        let ask = send_back_args(&item, &msg, Some("growth-director-1"));
        assert_eq!(ask, vec!["ask".to_string(), "growth-director-1".into(), msg.clone()]);
        let start = send_back_args(&item, &msg, None);
        assert_eq!(&start[..2], ["start", "growth"]);
        assert!(start[2].starts_with("Revise job 2026-10-13-week-of-posts (desk /d/job). Inbox item: growth-1."));
        assert!(start[2].ends_with(&msg));
        assert_eq!(&start[3..], ["--slug", "revise-week-of-posts"]);
        // The note stays inside one argument whatever it contains.
        let nasty = feedback_message(&item, None, "a \"quoted\" $(thing); rm -rf /");
        assert_eq!(send_back_args(&item, &nasty, None).len(), 5);
        assert_eq!(revision_job_id("Started 2026-10-13-revise-week-of-posts at /x/y", "week-of-posts", "2026-10-14"), "2026-10-13-revise-week-of-posts");
        assert_eq!(revision_job_id("nothing useful", "week-of-posts", "2026-10-14"), "2026-10-14-revise-week-of-posts");
        assert_eq!(job_slug("2026-10-13-Week Of Posts!"), "week-of-posts");
        assert_eq!(job_slug("plain"), "plain");
        assert_eq!(job_slug("2026-10-13-"), "2026-10-13");
        assert_eq!(job_slug("!!!"), "job");

        let mut registry: HashMap<String, Member> = HashMap::new();
        let m = |agent: &str, parent: Option<&str>, ended: Option<&str>| Member {
            agent_name: agent.into(),
            squad: "growth".into(),
            job: "2026-10-13-week-of-posts".into(),
            role: "r".into(),
            title: "t".into(),
            parent: parent.map(String::from),
            ended_at: ended.map(String::from),
        };
        registry.insert("p1".into(), m("growth-director", None, Some("2026-10-13T09:00:00Z")));
        assert_eq!(live_director(&item, &registry), None, "an ended director is not live");
        registry.insert("p2".into(), m("growth-director-2", None, None));
        registry.insert("p3".into(), m("growth-writer-1", Some("p2"), None));
        assert_eq!(live_director(&item, &registry).as_deref(), Some("growth-director-2"));
    }
}
