# Rust A-Grade Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift `gui/src-tauri/` Rust code from C/C+ to A. Pure refactor — zero observable behaviour change for React frontend.

**Architecture:** Split 4028-line `lib.rs` into thin orchestrator + 12 domain modules under `commands/`. Add `error.rs` (typed `AppError` with manual `Serialize` preserving wire format), `state.rs` (Tauri-managed `AppState` replacing static `Mutex` globals), `paths.rs` (canonicalize-checked path joins), `config.rs` (`serde_yaml` structs replacing hand-rolled parsers). Hot-path regexes hoisted to `LazyLock`. `get_usage_stats` migrated to async `reqwest::Client`. 50ms hotkey poll loop replaced with `notify` watcher. `Box::leak` at `lib.rs:1591` removed.

**Tech Stack:** Rust 2021, Tauri 2, `thiserror`, `serde_yaml`, `notify` 7, `std::sync::LazyLock` (1.80+), `reqwest` (rustls, async), `serde`, `serde_json`, `tokio` (Tauri-managed only).

**Spec:** `docs/superpowers/specs/2026-05-04-rust-a-grade-refactor-design.md`

**Branch:** `development` (current). All checkpoint commits use `wip:` prefix and get squashed in CP12 into a single `refactor:` commit.

**Working directory:** `/home/markmiddo/dev/misc/synthia` (repo root). All `cargo` commands run in `gui/src-tauri/`.

---

## Conventions

- Each checkpoint ends with: `cargo build --release`, `cargo clippy --all-targets -- -D warnings`, `cargo test`, then a 60-second manual GUI smoke drive by the user, then a WIP commit.
- WIP commit format: `wip(rust-refactor): CP<N> <short summary>`.
- All `Result<T, String>` returns in `#[tauri::command]` handlers stay externally identical until CP5 swaps the alias to `AppResult<T>`. Manual `Serialize` impl on `AppError` (CP2) ensures the wire format is still a plain string.
- Build commands run from `gui/src-tauri/`. Use `cd gui/src-tauri && cargo <cmd>` or set working dir.

---

## Task 1: CP1 — Cargo.toml cleanup

**Files:**
- Modify: `gui/src-tauri/Cargo.toml`

- [ ] **Step 1: Read current Cargo.toml**

Run: `cat gui/src-tauri/Cargo.toml`
Expected: see existing 27-line file with `tokio = { features = ["full", "net"] }`, `reqwest` with `blocking` feature, no `thiserror`/`serde_yaml`/`notify`.

- [ ] **Step 2: Replace [dependencies] block**

Edit `gui/src-tauri/Cargo.toml`, replace lines 15-26 with:

```toml
[dependencies]
tauri = { version = "2", features = ["tray-icon", "image-png"] }
tauri-plugin-opener = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
serde_yaml = "0.9"
thiserror = "2"
tokio = { version = "1", features = ["rt-multi-thread", "macros", "net"] }
image = "0.24"
regex = "1"
dirs = "5"
chrono = "0.4"
uuid = { version = "1", features = ["v4"] }
reqwest = { version = "0.12", features = ["json", "rustls-tls"], default-features = false }
notify = { version = "7", default-features = false, features = ["macos_kqueue"] }
```

Note: `notify` v7's default `crossbeam-channel` feature is fine on Linux; macos_kqueue feature kept for future cross-platform but on Linux it falls through to `inotify` automatically. If notify v7 fails to resolve, fall back to `notify = "6"`.

- [ ] **Step 3: Build to confirm dep resolution**

Run: `cd gui/src-tauri && cargo build --release 2>&1 | tail -30`
Expected: Build succeeds. If `notify = "7"` fails, downgrade to `"6"` and rebuild.

- [ ] **Step 4: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -20`
Expected: Same warning count as before (we haven't touched code yet — baseline). Document baseline count for CP10 reference.

- [ ] **Step 5: GUI smoke test**

Ask user to: launch GUI, click around for 60s, verify nothing broke.

- [ ] **Step 6: WIP commit**

```bash
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock
git commit -m "wip(rust-refactor): CP1 cargo deps cleanup"
```

---

## Task 2: CP2 — error.rs + state.rs + paths.rs scaffolding

**Files:**
- Create: `gui/src-tauri/src/error.rs`
- Create: `gui/src-tauri/src/state.rs`
- Create: `gui/src-tauri/src/paths.rs`
- Modify: `gui/src-tauri/src/lib.rs` (add `mod` declarations only, no callers yet)

- [ ] **Step 1: Write the failing test for AppError Serialize wire format**

Create `gui/src-tauri/src/error.rs`:

```rust
//! Typed application errors with wire-format-preserving serialization.
//!
//! `AppError` serializes as a plain JSON string (the `Display` output) so that
//! existing React `invoke()` consumers — which receive errors as strings — keep
//! working unchanged. Internally we get typed errors and `?` propagation.

use std::fmt;

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("io: {0}")]
    Io(String),
    #[error("yaml: {0}")]
    Yaml(String),
    #[error("json: {0}")]
    Json(String),
    #[error("path: {0}")]
    Path(String),
    #[error("validation: {0}")]
    Validation(String),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("process: {0}")]
    Process(String),
    #[error("http: {0}")]
    Http(String),
    #[error("other: {0}")]
    Other(String),
}

impl serde::Serialize for AppError {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(&self.to_string())
    }
}

impl From<std::io::Error> for AppError {
    fn from(e: std::io::Error) -> Self {
        AppError::Io(e.to_string())
    }
}

impl From<serde_yaml::Error> for AppError {
    fn from(e: serde_yaml::Error) -> Self {
        AppError::Yaml(e.to_string())
    }
}

impl From<serde_json::Error> for AppError {
    fn from(e: serde_json::Error) -> Self {
        AppError::Json(e.to_string())
    }
}

impl From<reqwest::Error> for AppError {
    fn from(e: reqwest::Error) -> Self {
        AppError::Http(e.to_string())
    }
}

impl From<String> for AppError {
    fn from(s: String) -> Self {
        AppError::Other(s)
    }
}

impl From<&str> for AppError {
    fn from(s: &str) -> Self {
        AppError::Other(s.to_string())
    }
}

