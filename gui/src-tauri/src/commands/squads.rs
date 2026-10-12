//! Squads: the AI teams org chart. Reads squad definitions, role agent files and job desks,
//! merges the squad registry into the fleet, and saves role edits back.
//!
//! Layout (all under the user's home):
//! - `~/.config/synthia/squads/<id>.yaml`          squad definition
//! - `~/.claude/agents/<role>.md`                  role prompt (frontmatter + markdown body)
//! - `~/.local/share/synthia/squads/registry.json` live members, written by the Python engine
//! - `~/.local/share/synthia/squads/<squad>/jobs/<job>/status.json`  job desks

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};

pub const MODELS: [&str; 3] = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"];
const RECENT_JOBS: usize = 6;
const MAX_PROMPT_BYTES: usize = 100_000;
const MAX_TITLE_CHARS: usize = 80;

// ---------------------------------------------------------------------------
// Locations and validation
// ---------------------------------------------------------------------------

#[derive(Clone, Debug)]
pub struct Dirs {
    pub config: PathBuf,
    pub agents: PathBuf,
    pub desk: PathBuf,
}

impl Dirs {
    pub fn for_home(home: &Path) -> Self {
        Dirs {
            config: home.join(".config/synthia/squads"),
            agents: home.join(".claude/agents"),
            desk: home.join(".local/share/synthia/squads"),
        }
    }
}

/// `[a-z][a-z0-9_-]{0,31}`
pub fn valid_id(id: &str) -> bool {
    let b = id.as_bytes();
    !b.is_empty()
        && b.len() <= 32
        && b[0].is_ascii_lowercase()
        && b.iter().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || *c == b'_' || *c == b'-')
}

fn check_id(kind: &str, id: &str) -> AppResult<()> {
    if valid_id(id) {
        Ok(())
    } else {
        Err(AppError::Validation(format!("bad {kind} id: {id}")))
    }
}

/// True when `path` (after resolving symlinks) is inside `root` (also resolved).
fn is_inside(root: &Path, path: &Path) -> bool {
    match (root.canonicalize(), path.canonicalize()) {
        (Ok(r), Ok(p)) => p.starts_with(r),
        _ => false,
    }
}

// ---------------------------------------------------------------------------
// Registry (shared contract, written only by the Python engine)
// ---------------------------------------------------------------------------

#[derive(Deserialize, Clone, Debug, PartialEq)]
pub struct Member {
    #[serde(default)]
    pub squad: String,
    #[serde(default)]
    pub job: String,
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub title: String,
    pub parent: Option<String>,
    pub ended_at: Option<String>,
}

#[derive(Deserialize)]
struct RegistryFile {
    #[serde(default)]
    members: HashMap<String, Member>,
}

static REGISTRY_WARNED: AtomicBool = AtomicBool::new(false);

/// Parse registry.json text.
pub fn parse_registry(text: &str) -> Result<HashMap<String, Member>, String> {
    serde_json::from_str::<RegistryFile>(text).map(|f| f.members).map_err(|e| e.to_string())
}

/// Live registry members by pane id. A missing or corrupt file is fine: no squads are shown.
/// A corrupt file is logged once, not every poll.
pub fn read_registry(desk: &Path) -> HashMap<String, Member> {
    let path = desk.join("registry.json");
    let text = match std::fs::read_to_string(&path) {
        Ok(t) => t,
        Err(_) => return HashMap::new(),
    };
    match parse_registry(&text) {
        Ok(m) => {
            REGISTRY_WARNED.store(false, Ordering::Relaxed);
            m.into_iter().filter(|(_, v)| v.ended_at.is_none()).collect()
        }
        Err(e) => {
            if !REGISTRY_WARNED.swap(true, Ordering::Relaxed) {
                eprintln!("squads: ignoring unreadable registry.json: {e}");
            }
            HashMap::new()
        }
    }
}

