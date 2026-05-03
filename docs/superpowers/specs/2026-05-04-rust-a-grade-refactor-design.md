# Rust A-Grade Refactor — Design

**Date:** 2026-05-04
**Branch:** `development`
**Scope:** `gui/src-tauri/` (Tauri Rust backend)
**Goal:** Lift code quality from C/C+ to A. Pure refactor — zero observable behaviour change for React frontend.

## Context

`gui/src-tauri/src/lib.rs` is 4028 lines containing 79 `#[tauri::command]` handlers across at least 8 unrelated domains. Sibling modules `security.rs` (608 lines) and `egress.rs` (212 lines) demonstrate the right shape — focused, well-documented, sensibly bounded. Author is new to Rust; code compiles cleanly with zero `unsafe` and almost no `unwrap`, but suffers from monolithic file structure, hand-rolled YAML parsing, `Result<T, String>` everywhere, a deliberate `Box::leak`, regex-in-loop hotspots, path-traversal checks without canonicalization, and `tokio = "full"` despite no async code.

## Non-goals

- Frontend changes. React `invoke()` callsites stay untouched.
- Wire-format changes. Errors continue to serialize as plain strings.
- Behaviour changes to any IPC command.
- New features.

## Architecture

### Module split

```
gui/src-tauri/src/
├── main.rs              (unchanged, 6 lines)
├── lib.rs               (~150 lines: run(), setup, invoke_handler!)
├── error.rs             (NEW: AppError enum + manual Serialize)
├── state.rs             (NEW: AppState struct, replaces static Mutexes)
├── config.rs            (NEW: serde_yaml structs for config files)
├── paths.rs             (NEW: safe_join + validate_filename)
├── security.rs          (unchanged)
├── egress.rs            (unchanged)
└── commands/
    ├── mod.rs           (re-exports)
    ├── worktrees.rs
    ├── notes.rs
    ├── memory.rs        (Box::leak fix)
    ├── agents.rs        (skills/commands/agents)
    ├── github.rs
    ├── clipboard.rs
    ├── inbox.rs
    ├── claude_config.rs
    ├── usage.rs         (async migration)
    ├── history.rs
    ├── hotkeys.rs       (notify watcher)
    └── neuralguard.rs
```

### Error model

```rust
// error.rs
#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("io: {0}")] Io(String),
    #[error("yaml: {0}")] Yaml(String),
    #[error("json: {0}")] Json(String),
    #[error("path: {0}")] Path(String),
    #[error("validation: {0}")] Validation(String),
    #[error("not found: {0}")] NotFound(String),
    #[error("process: {0}")] Process(String),
    #[error("http: {0}")] Http(String),
    #[error("other: {0}")] Other(String),
}

// Manual Serialize emits message string only — preserves React wire format
impl serde::Serialize for AppError {
    fn serialize<S: serde::Serializer>(&self, s: S) -> Result<S::Ok, S::Error> {
        s.serialize_str(&self.to_string())
    }
}

impl From<std::io::Error> for AppError { /* ... */ }
impl From<serde_yaml::Error> for AppError { /* ... */ }
impl From<serde_json::Error> for AppError { /* ... */ }
impl From<reqwest::Error> for AppError { /* ... */ }

pub type AppResult<T> = Result<T, AppError>;
```

All `#[tauri::command]` handlers return `AppResult<T>`. React still receives a string via the rejected `invoke()` promise — wire format identical.

### State management

```rust
// state.rs
#[derive(Default)]
pub struct AppState {
    pub synthia_process: Mutex<Option<std::process::Child>>,
    pub usage_cache: Mutex<Option<UsageCache>>,
    pub history_cache: Mutex<Option<HistoryCache>>,
}
```

Built into Tauri via `.manage(AppState::default())`. Commands receive `state: tauri::State<'_, AppState>`. Replaces three `Mutex<Option<...>>` static globals at `lib.rs:73, 3120, 3121`.

### Path safety

```rust
// paths.rs
pub fn safe_join(base: &Path, user_input: &str) -> AppResult<PathBuf> {
    validate_filename(user_input)?;
    let candidate = base.join(user_input);
    let canonical = candidate.canonicalize().map_err(|e| AppError::Path(e.to_string()))?;
    let base_canonical = base.canonicalize().map_err(|e| AppError::Path(e.to_string()))?;
    if !canonical.starts_with(&base_canonical) {
        return Err(AppError::Validation(format!("path escapes base: {user_input}")));
    }
    Ok(canonical)
}

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
```

Existing `validate_skill_name` becomes a thin wrapper. All filesystem operations in `notes.rs`, `agents.rs`, `memory.rs` route filenames through `validate_filename` and joined paths through `safe_join`.

### YAML structs

`config.rs` defines `Deserialize`/`Serialize` structs replacing 6 hand-rolled line-by-line parsers:

- `WorktreesConfig` (replaces `get_worktrees`, `get_worktree_repos`, `set_worktree_status`)
- `WordReplacements` (replaces `get_word_replacements`)
- `SynthiaConfig` (replaces `get_synthia_config`)

Roughly 200 lines of brittle parsing → ~30 lines of derived deserialization.

### Async + lazy regex

- `commands/usage.rs::get_usage_stats` becomes `async fn`, uses non-blocking `reqwest::Client`.
- Drop `reqwest`'s `blocking` feature.
- All hot-path regexes hoisted to `static FOO: LazyLock<Regex>` — affects `lib.rs:586`, `:706-730`, `egress.rs:108-109`.
- Drop `tokio = "full"` from `Cargo.toml` (zero async usage outside Tauri).

### `Box::leak` fix

`memory.rs` (currently `lib.rs:1591`):

```rust
// Before
let mut lines: Vec<&str> = content.lines().collect();
lines[line_number] = Box::leak(new_line.into_boxed_str());

// After
let mut lines: Vec<String> = content.lines().map(str::to_owned).collect();
lines[line_number] = new_line;
```

### Hotkeys poll loop

Replace 50ms `loop { sleep }` (currently `lib.rs:3873-3913`) with `notify` crate file watcher. Event-driven, cancellable on app exit.

## Cargo.toml changes

| Action | Crate | Reason |
|--------|-------|--------|
| remove | `tokio = { features = ["full"] }` | Unused, drag on compile time |
| remove | `reqwest` `blocking` feature | Migrating to async |
| add | `thiserror = "2"` | Typed errors |
| add | `serde_yaml = "0.9"` | Replace hand parsers |
| add | `notify = "7"` | Replace poll loop |
| keep | everything else | |

`LazyLock` is in `std` since 1.80, no crate needed.

## Testing

- Migrate existing 4 tests (`parse_etime`, `encode_project_dir`) to their new module homes.
- New unit tests (~20 added):
  - `paths::safe_join` rejects `..`, symlink escape, absolute paths
  - `paths::validate_filename` rejects `/`, `\`, `..`, leading `.`
  - `error::AppError` `Serialize` emits message string (regression guard for wire format)
  - `config::*` round-trip serialize/deserialize for each YAML struct
- Target: ~25 tests total, up from 4.

## Execution plan (12 checkpoints)

Each checkpoint:
1. Implement
2. `cargo build --release`
3. `cargo clippy --all-targets -- -D warnings`
4. `cargo test`
5. Mark drives GUI for 60s — verify nothing broke
6. Proceed to next checkpoint

| # | Checkpoint | Notes |
|---|-----------|-------|
| 1 | `Cargo.toml` cleanup | Drop tokio/blocking, add thiserror/serde_yaml/notify |
| 2 | `error.rs` + `state.rs` + `paths.rs` scaffolding | No callers yet, just infrastructure |
| 3 | `config.rs` YAML structs | Tested in isolation |
| 4 | Split `lib.rs` → `commands/*.rs` (mechanical) | No logic change, just `pub use` re-exports |
| 5 | Migrate handlers to `AppResult` + `AppState` | Replace `Result<T, String>` and statics |
| 6 | Replace 6 hand YAML sites with `serde_yaml` | |
| 7 | `Box::leak` fix + lazy regexes + async `get_usage_stats` | |
| 8 | Path canonicalize + filename validation everywhere | Security fix |
| 9 | `notify` watcher replaces poll loop | |
| 10 | `cargo clippy --fix` + manual sweep | Pedantic warnings |
| 11 | Add unit tests | Target ~25 |
| 12 | Final verification + single squash commit | |

## Verification matrix

| Concern | Verification |
|---------|--------------|
| Frontend wire format unchanged | Manual: GUI smoke test per checkpoint + `error::AppError` Serialize test |
| No behaviour regression | Manual GUI drive (60s) per checkpoint |
| Type safety improved | `Result<T, String>` count: ~80 → 0 in commands |
| Clippy clean | `cargo clippy -- -D warnings` zero output |
| Compile time reduced | Before/after `cargo build --release` cold timing |
| File size sanity | `lib.rs` 4028 → ~150 lines |

## Risks

- **`canonicalize()` requires path to exist.** For new-file write commands, must canonicalize the parent and validate the filename separately. Plan handles this in `safe_join` callers.
- **`notify` cross-platform quirks.** Linux `inotify` is what we run on (Pop!_OS confirmed via memory). Validated against single platform.
- **GUI smoke gate is human-paced.** 12 checkpoints × 60s + my own work = 2-3 hour session minimum. Acceptable.
- **Pure-refactor promise on Serialize.** Manual `Serialize` impl tested explicitly in checkpoint 11.

## Out of scope (deferred)

- Migrating other commands to async beyond `get_usage_stats`.
- Replacing `xdotool`/`wtype` shell-outs with native libraries.
- React side error handling improvements.
- Adding integration tests with a real Tauri window.