pub type AppResult<T> = Result<T, AppError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serializes_as_plain_string() {
        let err = AppError::Validation("bad name".to_string());
        let json = serde_json::to_string(&err).unwrap();
        assert_eq!(json, "\"validation: bad name\"");
    }

    #[test]
    fn io_conversion_preserves_message() {
        let io = std::io::Error::new(std::io::ErrorKind::NotFound, "missing");
        let app: AppError = io.into();
        assert!(matches!(app, AppError::Io(_)));
        assert_eq!(app.to_string(), "io: missing");
    }
}
```

- [ ] **Step 2: Add `mod error;` to lib.rs**

Edit `gui/src-tauri/src/lib.rs` — add at the top of the file, after any existing `use` statements but before the first `fn`:

```rust
mod error;
```

- [ ] **Step 3: Run the test to verify it passes**

Run: `cd gui/src-tauri && cargo test --lib error::tests 2>&1 | tail -10`
Expected: `test result: ok. 2 passed`

- [ ] **Step 4: Write paths.rs with failing tests first**

Create `gui/src-tauri/src/paths.rs`:

```rust
//! Filename and path-traversal safety helpers.

use crate::error::{AppError, AppResult};
use std::path::{Path, PathBuf};

/// Validate a filename has no path separators, parent refs, or hidden-dot prefix.
pub fn validate_filename(name: &str) -> AppResult<()> {
    if name.is_empty()
        || name.contains('/')
        || name.contains('\\')
        || name.contains("..")
        || name.starts_with('.')
    {
        return Err(AppError::Validation(format!("bad filename: {name}")));
    }
    Ok(())
}

/// Join `user_input` onto `base` and verify the canonical result stays under base.
///
/// Both paths must exist on disk for canonicalization to succeed. For new-file
/// writes, validate the filename with `validate_filename` and canonicalize the
/// parent directory separately.
pub fn safe_join(base: &Path, user_input: &str) -> AppResult<PathBuf> {
    validate_filename(user_input)?;
    let candidate = base.join(user_input);
    let canonical = candidate
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize {}: {}", candidate.display(), e)))?;
    let base_canonical = base
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize base {}: {}", base.display(), e)))?;
    if !canonical.starts_with(&base_canonical) {
        return Err(AppError::Validation(format!(
            "path escapes base: {user_input}"
        )));
    }
    Ok(canonical)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_empty_filename() {
        assert!(validate_filename("").is_err());
    }

    #[test]
    fn rejects_slash() {
        assert!(validate_filename("foo/bar").is_err());
    }

    #[test]
    fn rejects_backslash() {
        assert!(validate_filename("foo\\bar").is_err());
    }

    #[test]
    fn rejects_parent_ref() {
        assert!(validate_filename("..").is_err());
        assert!(validate_filename("foo..bar").is_err());
    }

    #[test]
    fn rejects_hidden_dotfile() {
        assert!(validate_filename(".env").is_err());
    }

    #[test]
    fn accepts_normal_filename() {
        assert!(validate_filename("notes.md").is_ok());
        assert!(validate_filename("my-file_2.txt").is_ok());
    }

    #[test]
    fn safe_join_rejects_traversal() {
        let tmp = std::env::temp_dir();
        // canonicalize-based check rejects the bad filename early via validate_filename
        assert!(safe_join(&tmp, "../etc/passwd").is_err());
    }
}
```

- [ ] **Step 5: Add `mod paths;` to lib.rs**

After `mod error;`:

```rust
mod paths;
```

- [ ] **Step 6: Run paths tests**

Run: `cd gui/src-tauri && cargo test --lib paths::tests 2>&1 | tail -10`
Expected: `test result: ok. 7 passed`

- [ ] **Step 7: Write state.rs**

Create `gui/src-tauri/src/state.rs`:

```rust
//! Tauri-managed application state, replacing static `Mutex<Option<T>>` globals.

use std::process::Child;
use std::sync::Mutex;

#[derive(Default)]
pub struct AppState {
    pub synthia_process: Mutex<Option<Child>>,
    /// Cached usage stats payload, keyed by ISO date string.
    pub usage_cache: Mutex<Option<UsageCacheEntry>>,
    /// Cached history payload.
    pub history_cache: Mutex<Option<HistoryCacheEntry>>,
}

#[derive(Clone, Debug)]
pub struct UsageCacheEntry {
    pub fetched_at: chrono::DateTime<chrono::Utc>,
    pub payload: serde_json::Value,
}

#[derive(Clone, Debug)]
pub struct HistoryCacheEntry {
    pub fetched_at: chrono::DateTime<chrono::Utc>,
    pub payload: serde_json::Value,
}
```

- [ ] **Step 8: Add `mod state;` to lib.rs**

```rust
mod state;
```

- [ ] **Step 9: Build + clippy**

Run:
```
cd gui/src-tauri && cargo build --release 2>&1 | tail -10
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -10
cd gui/src-tauri && cargo test --lib 2>&1 | tail -10
```

Expected: build green, no new clippy warnings (existing baseline preserved), all new tests pass.

If clippy complains about `dead_code` for `AppState` fields / `UsageCacheEntry` not yet used, add `#[allow(dead_code)]` to the structs with comment `// wired up in CP5`.

- [ ] **Step 10: GUI smoke test**

User drives GUI 60s.

- [ ] **Step 11: WIP commit**

```bash
git add gui/src-tauri/src/error.rs gui/src-tauri/src/state.rs gui/src-tauri/src/paths.rs gui/src-tauri/src/lib.rs
git commit -m "wip(rust-refactor): CP2 add error/state/paths scaffolding"
```

---

## Task 3: CP3 — config.rs YAML structs

**Files:**
- Create: `gui/src-tauri/src/config.rs`
- Modify: `gui/src-tauri/src/lib.rs` (add `mod config;`)

Survey first: read the current hand-parsed YAML sites to understand shape.

- [ ] **Step 1: Read existing parsers to derive struct shape**

Run:
```
sed -n '733,860p' gui/src-tauri/src/lib.rs   # get_worktrees + set_worktree_status
sed -n '1219,1314p' gui/src-tauri/src/lib.rs # get/save_word_replacements
sed -n '1601,1696p' gui/src-tauri/src/lib.rs # get/save_synthia_config
sed -n '1696,1747p' gui/src-tauri/src/lib.rs # get/save_worktree_repos
```

Note exact field names, optional vs required, nested shapes. The structs below are the design — adjust if the on-disk format diverges.

- [ ] **Step 2: Write config.rs with round-trip tests**

Create `gui/src-tauri/src/config.rs`:

```rust
//! Strongly-typed YAML config structs replacing hand-rolled line parsers.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WorktreesConfig {
    #[serde(default)]
    pub repos: HashMap<String, RepoEntry>,
    #[serde(default)]
    pub worktrees: Vec<WorktreeEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RepoEntry {
    pub path: String,
    #[serde(default)]
    pub label: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorktreeEntry {
    pub repo: String,
    pub branch: String,
    pub path: String,
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub session: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct WordReplacements {
    #[serde(default)]
    pub replacements: HashMap<String, String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SynthiaConfig {
    #[serde(default)]
    pub stt: Option<SttConfig>,
    #[serde(default)]
    pub tts: Option<TtsConfig>,
    #[serde(default)]
    pub assistant: Option<AssistantConfig>,
    #[serde(flatten, default)]
    pub extra: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SttConfig {
    #[serde(default)]
    pub provider: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(flatten, default)]
    pub extra: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct TtsConfig {
    #[serde(default)]
    pub provider: Option<String>,
    #[serde(default)]
    pub voice: Option<String>,
    #[serde(default)]
    pub speed: Option<f32>,
    #[serde(flatten, default)]
    pub extra: HashMap<String, serde_yaml::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AssistantConfig {
    #[serde(default)]
    pub provider: Option<String>,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(flatten, default)]
    pub extra: HashMap<String, serde_yaml::Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worktrees_round_trip() {
        let yaml = r#"
repos:
  synthia:
    path: /home/u/synthia
worktrees:
  - repo: synthia
    branch: main
    path: /tmp/wt
    status: active
"#;
        let parsed: WorktreesConfig = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(parsed.worktrees.len(), 1);
        assert_eq!(parsed.worktrees[0].branch, "main");
        let back = serde_yaml::to_string(&parsed).unwrap();
        let reparse: WorktreesConfig = serde_yaml::from_str(&back).unwrap();
        assert_eq!(reparse.worktrees.len(), 1);
    }

    #[test]
    fn word_replacements_round_trip() {
        let yaml = "replacements:\n  hello: hi\n  world: planet\n";
        let parsed: WordReplacements = serde_yaml::from_str(yaml).unwrap();
        assert_eq!(parsed.replacements.get("hello"), Some(&"hi".to_string()));
    }

    #[test]
    fn synthia_config_preserves_unknown_keys() {
        let yaml = "stt:\n  provider: whisper\nfuture_key: 42\n";
        let parsed: SynthiaConfig = serde_yaml::from_str(yaml).unwrap();
        assert!(parsed.extra.contains_key("future_key"));
    }

    #[test]
    fn missing_optional_fields_default() {
        let parsed: WorktreesConfig = serde_yaml::from_str("{}").unwrap();
        assert!(parsed.repos.is_empty());
        assert!(parsed.worktrees.is_empty());
    }
}
```

- [ ] **Step 3: Add `mod config;` to lib.rs**

Add after `mod state;`:

```rust
mod config;
```

Add `#[allow(dead_code)]` to top of `config.rs` with comment `// wired up in CP6` if clippy warns.

- [ ] **Step 4: Run config tests**

Run: `cd gui/src-tauri && cargo test --lib config::tests 2>&1 | tail -10`
Expected: `test result: ok. 4 passed`

- [ ] **Step 5: Build + clippy + GUI smoke**

Run:
```
cd gui/src-tauri && cargo build --release 2>&1 | tail -5
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -5
```

User drives GUI 60s.

- [ ] **Step 6: WIP commit**

```bash
git add gui/src-tauri/src/config.rs gui/src-tauri/src/lib.rs
git commit -m "wip(rust-refactor): CP3 add config.rs YAML structs"
```

---

## Task 4: CP4 — Mechanical split of lib.rs into commands/*.rs

**Files (all under `gui/src-tauri/src/commands/`):**
- Create: `mod.rs`, `worktrees.rs`, `notes.rs`, `memory.rs`, `agents.rs`, `github.rs`, `clipboard.rs`, `inbox.rs`, `claude_config.rs`, `usage.rs`, `history.rs`, `hotkeys.rs`, `neuralguard.rs`, `lifecycle.rs`, `overlay.rs`, `remote.rs`
- Modify: `gui/src-tauri/src/lib.rs` (drastically shrink)

This is the largest task. There is no clean TDD step for moving 4000 lines mechanically — verification is "still compiles and clippy is silent and GUI works".

### Module assignment table

Map each `#[tauri::command]` and its supporting helpers to a target module.

| Module | Commands | Approx lib.rs lines |
|--------|----------|---------------------|
| `lifecycle.rs` | `get_status`, `start_synthia`, `stop_synthia`, `set_mode`, `get_voice_muted`, `set_voice_muted` | 912-1126 (subset) |
| `overlay.rs` | `show_overlay`, `hide_overlay`, `set_overlay_recording` | 1044-1068 |
| `remote.rs` | `start_remote_mode`, `stop_remote_mode`, `get_remote_status` | 965-1044 |
| `history.rs` | `get_history`, `clear_history`, `resend_to_assistant` | 1068-1095, 3583-3622 |
| `hotkeys.rs` | `get_hotkeys`, `save_hotkeys`, `get_word_replacements`, `save_word_replacements` | 1126-1314 |
| `clipboard.rs` | `get_clipboard_history`, `copy_from_clipboard_history` | 1314-1361 |
| `inbox.rs` | `get_inbox_items`, `open_inbox_item`, `delete_inbox_item`, `clear_inbox` | 1361-1450 |
| `worktrees.rs` | `get_worktrees`, `set_worktree_status`, `resume_session`, `get_worktree_repos`, `save_worktree_repos` | 732-911, 1450-1473, 1695-1746 |
| `memory.rs` | `get_memory_stats`, `get_memory_entries`, `search_memory`, `update_memory_entry`, `delete_memory_entry` | 1473-1641, 1746-1776 |
| `claude_config.rs` | `get_synthia_config`, `save_synthia_config`, `get_knowledge_meta`, `save_knowledge_meta` | 1600-1695, 3285-3334 |
| `agents.rs` | `list_agents`, `save_agent`, `delete_agent`, `list_commands`, `save_command`, `delete_command`, `list_skills`, `save_skill`, `delete_skill`, `list_hooks`, `list_plugins`, `toggle_plugin`, `list_active_agents`, `kill_agent`, `scan_all_sessions` | 1776-2671, 2671-2836, 3060-3180 |
| `neuralguard.rs` | `list_security_events`, `clear_security_events`, `get_egress_enabled`, `set_egress_enabled`, `list_pending_prompts`, `respond_to_prompt`, `neuralguard_status`, `install_neuralguard_hooks`, `uninstall_neuralguard_hooks` | 2836-3060 |
| `usage.rs` | `get_usage_stats` | 3180-3285 |
| `notes.rs` | `get_notes_base_path_cmd`, `list_notes`, `read_note`, `get_note_preview`, `get_note_modified`, `save_note`, `rename_note`, `move_note`, `create_folder`, `delete_note`, `get_pinned_note`, `save_pinned_note` | 3334-3653 |
| `github.rs` | `get_github_config`, `save_github_config`, `get_github_issues` | 3653-3917 |