// ---------------------------------------------------------------------------
// Wire types
// ---------------------------------------------------------------------------

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct RoleInfo {
    pub id: String,
    pub title: String,
    pub model: String,
    pub hires: Vec<String>,
    pub description: String,
    /// The agent file body: the role's prompt.
    pub prompt: String,
    /// False when `~/.claude/agents/<role>.md` does not exist yet.
    pub has_agent_file: bool,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct JobInfo {
    pub id: String,
    pub path: String,
    pub state: String,
    pub updated_ms: i64,
    pub last_log: Option<String>,
}

#[derive(Serialize, Clone, Debug, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct SquadInfo {
    pub id: String,
    pub name: String,
    pub director: String,
    pub cap: u32,
    pub cwd: String,
    pub roles: Vec<RoleInfo>,
    pub jobs: Vec<JobInfo>,
}

#[derive(Deserialize, Debug, Default)]
#[serde(rename_all = "camelCase")]
pub struct RoleFields {
    pub title: Option<String>,
    pub model: Option<String>,
    pub hires: Option<Vec<String>>,
    pub prompt: Option<String>,
}

// ---------------------------------------------------------------------------
// Agent files
// ---------------------------------------------------------------------------

/// Split `---\nfrontmatter\n---\nbody`. No frontmatter means everything is body.
fn split_frontmatter(text: &str) -> (Option<&str>, &str) {
    let rest = match text.strip_prefix("---\n") {
        Some(r) => r,
        None => return (None, text),
    };
    if let Some(end) = rest.find("\n---\n") {
        return (Some(&rest[..end]), &rest[end + 5..]);
    }
    if let Some(fm) = rest.strip_suffix("\n---") {
        return (Some(fm), "");
    }
    (None, text)
}

/// Read a top-level `key: value` from frontmatter, tolerating unquoted colons in values.
fn frontmatter_value(fm: &str, key: &str) -> Option<String> {
    for line in fm.lines() {
        if let Some(v) = line.strip_prefix(key).and_then(|r| r.strip_prefix(':')) {
            let v = v.trim();
            let v = v
                .strip_prefix('"')
                .and_then(|s| s.strip_suffix('"'))
                .or_else(|| v.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')))
                .unwrap_or(v);
            return Some(v.to_string());
        }
    }
    None
}

struct AgentFile {
    description: String,
    model: String,
    body: String,
}

fn read_agent_file(dirs: &Dirs, role: &str) -> Option<AgentFile> {
    let path = dirs.agents.join(format!("{role}.md"));
    if !is_inside(&dirs.agents, &path) {
        return None;
    }
    let text = std::fs::read_to_string(path).ok()?;
    let (fm, body) = split_frontmatter(&text);
    Some(AgentFile {
        description: fm.and_then(|f| frontmatter_value(f, "description")).unwrap_or_default(),
        model: fm.and_then(|f| frontmatter_value(f, "model")).unwrap_or_default(),
        body: body.trim_start_matches('\n').to_string(),
    })
}

/// Rewrite an agent file: set `model:` in the frontmatter and/or replace the body.
fn rewrite_agent_file(existing: &str, model: Option<&str>, prompt: Option<&str>) -> String {
    let (fm, body) = split_frontmatter(existing);
    let mut fm_lines: Vec<String> = fm.map(|f| f.lines().map(String::from).collect()).unwrap_or_default();
    if let Some(m) = model {
        match fm_lines.iter().position(|l| l.starts_with("model:")) {
            Some(i) => fm_lines[i] = format!("model: {m}"),
            None => fm_lines.push(format!("model: {m}")),
        }
    }
    let new_body = match prompt {
        Some(p) => format!("{}\n", p.trim_end()),
        None => body.to_string(),
    };
    if fm.is_none() && model.is_none() {
        return new_body;
    }
    format!("---\n{}\n---\n{}", fm_lines.join("\n"), new_body)
}

fn atomic_write(path: &Path, text: &str) -> AppResult<()> {
    let tmp = path.with_extension(format!("tmp-{}", std::process::id()));
    std::fs::write(&tmp, text)?;
    std::fs::rename(&tmp, path).inspect_err(|_| {
        let _ = std::fs::remove_file(&tmp);
    })?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Reading squads
// ---------------------------------------------------------------------------

fn str_of(v: Option<&serde_yaml::Value>) -> String {
    v.and_then(|v| v.as_str()).unwrap_or_default().to_string()
}

fn parse_squad(dirs: &Dirs, text: &str, file_stem: &str) -> AppResult<SquadInfo> {
    let doc: serde_yaml::Value = serde_yaml::from_str(text)?;
    let id = str_of(doc.get("id"));
    let id = if id.is_empty() { file_stem.to_string() } else { id };
    check_id("squad", &id)?;
    let roles_map = doc.get("roles").and_then(|r| r.as_mapping()).cloned().unwrap_or_default();
    let mut roles = Vec::new();
    for (k, v) in &roles_map {
        let Some(role_id) = k.as_str().filter(|r| valid_id(r)) else { continue };
        let agent = read_agent_file(dirs, role_id);
        let model_yaml = str_of(v.get("model"));
        let hires = v
            .get("hires")
            .and_then(|h| h.as_sequence())
            .map(|s| s.iter().filter_map(|x| x.as_str().map(String::from)).collect())
            .unwrap_or_default();
        roles.push(RoleInfo {
            id: role_id.to_string(),
            title: str_of(v.get("title")),
            model: if model_yaml.is_empty() { agent.as_ref().map(|a| a.model.clone()).unwrap_or_default() } else { model_yaml },
            hires,
            description: agent.as_ref().map(|a| a.description.clone()).unwrap_or_default(),
            prompt: agent.as_ref().map(|a| a.body.clone()).unwrap_or_default(),
            has_agent_file: agent.is_some(),
        });
    }
    let name = str_of(doc.get("name"));
    Ok(SquadInfo {
        name: if name.is_empty() { id.clone() } else { name },
        director: str_of(doc.get("director")),
        cap: doc.get("cap").and_then(|c| c.as_u64()).unwrap_or(4) as u32,
        cwd: str_of(doc.get("cwd")),
        jobs: recent_jobs(&dirs.desk, &id),
        id,
        roles,
    })
}

fn mtime_ms(path: &Path) -> i64 {
    std::fs::metadata(path)
        .and_then(|m| m.modified())
        .ok()
        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|d| d.as_millis() as i64)
        .unwrap_or(0)
}

fn recent_jobs(desk: &Path, squad: &str) -> Vec<JobInfo> {
    let jobs_dir = desk.join(squad).join("jobs");
    let Ok(rd) = std::fs::read_dir(&jobs_dir) else { return Vec::new() };
    let mut ids: Vec<String> = rd
        .filter_map(|e| e.ok())
        .filter(|e| e.path().is_dir())
        .filter_map(|e| e.file_name().into_string().ok())
        .collect();
    // Job ids start with YYYY-MM-DD, so a reverse sort is newest first.
    ids.sort_by(|a, b| b.cmp(a));
    ids.truncate(RECENT_JOBS);
    ids.into_iter()
        .map(|id| {
            let dir = jobs_dir.join(&id);
            let status_path = dir.join("status.json");
            let status: Option<serde_json::Value> =
                std::fs::read_to_string(&status_path).ok().and_then(|t| serde_json::from_str(&t).ok());
            let state = status
                .as_ref()
                .and_then(|s| s.get("state"))
                .and_then(|s| s.as_str())
                .unwrap_or("unknown")
                .to_string();
            let last_log = status
                .as_ref()
                .and_then(|s| s.get("log"))
                .and_then(|l| l.as_array())
                .and_then(|l| l.last())
                .and_then(|e| e.get("text"))
                .and_then(|t| t.as_str())
                .map(String::from);
            JobInfo {
                path: dir.to_string_lossy().into_owned(),
                updated_ms: mtime_ms(&status_path),
                id,
                state,
                last_log,
            }
        })
        .collect()
}

pub fn list_squads(dirs: &Dirs) -> Vec<SquadInfo> {
    let Ok(rd) = std::fs::read_dir(&dirs.config) else { return Vec::new() };
    let mut files: Vec<PathBuf> = rd
        .filter_map(|e| e.ok())
        .map(|e| e.path())
        .filter(|p| p.extension().is_some_and(|x| x == "yaml" || x == "yml"))
        .collect();
    files.sort();
    let mut out = Vec::new();
    for f in files {
        let stem = f.file_stem().and_then(|s| s.to_str()).unwrap_or_default().to_string();
        if !valid_id(&stem) {
            continue;
        }
        match std::fs::read_to_string(&f).map_err(AppError::from).and_then(|t| parse_squad(dirs, &t, &stem)) {
            Ok(s) => out.push(s),
            Err(e) => eprintln!("squads: skipping {}: {e}", f.display()),
        }
    }
    out
}

// ---------------------------------------------------------------------------
// Saving a role
// ---------------------------------------------------------------------------

fn plain_scalar_ok(s: &str) -> bool {
    let lower = s.to_ascii_lowercase();
    !s.is_empty()
        && s.chars().next().is_some_and(|c| c.is_ascii_alphanumeric())
        && s.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, ' ' | '_' | '.' | '-'))
        && !s.ends_with(' ')
        && s.parse::<f64>().is_err()
        && !matches!(lower.as_str(), "yes" | "no" | "true" | "false" | "null" | "on" | "off" | "y" | "n")
}