Helpers (`get_*_file()`, `get_*_dir()`, `parse_etime`, `encode_project_dir`, `load_icon_from_path`, `validate_skill_name`, etc.) move with their primary consumer. Cross-module helpers (e.g. `get_synthia_root`, `get_runtime_dir`) move to `paths.rs` as `pub fn`.

### Steps

- [ ] **Step 1: Create `commands/mod.rs`**

```rust
//! Tauri IPC command handlers grouped by domain.

pub mod agents;
pub mod claude_config;
pub mod clipboard;
pub mod github;
pub mod history;
pub mod hotkeys;
pub mod inbox;
pub mod lifecycle;
pub mod memory;
pub mod neuralguard;
pub mod notes;
pub mod overlay;
pub mod remote;
pub mod usage;
pub mod worktrees;
```

- [ ] **Step 2: Move shared root helpers to paths.rs**

Append to `gui/src-tauri/src/paths.rs`:

```rust
use std::path::PathBuf;

pub fn synthia_root() -> PathBuf {
    if let Ok(p) = std::env::var("SYNTHIA_ROOT") {
        return PathBuf::from(p);
    }
    let exe = std::env::current_exe().ok();
    if let Some(e) = exe.as_ref() {
        if let Some(parent) = e.parent() {
            // Cargo target dir: target/{debug,release}/...
            if parent.ends_with("debug") || parent.ends_with("release") {
                if let Some(target) = parent.parent() {
                    if let Some(crate_root) = target.parent() {
                        if let Some(gui) = crate_root.parent() {
                            if let Some(repo) = gui.parent() {
                                return repo.to_path_buf();
                            }
                        }
                    }
                }
            }
        }
    }
    // Installed binary fallback (per memory: /usr/bin/synthia-gui needs ~/dev/misc/synthia)
    if let Some(home) = dirs::home_dir() {
        let dev = home.join("dev/misc/synthia");
        if dev.exists() {
            return dev;
        }
    }
    PathBuf::from(".")
}

pub fn runtime_dir() -> PathBuf {
    dirs::runtime_dir()
        .or_else(dirs::cache_dir)
        .unwrap_or_else(|| PathBuf::from("/tmp"))
        .join("synthia")
}
```

(Adapt the body to match the current `get_synthia_root` and `get_runtime_dir` implementations exactly. Read `lib.rs:22-54` first.)

Replace `get_synthia_root()` and `get_runtime_dir()` callsites in lib.rs with `paths::synthia_root()` / `paths::runtime_dir()` after the splits in steps 4-18. For now keep originals so the file compiles.

- [ ] **Step 3: Add commands module to lib.rs**

Add to `lib.rs` near top (after `mod paths;`):

```rust
mod commands;
```

This will fail to compile until `commands/mod.rs` and at least one stub submodule exist. Create empty placeholder files in step 4.

- [ ] **Step 4: Create empty placeholder modules**

For each of the 15 modules in the table, create the file with just a doc comment:

```rust
//! <Domain> Tauri commands.
```

Run `cd gui/src-tauri && cargo build --release 2>&1 | tail -5` — expected to pass.

- [ ] **Step 5–18: Move handlers domain-by-domain (one commit per domain)**