fn flow_scalar(s: &str) -> String {
    if plain_scalar_ok(s) {
        s.to_string()
    } else {
        // A JSON string is a valid YAML double-quoted scalar.
        serde_json::to_string(s).unwrap_or_else(|_| "\"\"".into())
    }
}

fn flow_value(v: &serde_yaml::Value) -> String {
    match v {
        serde_yaml::Value::String(s) => flow_scalar(s),
        serde_yaml::Value::Sequence(items) => {
            format!("[{}]", items.iter().map(flow_value).collect::<Vec<_>>().join(", "))
        }
        serde_yaml::Value::Bool(b) => b.to_string(),
        serde_yaml::Value::Number(n) => n.to_string(),
        serde_yaml::Value::Null => "null".into(),
        other => serde_json::to_string(&serde_yaml::to_string(other).unwrap_or_default()).unwrap_or_default(),
    }
}

/// Apply `fields` to the squad yaml. A role written as a one-line flow mapping
/// (`role: {title: X, model: Y}`) is edited in place so comments and alignment survive;
/// anything else falls back to a serde_yaml round trip.
fn edit_role_yaml(text: &str, role: &str, fields: &RoleFields) -> AppResult<String> {
    let mut in_roles = false;
    let mut lines: Vec<String> = text.lines().map(String::from).collect();
    let key = format!("{role}:");
    for line in lines.iter_mut() {
        if !line.starts_with(' ') && !line.starts_with('\t') && !line.trim().is_empty() {
            in_roles = line.trim_end().starts_with("roles:");
            continue;
        }
        let t = line.trim_start();
        if !in_roles || !t.starts_with(&key) {
            continue;
        }
        let after_key = &t[key.len()..];
        let rest = after_key.trim_start();
        if !rest.starts_with('{') {
            break; // block style: use the round trip below
        }
        let Some(close) = rest.find('}') else { break };
        let inner = &rest[..=close];
        let tail = &rest[close + 1..];
        let Ok(mut map) = serde_yaml::from_str::<serde_yaml::Mapping>(inner) else { break };
        apply_fields(&mut map, fields);
        let prefix_len = line.len() - rest.len();
        let new_inner = format!(
            "{{{}}}",
            map.iter()
                .map(|(k, v)| format!("{}: {}", k.as_str().unwrap_or_default(), flow_value(v)))
                .collect::<Vec<_>>()
                .join(", ")
        );
        *line = format!("{}{}{}", &line[..prefix_len], new_inner, tail);
        let mut out = lines.join("\n");
        if text.ends_with('\n') {
            out.push('\n');
        }
        return Ok(out);
    }
    // Fallback: structured round trip.
    let mut doc: serde_yaml::Value = serde_yaml::from_str(text)?;
    let role_map = doc
        .get_mut("roles")
        .and_then(|r| r.get_mut(role))
        .and_then(|r| r.as_mapping_mut())
        .ok_or_else(|| AppError::NotFound(format!("role {role}")))?;
    apply_fields(role_map, fields);
    Ok(serde_yaml::to_string(&doc)?)
}

fn apply_fields(map: &mut serde_yaml::Mapping, fields: &RoleFields) {
    use serde_yaml::Value;
    if let Some(t) = &fields.title {
        map.insert(Value::String("title".into()), Value::String(t.clone()));
    }
    if let Some(m) = &fields.model {
        map.insert(Value::String("model".into()), Value::String(m.clone()));
    }
    if let Some(h) = &fields.hires {
        if h.is_empty() {
            map.remove("hires");
        } else {
            map.insert(Value::String("hires".into()), Value::Sequence(h.iter().cloned().map(Value::String).collect()));
        }
    }
}

pub fn save_role(dirs: &Dirs, squad: &str, role: &str, fields: &RoleFields) -> AppResult<()> {
    check_id("squad", squad)?;
    check_id("role", role)?;
    if let Some(m) = &fields.model {
        if !MODELS.contains(&m.as_str()) {
            return Err(AppError::Validation(format!("unknown model: {m}")));
        }
    }
    if let Some(t) = &fields.title {
        if t.trim().is_empty() || t.chars().count() > MAX_TITLE_CHARS || t.contains('\n') || t.contains('\r') {
            return Err(AppError::Validation("title must be one short line".into()));
        }
    }
    if let Some(p) = &fields.prompt {
        if p.len() > MAX_PROMPT_BYTES {
            return Err(AppError::Validation("prompt is too long".into()));
        }
    }
    let yaml_path = dirs.config.join(format!("{squad}.yaml"));
    if !is_inside(&dirs.config, &yaml_path) {
        return Err(AppError::NotFound(format!("squad {squad}")));
    }
    let text = std::fs::read_to_string(&yaml_path)?;
    let doc: serde_yaml::Value = serde_yaml::from_str(&text)?;
    let roles = doc
        .get("roles")
        .and_then(|r| r.as_mapping())
        .ok_or_else(|| AppError::NotFound(format!("roles in squad {squad}")))?;
    if !roles.contains_key(role) {
        return Err(AppError::NotFound(format!("role {role} in squad {squad}")));
    }
    if let Some(hires) = &fields.hires {
        for h in hires {
            check_id("role", h)?;
            if !roles.contains_key(h.as_str()) {
                return Err(AppError::Validation(format!("{h} is not a role in {squad}")));
            }
        }
    }

    let yaml_changed = fields.title.is_some() || fields.model.is_some() || fields.hires.is_some();
    if yaml_changed {
        atomic_write(&yaml_path, &edit_role_yaml(&text, role, fields)?)?;
    }

    if fields.model.is_some() || fields.prompt.is_some() {
        std::fs::create_dir_all(&dirs.agents)?;
        let agent_path = dirs.agents.join(format!("{role}.md"));
        if agent_path.exists() && !is_inside(&dirs.agents, &agent_path) {
            return Err(AppError::Path(format!("agent file for {role} resolves outside the agents folder")));
        }
        let existing = std::fs::read_to_string(&agent_path).unwrap_or_else(|_| {
            let title = fields.title.clone().unwrap_or_else(|| role.to_string());
            format!("---\nname: {role}\ndescription: {}\n---\n", flow_scalar(&title))
        });
        atomic_write(
            &agent_path,
            &rewrite_agent_file(&existing, fields.model.as_deref(), fields.prompt.as_deref()),
        )?;
    }
    Ok(())
}

// ---------------------------------------------------------------------------
// Opening a job folder
// ---------------------------------------------------------------------------