For each domain in the table:

  a. Cut the `#[tauri::command]` block and its private helpers from `lib.rs`.
  b. Paste into the target `commands/<domain>.rs`.
  c. Add `use` statements at the top of the new module: pull in `crate::error::{AppError, AppResult}` (kept as `Result<T, String>` until CP5), `crate::paths`, `tauri`, `serde::*`, and any external crates the moved code uses. Mechanical — copy whatever the moved code references.
  d. Mark every moved `fn` and `struct` `pub` (or `pub(crate)`) so `lib.rs::run()` can reference them in `generate_handler!`.
  e. In `lib.rs`, replace bare handler names in `generate_handler![...]` (lines 3917-3997) with module-qualified paths: `commands::lifecycle::get_status`, `commands::worktrees::get_worktrees`, etc. The macro accepts paths.
  f. Build: `cd gui/src-tauri && cargo build --release 2>&1 | tail -10`. Fix imports until green.
  g. Clippy: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -5`. Should match baseline (we may have introduced unused import warnings — fix them).
  h. Skip GUI smoke between sub-domains (we'll do it once at end of CP4); commit:
  `git commit -am "wip(rust-refactor): CP4.<n> move <domain> handlers"`.

Execute in this order to minimize cross-module rewiring:

  1. `lifecycle` (smallest, exercises the pattern)
  2. `overlay`
  3. `remote`
  4. `clipboard`
  5. `inbox`
  6. `history`
  7. `hotkeys`
  8. `claude_config`
  9. `worktrees`
  10. `memory`
  11. `agents` (largest)
  12. `neuralguard`
  13. `usage`
  14. `notes`
  15. `github`

  After each domain, `lib.rs` shrinks. Tests in `lib.rs:4002-...` stay until CP11.

- [ ] **Step 19: Final lib.rs shape check**

Run: `wc -l gui/src-tauri/src/lib.rs gui/src-tauri/src/commands/*.rs`
Expected: `lib.rs` < 250 lines (Tauri builder, mod decls, `run()`, leftover tests). Each command module < 600 lines.

- [ ] **Step 20: Full GUI smoke test**

Run: `cd gui/src-tauri && cargo build --release && cd ../.. && ./gui/src-tauri/target/release/synthia-gui &`
Or rebuild deb per memory note (`gui/src-tauri/target/release/bundle/deb/...`) if user prefers. User drives every panel: history, hotkeys, notes (create/rename/delete), worktrees (status set), memory (view/edit), agents (list/save/delete a skill), inbox, github issues fetch, usage stats, neuralguard status, clipboard.

If anything broke, revert the offending sub-domain commit and retry.

- [ ] **Step 21: Clippy + tests + WIP commit (final CP4)**

```bash
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings
cd gui/src-tauri && cargo test --lib
git add -A
git commit -m "wip(rust-refactor): CP4 lib.rs split into commands/* (final)"
```

---

## Task 5: CP5 — Migrate handlers to AppResult + AppState

**Files:**
- Modify: every `gui/src-tauri/src/commands/*.rs` (handler signatures)
- Modify: `gui/src-tauri/src/lib.rs` (manage AppState, drop static globals)

- [ ] **Step 1: Identify static Mutex globals**

Run: `grep -n "static .*Mutex" gui/src-tauri/src/lib.rs gui/src-tauri/src/commands/*.rs`
Expected: 3 hits (synthia_process at original lib.rs:73, usage cache 3120, history cache 3121 — now relocated).

Document their current locations.

- [ ] **Step 2: Manage AppState in lib.rs**

In `gui/src-tauri/src/lib.rs::run()` (the `.invoke_handler` builder), add before `.invoke_handler(...)`:

```rust
use crate::state::AppState;

// inside the builder chain:
.manage(AppState::default())
```

- [ ] **Step 3: Migrate each command's signature**

For every `#[tauri::command]` that uses one of the static Mutexes:

  - Change signature: add `state: tauri::State<'_, crate::state::AppState>` parameter.
  - Replace `SYNTHIA_PROCESS.lock().unwrap()` with `state.synthia_process.lock().unwrap()`.
  - Same for `USAGE_CACHE`, `HISTORY_CACHE`.

For every `#[tauri::command]` returning `Result<T, String>`:

  - Change return type to `crate::error::AppResult<T>` (or import `AppResult` at the module top).
  - Remove `.map_err(|e| e.to_string())` chains — `?` now flows directly because of `From` impls in `error.rs`.
  - Where errors were previously `Err("literal".to_string())`, change to `Err(AppError::Validation("literal".to_string()))` or the appropriate variant.

Do this per module, one module per commit. Build + clippy after each.

- [ ] **Step 4: Delete now-unused static Mutex declarations**

`grep -n "lazy_static\|static .*: Mutex" gui/src-tauri/src/` → delete each.

- [ ] **Step 5: Verify wire format unchanged**

The test from CP2 already guards this (`error::tests::serializes_as_plain_string`). Re-run:

```
cd gui/src-tauri && cargo test --lib error::tests
```

Expected: pass.

- [ ] **Step 6: Build + clippy + GUI smoke**

```
cd gui/src-tauri && cargo build --release 2>&1 | tail -10
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -10
cd gui/src-tauri && cargo test --lib 2>&1 | tail -10
```

User drives GUI 60s, focus on commands that previously returned errors (try invalid hotkey edit, missing file open, etc.) and verify the error toast/console shows the same string format as before.

- [ ] **Step 7: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP5 AppResult + AppState migration"
```

---

## Task 6: CP6 — serde_yaml replaces hand parsers

**Files:**
- Modify: `gui/src-tauri/src/commands/worktrees.rs` (3 sites: get_worktrees, set_worktree_status, get_worktree_repos, save_worktree_repos)
- Modify: `gui/src-tauri/src/commands/hotkeys.rs` (get_word_replacements, save_word_replacements)
- Modify: `gui/src-tauri/src/commands/claude_config.rs` (get_synthia_config, save_synthia_config)

- [ ] **Step 1: Migrate get_worktrees**

Replace the body of `get_worktrees` with:

```rust
let path = paths::worktrees_config_path();
if !path.exists() {
    return Ok(vec![]);
}
let content = std::fs::read_to_string(&path)?;
let cfg: crate::config::WorktreesConfig = serde_yaml::from_str(&content)?;
// Map cfg.worktrees to whatever shape the existing return type wants.
Ok(cfg.worktrees.into_iter().map(into_existing_shape).collect())
```

Keep the existing return type (whatever shape React expects). Add an `into_existing_shape` conversion helper if needed. Read the original implementation first to confirm the public shape.

- [ ] **Step 2: Migrate set_worktree_status**

Replace hand-rolled string slicing with:

```rust
let path = paths::worktrees_config_path();
let content = std::fs::read_to_string(&path)?;
let mut cfg: crate::config::WorktreesConfig = serde_yaml::from_str(&content)?;
if let Some(wt) = cfg.worktrees.iter_mut().find(|w| w.path == target_path) {
    wt.status = Some(status);
} else {
    return Err(AppError::NotFound(format!("worktree: {target_path}")));
}
let new_content = serde_yaml::to_string(&cfg)?;
std::fs::write(&path, new_content)?;
Ok(())
```

- [ ] **Step 3: Migrate get/save_worktree_repos, get/save_word_replacements, get/save_synthia_config**

Same pattern: `serde_yaml::from_str` → mutate struct → `serde_yaml::to_string` → write.

For `save_synthia_config` specifically: `SynthiaConfig` uses `#[serde(flatten)] extra` to preserve unknown keys, so existing config files don't lose data on rewrite. Verify this with a manual round-trip on the user's actual `~/.config/synthia/config.yaml` — read it, parse, re-serialize, diff. The diff should be cosmetic (key ordering, quoting) not semantic.

- [ ] **Step 4: Build + clippy + tests + GUI smoke**

```
cd gui/src-tauri && cargo build --release && cargo clippy --all-targets -- -D warnings && cargo test --lib
```

User drives GUI: change a hotkey, edit a word replacement, change synthia config (e.g. TTS speed), set a worktree status. Confirm the YAML files on disk after each operation are still well-formed (`yamllint ~/.config/synthia/config.yaml` if installed) and Synthia still loads them.

- [ ] **Step 5: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP6 serde_yaml replaces hand parsers"
```

---

## Task 7: CP7 — Box::leak fix + lazy regex + async usage

**Files:**
- Modify: `gui/src-tauri/src/commands/memory.rs` (Box::leak)
- Modify: `gui/src-tauri/src/commands/agents.rs`, `gui/src-tauri/src/egress.rs` (lazy regex)
- Modify: `gui/src-tauri/src/commands/usage.rs` (async)
- Modify: `gui/src-tauri/src/lib.rs` if usage handler list needs `async fn` annotation in `generate_handler!`

- [ ] **Step 1: Write failing test for memory edit (no leak)**

In `gui/src-tauri/src/commands/memory.rs`, add to its `#[cfg(test)] mod tests`:

```rust
#[test]
fn update_entry_uses_owned_strings() {
    // Sanity: build the same Vec<String> path that the fix uses.
    let content = "line0\nline1\nline2\n";
    let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();
    lines[1] = "replaced".to_string();
    assert_eq!(lines, vec!["line0", "replaced", "line2"]);
}
```

This is a behaviour-of-the-fix test, not the function under test directly (the file IO is hard to unit-test without fixtures). The actual leak removal is verified by running miri or just by reading the diff — the test pins the pattern.

- [ ] **Step 2: Run test (will pass — sanity check on the pattern)**

Run: `cd gui/src-tauri && cargo test --lib commands::memory::tests::update_entry_uses_owned_strings`
Expected: PASS.

- [ ] **Step 3: Fix Box::leak in update_memory_entry**

In `gui/src-tauri/src/commands/memory.rs`, find the block (originally `lib.rs:1591`):

```rust
let mut lines: Vec<&str> = content.lines().collect();
// ...
lines[line_number] = Box::leak(new_line.into_boxed_str());
// ...
let updated = lines.join("\n");
```

Replace with:

```rust
let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();
// ...
lines[line_number] = new_line;
// ...
let updated = lines.join("\n");
```

Adjust any subsequent code that depended on `&str` semantics (e.g. iteration borrows).

- [ ] **Step 4: Hoist regexes to LazyLock**

For each `Regex::new(...)` inside a function body, replace with module-level static. Example for `commands/agents.rs::extract_issue_number` area (originally `lib.rs:706-730`):

```rust
use std::sync::LazyLock;
use regex::Regex;

static ISSUE_NUMBER_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"#(\d+)").expect("ISSUE_NUMBER_RE compiles")
});

static SESSION_RE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"...").expect("SESSION_RE compiles")
});

// At call sites:
ISSUE_NUMBER_RE.captures(input)
```

Apply same pattern to:
  - `egress.rs:108-109` (two regexes)
  - Any other `Regex::new` inside loops or hot paths — find with `grep -n "Regex::new" gui/src-tauri/src/`.

- [ ] **Step 5: Make get_usage_stats async**

In `gui/src-tauri/src/commands/usage.rs`:

```rust
use reqwest::Client;
use std::sync::OnceLock;

static HTTP: OnceLock<Client> = OnceLock::new();

fn http_client() -> &'static Client {
    HTTP.get_or_init(|| {
        Client::builder()
            .timeout(std::time::Duration::from_secs(10))
            .build()
            .expect("reqwest client builds")
    })
}

#[tauri::command]
pub async fn get_usage_stats(
    state: tauri::State<'_, crate::state::AppState>,
) -> AppResult<serde_json::Value> {
    // Existing cache check stays, just no .blocking() calls
    let resp = http_client().get(API_URL).send().await?;
    let payload: serde_json::Value = resp.json().await?;
    // Cache as before
    Ok(payload)
}
```

`tauri::generate_handler!` already handles async commands transparently — no changes needed in `lib.rs`.

- [ ] **Step 6: Build + clippy + tests + GUI smoke**

```
cd gui/src-tauri && cargo build --release && cargo clippy --all-targets -- -D warnings && cargo test --lib
```

User drives GUI: open memory tab, edit an entry, save — verify it persists. Open usage stats panel — verify it loads (now async, should not block UI).

- [ ] **Step 7: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP7 Box::leak fix, lazy regex, async usage"
```

---

## Task 8: CP8 — Path canonicalize + filename validation

**Files:**
- Modify: `gui/src-tauri/src/commands/notes.rs` (8 commands touch paths)
- Modify: `gui/src-tauri/src/commands/agents.rs` (save_skill, save_command, save_agent + delete variants)
- Modify: `gui/src-tauri/src/commands/memory.rs` (anything taking a filename)

- [ ] **Step 1: Audit current filename inputs**

Run:
```
grep -n "filename\|file_name\|path: String\|fn .*(name: " gui/src-tauri/src/commands/*.rs
```

Build a list of every command that takes a user-supplied string and joins it onto a base directory.

- [ ] **Step 2: Wrap notes commands**

For `read_note`, `save_note`, `rename_note`, `move_note`, `create_folder`, `delete_note`, `get_note_preview`, `get_note_modified`, `get_pinned_note`, `save_pinned_note`:

  - For reads/deletes: `let resolved = paths::safe_join(&notes_base, &name)?;` then use `resolved`.
  - For writes that create new files: split into parent dir + filename, validate filename, canonicalize parent, then construct the final path:

    ```rust
    paths::validate_filename(&name)?;
    let parent_canonical = parent_dir.canonicalize()
        .map_err(|e| AppError::Path(e.to_string()))?;
    let target = parent_canonical.join(&name);
    let base_canonical = notes_base.canonicalize()?;
    if !target.starts_with(&base_canonical) {
        return Err(AppError::Validation("path escapes notes base".into()));
    }
    std::fs::write(&target, content)?;
    ```

- [ ] **Step 3: Wrap agents/commands/skills save+delete**

Existing `validate_skill_name` (originally `lib.rs:1953`) becomes a wrapper:

```rust
pub fn validate_skill_name(name: &str) -> AppResult<()> {
    crate::paths::validate_filename(name)?;
    // Plus any skill-specific rules (length, regex etc.)
    if name.len() > 64 {
        return Err(AppError::Validation("skill name too long".into()));
    }
    Ok(())
}
```

Apply `validate_filename` (or `validate_skill_name`) to every command that takes a filename and joins onto `agents_dir`/`commands_dir`/`skills_dir`.

- [ ] **Step 4: Add traversal regression tests**

Add to `gui/src-tauri/src/commands/notes.rs::tests`:

```rust
#[test]
fn safe_join_blocks_traversal_in_notes_base() {
    let base = std::env::temp_dir();
    assert!(crate::paths::safe_join(&base, "../etc/passwd").is_err());
    assert!(crate::paths::safe_join(&base, "..").is_err());
    assert!(crate::paths::safe_join(&base, "/etc/passwd").is_err());
}
```

- [ ] **Step 5: Build + clippy + tests + GUI smoke**

User drives GUI specifically: try to create a note named `../foo` (should fail with validation error), try to save a skill with `/` in name (should fail). Normal operations (legit filenames) must still work.

- [ ] **Step 6: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP8 canonicalize paths + validate filenames"
```

---

## Task 9: CP9 — notify watcher replaces poll loop

**Files:**
- Modify: `gui/src-tauri/src/commands/hotkeys.rs` OR wherever the 50ms poll thread now lives (originally `lib.rs:3873-3913` — likely moved to `lifecycle.rs` or similar in CP4)

- [ ] **Step 1: Locate the poll loop after CP4 split**

Run: `grep -rn "Duration::from_millis(50)" gui/src-tauri/src/`
Note the file and lines.

- [ ] **Step 2: Identify what the loop watches**

Read the loop body. It almost certainly polls a JSON file under `~/.local/share/synthia/...` for changes.

- [ ] **Step 3: Replace with notify watcher**

```rust
use notify::{Event, RecommendedWatcher, RecursiveMode, Watcher};
use std::sync::mpsc;
use std::time::Duration;

fn spawn_state_watcher(
    app: tauri::AppHandle,
    state_file: PathBuf,
) -> AppResult<RecommendedWatcher> {
    let (tx, rx) = mpsc::channel::<notify::Result<Event>>();
    let mut watcher = notify::recommended_watcher(tx)
        .map_err(|e| AppError::Other(format!("watcher: {e}")))?;
    watcher
        .watch(state_file.parent().ok_or_else(|| {
            AppError::Path("state file has no parent".into())
        })?, RecursiveMode::NonRecursive)
        .map_err(|e| AppError::Other(format!("watch: {e}")))?;

    let target = state_file.clone();
    std::thread::spawn(move || {
        for res in rx {
            match res {
                Ok(event) if event.paths.iter().any(|p| p == &target) => {
                    // emit existing event to frontend
                    if let Err(e) = app.emit("synthia-state-changed", ()) {
                        eprintln!("emit failed: {e}");
                    }
                }
                Ok(_) => {}
                Err(e) => eprintln!("watch error: {e}"),
            }
        }
    });

    Ok(watcher)
}
```

Store the returned `RecommendedWatcher` in `AppState` (add a `pub watchers: Mutex<Vec<RecommendedWatcher>>` field) so it isn't dropped — `notify` watchers stop watching when dropped.

Wire it up in `lib.rs::run()::setup`:

```rust
.setup(|app| {
    let state: tauri::State<AppState> = app.state();
    let watcher = commands::lifecycle::spawn_state_watcher(
        app.handle().clone(),
        paths::state_file(),
    )?;
    state.watchers.lock().unwrap().push(watcher);
    Ok(())
})
```

- [ ] **Step 4: Delete the 50ms loop**

Remove the entire `thread::spawn(move || { loop { ... sleep(50ms) } })` block.

- [ ] **Step 5: Build + clippy + tests + GUI smoke**

User drives GUI: trigger something that updates the watched state file from outside the GUI (e.g. start/stop Synthia from CLI), confirm GUI status updates within ~1 second instead of relying on the old 50ms poll.

- [ ] **Step 6: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP9 notify watcher replaces poll loop"
```

---

## Task 10: CP10 — clippy --fix + manual sweep

**Files:**
- Many (auto-fix touches whatever it touches)

- [ ] **Step 1: Capture baseline clippy output**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -W clippy::pedantic 2>&1 | tee /tmp/clippy-before.txt | tail -30`

- [ ] **Step 2: Auto-fix the easy wins**

Run: `cd gui/src-tauri && cargo clippy --all-targets --fix --allow-dirty --allow-staged -- -W clippy::pedantic 2>&1 | tail -20`

This rewrites obvious issues (`needless_clone`, `redundant_field_names`, `pass-by-value-not-consumed`, etc.). Review the diff:

`git diff --stat`

- [ ] **Step 3: Build + tests after auto-fix**

```
cd gui/src-tauri && cargo build --release && cargo test --lib
```

If anything broke, `git checkout -- gui/src-tauri/src/<broken-file>` and either fix manually or accept the auto-fix selectively.

- [ ] **Step 4: Manual sweep of remaining warnings**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -W clippy::pedantic 2>&1 | grep "warning:" | sort | uniq -c | sort -rn | head -20`

Address the top warning categories. For genuinely false-positive ones, add a targeted `#[allow(clippy::xxx)]` with a comment explaining why.

Goal: `cargo clippy --all-targets -- -D warnings` runs clean (no `-W pedantic`).

- [ ] **Step 5: Drop dead code flagged in audit**

Confirmed dead: `load_icon_from_path`, `WorktreesRepoConfig`, `WorktreesConfig` (the old hand-parser version, not the new `config::WorktreesConfig`), `evaluate_injection`, `match_first`. Remove them entirely.

Run: `cd gui/src-tauri && cargo build --release` to confirm nothing depended on them.

- [ ] **Step 6: GUI smoke + WIP commit**

User drives GUI 60s, verify nothing broke.

```bash
git add -A
git commit -m "wip(rust-refactor): CP10 clippy sweep + dead code removal"
```

---

## Task 11: CP11 — Add unit tests

**Files:**
- Modify: every `gui/src-tauri/src/commands/*.rs` (add `#[cfg(test)] mod tests`)
- Migrate: existing tests from `gui/src-tauri/src/lib.rs` (originally lines 4002-4030) into appropriate modules

- [ ] **Step 1: Find current home of `parse_etime` and `encode_project_dir`**

Run: `grep -rn "fn parse_etime\|fn encode_project_dir" gui/src-tauri/src/`

These should now be inside `commands/agents.rs` (claude project sessions) and likely `commands/agents.rs` again. Move their tests into the same module's `#[cfg(test)] mod tests`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn etime_parses_mm_ss() {
        assert_eq!(parse_etime("01:23"), 83);
    }

    #[test]
    fn etime_parses_hh_mm_ss() {
        assert_eq!(parse_etime("1:02:03"), 3723);
    }

    #[test]
    fn etime_parses_days() {
        assert_eq!(parse_etime("2-03:04:05"), 2 * 86400 + 3 * 3600 + 4 * 60 + 5);
    }

    #[test]
    fn encodes_project_dir() {
        assert_eq!(
            encode_project_dir("/home/markmiddo/dev/misc/synthia"),
            "-home-markmiddo-dev-misc-synthia"
        );
    }
}
```

Delete the old `mod tests` block from `lib.rs`.

- [ ] **Step 2: Add config round-trip tests**

Already added in CP3. Verify still passing.

- [ ] **Step 3: Add error wire-format guard tests**

Already added in CP2. Verify.

- [ ] **Step 4: Add path safety tests**

Already added in CP2 + CP8. Verify.

- [ ] **Step 5: Add per-module sanity tests where cheap**

For each command module, add at least one trivial test that exercises a pure helper (parsing, formatting, validation). Examples:

  - `commands/notes.rs`: test `slugify_filename` if such a helper exists
  - `commands/github.rs`: test issue-number regex
  - `commands/hotkeys.rs`: test hotkey-name parser
  - `commands/agents.rs`: test `validate_skill_name` rejection cases

Aim for at least 1 test per command module — won't all be deep, but builds the habit.

- [ ] **Step 6: Run full suite**

Run: `cd gui/src-tauri && cargo test --lib 2>&1 | tail -15`
Expected: ~25 tests passing.

- [ ] **Step 7: WIP commit**

```bash
git add -A
git commit -m "wip(rust-refactor): CP11 unit tests across modules"
```

---

## Task 12: CP12 — Final verification + squash commit

- [ ] **Step 1: Full clean build**

```
cd gui/src-tauri && cargo clean
cd gui/src-tauri && cargo build --release 2>&1 | tail -10
```

Expected: green, no warnings beyond clippy baseline.

- [ ] **Step 2: Clippy strict**

```
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -10
```

Expected: zero output (other than the final compile summary).

- [ ] **Step 3: Full test suite**

```
cd gui/src-tauri && cargo test --lib 2>&1 | tail -15
```

Expected: all ~25 pass.

- [ ] **Step 4: Final manual GUI smoke (extended)**

Build deb if needed, install, restart GUI. User exercises every panel:

  - Status / start / stop
  - Voice mute toggle
  - Mode switch
  - Hotkeys panel: edit + save
  - Word replacements
  - Clipboard history
  - Inbox: open + delete + clear
  - Worktrees: list, set status, resume
  - Memory: list, search, edit, delete
  - Synthia config: edit + save
  - Skills/commands/agents: list, save, delete
  - NeuralGuard: status, toggle egress, list events, respond to prompt
  - Notes: list, read, create, rename, move, delete folder/file, pin
  - Usage stats: load
  - GitHub: issues fetch
  - History: list, clear, resend
  - Active agents: list, kill
  - Plugins: list, toggle

Anything broken → revert to the last good WIP commit, fix, redo CP12.

- [ ] **Step 5: Capture before/after metrics**

```
wc -l gui/src-tauri/src/lib.rs gui/src-tauri/src/commands/*.rs gui/src-tauri/src/error.rs gui/src-tauri/src/state.rs gui/src-tauri/src/paths.rs gui/src-tauri/src/config.rs
```

Document in the squash commit body: `lib.rs 4028 → <N>`, `total handlers covered: 79`, `tests 4 → 25`.

- [ ] **Step 6: Squash all `wip(rust-refactor):` commits into one**

Identify the first WIP commit:

```bash
git log --oneline | grep -n "wip(rust-refactor)" | tail -1
```

Find the commit just before the first WIP (the spec commit `f795cb1` or whatever is current at start of CP1). Then:

```bash
git reset --soft <commit-before-first-wip>
git commit -m "$(cat <<'EOF'
refactor(gui): Rust A-grade pass on src-tauri

Lift gui/src-tauri/ from C/C+ to A. Pure refactor — zero behaviour change
visible to React frontend.

Major changes:
- Split 4028-line lib.rs into 15 commands/* modules + thin orchestrator
- Add error.rs (AppError enum, manual Serialize preserves wire format)
- Add state.rs (Tauri-managed AppState, drops 3 static Mutex globals)
- Add paths.rs (canonicalize-checked safe_join, validate_filename)
- Add config.rs (serde_yaml structs replace 6 hand-rolled YAML parsers)
- Fix Box::leak in update_memory_entry (memory leak per edit)
- Hoist hot-path regexes to LazyLock
- Migrate get_usage_stats to async reqwest::Client
- Replace 50ms hotkey poll loop with notify file watcher
- Path canonicalize + filename validation across notes/agents/memory
- Drop tokio "full" feature (unused), drop reqwest blocking feature
- cargo clippy --all-targets -- -D warnings now passes clean
- Tests: 4 → ~25

Spec: docs/superpowers/specs/2026-05-04-rust-a-grade-refactor-design.md
Plan: docs/superpowers/plans/2026-05-04-rust-a-grade-refactor.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 7: Verify final commit**

```bash
git log --oneline -5
git diff HEAD~1 --stat | tail -10
```

Expected: single `refactor(gui)` commit on top of the spec/plan commits. Stat shows ~4900 lines changed across ~20 files.

- [ ] **Step 8: Done**

Mark all checkpoint tasks completed. Report to user with:
  - Final lib.rs line count
  - Test count delta
  - Clippy warning count delta
  - Compile time delta (release, cold)

---

## Self-review notes

**Spec coverage:**
- Module split → CP4 ✓
- Error model (AppError + manual Serialize) → CP2, CP5 ✓
- AppState replaces statics → CP2, CP5 ✓
- Path safety → CP2, CP8 ✓
- YAML migration → CP3, CP6 ✓
- Async + lazy regex → CP7 ✓
- Box::leak fix → CP7 ✓
- notify watcher → CP9 ✓
- Cargo.toml changes → CP1 ✓
- Tests → CP11 ✓
- Verification matrix → CP12 ✓

**Risks acknowledged in spec → handled in plan:**
- canonicalize requires path existence → CP8 step 2 splits into parent canonicalize + filename validate for new-file writes
- Wire format unchanged → CP2 test, re-run in CP5 step 5

**Type/name consistency:**
- `AppError`/`AppResult` defined CP2, used CP5+
- `AppState` defined CP2, managed CP5, watchers field added CP9
- `WorktreesConfig` defined CP3 (note: distinct from old hand-parser type also called WorktreesConfig — old one removed in CP10 step 5)
- `safe_join`/`validate_filename` defined CP2, called CP8
- `paths::synthia_root`/`runtime_dir` added CP4 step 2

**Open uncertainty:**
- `notify` v7 vs v6 — fallback documented in CP1 step 2.
- Exact existing types returned from `get_worktrees` etc. — CP6 step 1 instructs to read source first and add adapter conversions if needed.
- Where the 50ms poll thread ends up after CP4 — CP9 step 1 locates it via grep.