/// The job folder to open: must exist and be `<desk>/<squad>/jobs/<job>` after resolving symlinks.
pub fn validate_job_path(desk: &Path, path: &str) -> AppResult<PathBuf> {
    let root = desk.canonicalize().map_err(|_| AppError::NotFound("squads desk".into()))?;
    let real = Path::new(path)
        .canonicalize()
        .map_err(|_| AppError::NotFound(format!("job folder: {path}")))?;
    let rel = real
        .strip_prefix(&root)
        .map_err(|_| AppError::Path("that folder is not under the squads desk".into()))?;
    let parts: Vec<_> = rel.components().collect();
    let shaped = parts.len() == 3 && parts[1].as_os_str() == "jobs";
    if !shaped || !real.is_dir() {
        return Err(AppError::Path("that is not a job folder".into()));
    }
    Ok(real)
}

// ---------------------------------------------------------------------------
// Tauri surface
// ---------------------------------------------------------------------------

fn dirs() -> Dirs {
    Dirs::for_home(&super::fleet::home_dir())
}

#[tauri::command]
pub fn squads_list() -> Vec<SquadInfo> {
    list_squads(&dirs())
}

#[tauri::command]
pub fn squad_role_save(squad: String, role: String, fields: RoleFields) -> AppResult<()> {
    save_role(&dirs(), &squad, &role, &fields)
}

#[tauri::command]
pub fn squad_open_job(path: String) -> AppResult<()> {
    let real = validate_job_path(&dirs().desk, &path)?;
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
    use std::fs;

    fn temp_home() -> (PathBuf, Dirs) {
        let home = std::env::temp_dir().join(format!("synthia-squads-{}", uuid::Uuid::new_v4()));
        let dirs = Dirs::for_home(&home);
        fs::create_dir_all(&dirs.config).unwrap();
        fs::create_dir_all(&dirs.agents).unwrap();
        fs::create_dir_all(&dirs.desk).unwrap();
        (home, dirs)
    }

    const YAML: &str = "# growth squad\nid: growth\nname: Growth\ndirector: growth-director\ncap: 4\ncwd: ~/dev/eventflo\nroles:\n  growth-director:    {title: Marketing Director, model: claude-opus-5-5, hires: [growth-writer, growth-seo]}  # boss\n  growth-writer:      {title: Writer, model: claude-sonnet-5-5}\n  growth-seo:         {title: SEO Strategist, model: claude-sonnet-5-5}\n";

    const AGENT: &str = "---\nname: growth-writer\ndescription: Writes: posts and pages\nmodel: claude-sonnet-5-5\ntools: Read, Write\n---\nYou write the posts.\n\nBe brief.\n";

    fn fixture() -> (PathBuf, Dirs) {
        let (home, dirs) = temp_home();
        fs::write(dirs.config.join("growth.yaml"), YAML).unwrap();
        fs::write(dirs.agents.join("growth-writer.md"), AGENT).unwrap();
        let job = dirs.desk.join("growth/jobs/2026-10-13-week-of-posts");
        fs::create_dir_all(&job).unwrap();
        fs::write(
            job.join("status.json"),
            r#"{"state":"working","log":[{"at":"t","who":"director","text":"briefed"},{"at":"t2","who":"growth-writer","text":"drafting"}]}"#,
        )
        .unwrap();
        fs::create_dir_all(dirs.desk.join("growth/jobs/2026-10-01-old")).unwrap();
        (home, dirs)
    }

    #[test]
    fn id_validation() {
        for ok in ["a", "growth-writer", "a_b-9", &"a".repeat(32)] {
            assert!(valid_id(ok), "{ok}");
        }
        for bad in ["", "A", "1a", "-a", "a b", "a/b", "../x", "a.b", &"a".repeat(33), "é"] {
            assert!(!valid_id(bad), "{bad}");
        }
    }

    #[test]
    fn parses_squad_roles_and_jobs() {
        let (home, dirs) = fixture();
        let squads = list_squads(&dirs);
        assert_eq!(squads.len(), 1);
        let s = &squads[0];
        assert_eq!((s.id.as_str(), s.name.as_str(), s.director.as_str(), s.cap), ("growth", "Growth", "growth-director", 4));
        assert_eq!(s.roles.len(), 3);
        assert_eq!(s.roles[0].hires, ["growth-writer", "growth-seo"]);
        assert_eq!(s.roles[0].model, "claude-opus-5-5");
        let w = &s.roles[1];
        assert_eq!(w.title, "Writer");
        assert_eq!(w.description, "Writes: posts and pages");
        assert!(w.has_agent_file);
        assert!(w.prompt.starts_with("You write the posts."));
        assert!(!s.roles[0].has_agent_file);
        assert_eq!(s.jobs.len(), 2);
        assert_eq!(s.jobs[0].id, "2026-10-13-week-of-posts");
        assert_eq!(s.jobs[0].state, "working");
        assert_eq!(s.jobs[0].last_log.as_deref(), Some("drafting"));
        assert_eq!(s.jobs[1].state, "unknown");
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn no_squads_is_empty_and_corrupt_yaml_is_skipped() {
        let (home, dirs) = temp_home();
        assert!(list_squads(&dirs).is_empty());
        fs::write(dirs.config.join("bad.yaml"), "roles: [unclosed").unwrap();
        assert!(list_squads(&dirs).is_empty());
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn role_save_round_trip_keeps_comments_and_updates_agent_file() {
        let (home, dirs) = fixture();
        let fields = RoleFields {
            title: Some("Senior Writer: long form".into()),
            model: Some("claude-haiku-5-5".into()),
            hires: None,
            prompt: Some("New prompt.\n\nSecond paragraph.".into()),
        };
        save_role(&dirs, "growth", "growth-writer", &fields).unwrap();
        let yaml = fs::read_to_string(dirs.config.join("growth.yaml")).unwrap();
        assert!(yaml.starts_with("# growth squad\n"));
        assert!(yaml.contains("  growth-director:    {title: Marketing Director"));
        assert!(yaml.contains("# boss"));
        assert!(yaml.contains("growth-writer:      {title: \"Senior Writer: long form\", model: claude-haiku-5-5}"));
        let agent = fs::read_to_string(dirs.agents.join("growth-writer.md")).unwrap();
        assert!(agent.contains("model: claude-haiku-5-5"));
        assert!(agent.contains("tools: Read, Write"));
        assert!(agent.ends_with("---\nNew prompt.\n\nSecond paragraph.\n"));
        let s = &list_squads(&dirs)[0];
        let w = &s.roles[1];
        assert_eq!((w.title.as_str(), w.model.as_str()), ("Senior Writer: long form", "claude-haiku-5-5"));
        assert_eq!(w.prompt, "New prompt.\n\nSecond paragraph.\n");

        // Hires on the director, and clearing them.
        let hires = RoleFields { hires: Some(vec!["growth-seo".into()]), ..Default::default() };
        save_role(&dirs, "growth", "growth-director", &hires).unwrap();
        assert_eq!(list_squads(&dirs)[0].roles[0].hires, ["growth-seo"]);
        let none = RoleFields { hires: Some(vec![]), ..Default::default() };
        save_role(&dirs, "growth", "growth-director", &none).unwrap();
        assert!(list_squads(&dirs)[0].roles[0].hires.is_empty());
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn block_style_role_falls_back_to_round_trip() {
        let (home, dirs) = temp_home();
        fs::write(
            dirs.config.join("ops.yaml"),
            "id: ops\nname: Ops\ndirector: ops-lead\nroles:\n  ops-lead:\n    title: Lead\n    model: claude-opus-5-5\n",
        )
        .unwrap();
        let f = RoleFields { title: Some("Chief".into()), ..Default::default() };
        save_role(&dirs, "ops", "ops-lead", &f).unwrap();
        assert_eq!(list_squads(&dirs)[0].roles[0].title, "Chief");
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn role_save_creates_missing_agent_file() {
        let (home, dirs) = fixture();
        let f = RoleFields { prompt: Some("Lead the team.".into()), ..Default::default() };
        save_role(&dirs, "growth", "growth-seo", &f).unwrap();
        let agent = fs::read_to_string(dirs.agents.join("growth-seo.md")).unwrap();
        assert!(agent.starts_with("---\nname: growth-seo\n"));
        assert!(agent.ends_with("---\nLead the team.\n"));
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn role_save_rejects_bad_input() {
        let (home, dirs) = fixture();
        let ok = RoleFields { title: Some("X".into()), ..Default::default() };
        assert!(save_role(&dirs, "../growth", "growth-writer", &ok).is_err());
        assert!(save_role(&dirs, "growth", "../../etc/passwd", &ok).is_err());
        assert!(save_role(&dirs, "growth", "Growth-Writer", &ok).is_err());
        assert!(save_role(&dirs, "growth", "nobody", &ok).is_err());
        assert!(save_role(&dirs, "nosquad", "growth-writer", &ok).is_err());
        let bad_model = RoleFields { model: Some("gpt-9".into()), ..Default::default() };
        assert!(save_role(&dirs, "growth", "growth-writer", &bad_model).is_err());
        let bad_hire = RoleFields { hires: Some(vec!["stranger".into()]), ..Default::default() };
        assert!(save_role(&dirs, "growth", "growth-director", &bad_hire).is_err());
        let bad_title = RoleFields { title: Some("a\nb".into()), ..Default::default() };
        assert!(save_role(&dirs, "growth", "growth-writer", &bad_title).is_err());
        // Nothing was changed by the rejected saves.
        assert_eq!(fs::read_to_string(dirs.config.join("growth.yaml")).unwrap(), YAML);
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn symlinked_agent_file_outside_agents_dir_is_refused() {
        let (home, dirs) = fixture();
        let outside = home.join("outside.md");
        fs::write(&outside, "secret").unwrap();
        std::os::unix::fs::symlink(&outside, dirs.agents.join("growth-seo.md")).unwrap();
        let f = RoleFields { prompt: Some("x".into()), ..Default::default() };
        assert!(save_role(&dirs, "growth", "growth-seo", &f).is_err());
        assert_eq!(fs::read_to_string(&outside).unwrap(), "secret");
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn open_job_path_must_be_a_job_under_the_desk() {
        let (home, dirs) = fixture();
        let job = dirs.desk.join("growth/jobs/2026-10-13-week-of-posts");
        assert!(validate_job_path(&dirs.desk, job.to_str().unwrap()).is_ok());
        assert!(validate_job_path(&dirs.desk, dirs.desk.to_str().unwrap()).is_err());
        assert!(validate_job_path(&dirs.desk, dirs.desk.join("growth").to_str().unwrap()).is_err());
        assert!(validate_job_path(&dirs.desk, job.join("status.json").to_str().unwrap()).is_err());
        assert!(validate_job_path(&dirs.desk, home.to_str().unwrap()).is_err());
        let sneaky = format!("{}/growth/jobs/../../../..", dirs.desk.display());
        assert!(validate_job_path(&dirs.desk, &sneaky).is_err());
        assert!(validate_job_path(&dirs.desk, "/etc").is_err());
        fs::remove_dir_all(home).ok();
    }

    #[test]
    fn registry_parse_skips_ended_and_survives_garbage() {
        let (home, dirs) = temp_home();
        assert!(read_registry(&dirs.desk).is_empty());
        fs::write(dirs.desk.join("registry.json"), "{not json").unwrap();
        assert!(read_registry(&dirs.desk).is_empty());
        fs::write(
            dirs.desk.join("registry.json"),
            r#"{"version":1,"members":{
              "w1:p1":{"agent_name":"growth-director","squad":"growth","job":"j","role":"growth-director","title":"Director","parent":null,"ended_at":null},
              "w1:p2":{"squad":"growth","job":"j","role":"growth-writer","title":"Writer","parent":"w1:p1","ended_at":"2026-10-13T10:00:00+11:00"}}}"#,
        )
        .unwrap();
        let reg = read_registry(&dirs.desk);
        assert_eq!(reg.len(), 1);
        assert_eq!(reg["w1:p1"].role, "growth-director");
        fs::remove_dir_all(home).ok();
    }
}
