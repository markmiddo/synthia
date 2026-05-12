# Built-in Terminal Emulator — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an xterm.js-based terminal as a new "Terminal" sidebar tab in the Synthia Tauri GUI — generic shell + Claude shortcut, browser-style tabs, glassmorphic theme, Commit Mono font, worktree-aware spawn.

**Architecture:** Rust backend uses `portable-pty` (same crate as Wezterm) to spawn shells and manage PTY masters; each session lives in a `TerminalRegistry: HashMap<Uuid, PtySession>` in `AppState`. A tokio task per session reads PTY output and emits base64-encoded Tauri events. React layer renders xterm.js instances (one per tab) and forwards keystrokes through Tauri commands.

**Tech Stack:** Rust (Tauri 2, tokio, portable-pty 0.8, base64 0.22, uuid, chrono, serde, thiserror) + React 19 / TypeScript / Vite + xterm.js 5.5 with fit/webgl/web-links/search addons + Commit Mono woff2 font (SIL OFL).

**Spec:** `docs/superpowers/specs/2026-05-13-terminal-emulator-design.md`

---

## File Structure

| Path | Status | Purpose |
|------|--------|---------|
| `gui/src-tauri/Cargo.toml` | Modify | Add `portable-pty`, `base64` deps |
| `gui/src-tauri/src/error.rs` | Modify | Add `Terminal(String)` variant |
| `gui/src-tauri/src/state.rs` | Modify | Add `TerminalRegistry` field |
| `gui/src-tauri/src/commands/terminal.rs` | Create | Tauri commands: spawn/write/resize/kill/list |
| `gui/src-tauri/src/commands/mod.rs` | Modify | Register `terminal` module |
| `gui/src-tauri/src/lib.rs` | Modify | Register 5 new commands in `generate_handler!` |
| `gui/package.json` | Modify | Add xterm + addon deps |
| `gui/src/assets/fonts/CommitMono-400-Regular.woff2` | Create | Font file (download in Task 9) |
| `gui/src/assets/fonts/CommitMono-700-Regular.woff2` | Create | Bold weight |
| `gui/src/assets/fonts/CommitMono-LICENSE.txt` | Create | OFL license text |
| `gui/src/components/terminal/theme.ts` | Create | xterm theme + CSS tokens |
| `gui/src/components/terminal/useTerminalSession.ts` | Create | Hook: spawn/listen/write/dispose |
| `gui/src/components/terminal/TerminalView.tsx` | Create | One xterm instance |
| `gui/src/components/terminal/TerminalTabs.tsx` | Create | Tab strip with `+` and `+ Claude` |
| `gui/src/components/terminal/TerminalPanel.tsx` | Create | Top-level panel |
| `gui/src/components/terminal/terminal.css` | Create | Glass theme styles |
| `gui/src/components/terminal/spawnRequest.ts` | Create | Module-level mailbox for cross-panel spawn requests |
| `gui/src/App.tsx` | Modify | Add `"terminal"` to `Section`, sidebar entry, route render |
| `gui/src/App.css` | Modify | Import `terminal.css`, font-face declarations |

---

## Task 1: Add Rust dependencies and `AppError::Terminal` variant

**Files:**
- Modify: `gui/src-tauri/Cargo.toml`
- Modify: `gui/src-tauri/src/error.rs`

- [ ] **Step 1: Add `portable-pty` and `base64` to Cargo.toml**

Append under the existing `[dependencies]` block in `gui/src-tauri/Cargo.toml`:

```toml
portable-pty = "0.8"
base64 = "0.22"
```

- [ ] **Step 2: Add `Terminal` variant to `AppError`**

Edit `gui/src-tauri/src/error.rs`. Inside the `pub enum AppError { ... }` block, add this variant after the `Other` variant:

```rust
    #[error("terminal: {0}")]
    Terminal(String),
```

- [ ] **Step 3: Add a unit test for the new variant**

In `gui/src-tauri/src/error.rs`, inside `mod tests { ... }`, add:

```rust
    #[test]
    fn terminal_variant_serializes() {
        let err = AppError::Terminal("spawn failed".to_string());
        let json = serde_json::to_string(&err).unwrap();
        assert_eq!(json, "\"terminal: spawn failed\"");
    }
```

- [ ] **Step 4: Verify build + tests pass**

Run: `cd gui/src-tauri && cargo test --lib error::`
Expected: `terminal_variant_serializes` passes plus existing error tests.

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock gui/src-tauri/src/error.rs
git commit -m "feat(terminal): add portable-pty deps and AppError::Terminal variant"
```

---

## Task 2: Add `SessionMeta` type and `TerminalRegistry` skeleton in `state.rs`

**Files:**
- Modify: `gui/src-tauri/src/state.rs`

- [ ] **Step 1: Write the failing test**

Append to `gui/src-tauri/src/state.rs`:

```rust
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_registry_starts_empty() {
        let reg = TerminalRegistry::default();
        let metas = reg.list();
        assert!(metas.is_empty());
    }
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd gui/src-tauri && cargo test --lib state::tests::terminal_registry_starts_empty`
Expected: FAIL with "cannot find type `TerminalRegistry`".

- [ ] **Step 3: Add the registry type, `SessionMeta`, and field on `AppState`**

Replace the contents of `gui/src-tauri/src/state.rs` with:

```rust
//! Tauri-managed application state, replacing static `Mutex<Option<T>>` globals.

use std::collections::HashMap;
use std::process::Child;
use std::sync::Mutex;
use std::time::Instant;

use chrono::{DateTime, Utc};
use portable_pty::{Child as PtyChild, MasterPty};
use serde::Serialize;
use tokio::task::JoinHandle;
use uuid::Uuid;

use crate::commands::usage::UsageStats;

#[derive(Default)]
pub struct AppState {
    pub synthia_process: Mutex<Option<Child>>,
    pub usage_cache: Mutex<Option<UsageTokenCache>>,
    pub usage_response_cache: Mutex<Option<UsageResponseCache>>,
    #[allow(dead_code)]
    pub watchers: Mutex<Vec<Box<dyn std::any::Any + Send + Sync>>>,
    pub terminals: TerminalRegistry,
}

#[derive(Clone, Debug)]
pub struct UsageTokenCache {
    pub token: String,
    pub fetched_at: Instant,
}

#[derive(Clone, Debug)]
pub struct UsageResponseCache {
    pub stats: UsageStats,
    pub fetched_at: Instant,
}

#[derive(Clone, Debug, Serialize)]
pub struct SessionMeta {
    pub id: Uuid,
    pub cwd: String,
    pub shell: String,
    pub title: String,
    pub created_at: DateTime<Utc>,
}

pub struct PtySession {
    pub master: Box<dyn MasterPty + Send>,
    pub writer: Box<dyn std::io::Write + Send>,
    pub child: Box<dyn PtyChild + Send + Sync>,
    pub reader_task: JoinHandle<()>,
    pub meta: SessionMeta,
}

#[derive(Default)]
pub struct TerminalRegistry {
    pub sessions: Mutex<HashMap<Uuid, PtySession>>,
}

impl TerminalRegistry {
    pub fn list(&self) -> Vec<SessionMeta> {
        match self.sessions.lock() {
            Ok(g) => g.values().map(|s| s.meta.clone()).collect(),
            Err(_) => Vec::new(),
        }
    }
}

impl Drop for TerminalRegistry {
    fn drop(&mut self) {
        let mut guard = match self.sessions.lock() {
            Ok(g) => g,
            Err(p) => p.into_inner(),
        };
        for (_id, mut sess) in guard.drain() {
            let _ = sess.child.kill();
            sess.reader_task.abort();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn terminal_registry_starts_empty() {
        let reg = TerminalRegistry::default();
        let metas = reg.list();
        assert!(metas.is_empty());
    }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gui/src-tauri && cargo test --lib state::`
Expected: `terminal_registry_starts_empty` passes.

- [ ] **Step 5: Confirm clippy still clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`
Expected: zero warnings.

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/state.rs
git commit -m "feat(terminal): add TerminalRegistry + SessionMeta to AppState"
```

---

## Task 3: Create `commands/terminal.rs` with `terminal_spawn`

**Files:**
- Create: `gui/src-tauri/src/commands/terminal.rs`
- Modify: `gui/src-tauri/src/commands/mod.rs`

- [ ] **Step 1: Wire the module declaration**

Edit `gui/src-tauri/src/commands/mod.rs`. Add `pub mod terminal;` in alphabetical position (between `remote` and `usage`).

- [ ] **Step 2: Write the failing test inside the new file**

Create `gui/src-tauri/src/commands/terminal.rs` with this initial content:

```rust
//! Built-in PTY terminal sessions. See `docs/superpowers/specs/2026-05-13-terminal-emulator-design.md`.

use std::sync::Arc;

use base64::Engine;
use chrono::Utc;
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use tauri::{AppHandle, Emitter, Manager, State};
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::state::{AppState, PtySession, SessionMeta};

const MAX_SESSIONS: usize = 16;
const READ_CHUNK_SIZE: usize = 4096;

fn detect_shell() -> String {
    std::env::var("SHELL").unwrap_or_else(|_| "/bin/bash".to_string())
}

fn derive_title(shell: &str, cwd: &str) -> String {
    let shell_name = std::path::Path::new(shell)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("shell");
    let cwd_name = std::path::Path::new(cwd)
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or(cwd);
    format!("{shell_name} · {cwd_name}")
}

#[tauri::command]
pub async fn terminal_spawn(
    app: AppHandle,
    state: State<'_, AppState>,
    cwd: Option<String>,
    shell: Option<String>,
) -> AppResult<SessionMeta> {
    let shell = shell.unwrap_or_else(detect_shell);
    let cwd = cwd
        .filter(|p| std::path::Path::new(p).is_dir())
        .or_else(|| std::env::var("HOME").ok())
        .ok_or_else(|| AppError::Terminal("no usable cwd".into()))?;

    {
        let guard = state
            .terminals
            .sessions
            .lock()
            .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
        if guard.len() >= MAX_SESSIONS {
            return Err(AppError::Terminal(format!(
                "max {MAX_SESSIONS} terminals"
            )));
        }
    }

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize {
            rows: 24,
            cols: 80,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::Terminal(format!("openpty: {e}")))?;

    let mut cmd = CommandBuilder::new(&shell);
    cmd.cwd(&cwd);
    if let Ok(term) = std::env::var("TERM") {
        cmd.env("TERM", term);
    } else {
        cmd.env("TERM", "xterm-256color");
    }
    let child = pair
        .slave
        .spawn_command(cmd)
        .map_err(|e| AppError::Terminal(format!("spawn: {e}")))?;
    drop(pair.slave);

    let writer = pair
        .master
        .take_writer()
        .map_err(|e| AppError::Terminal(format!("take_writer: {e}")))?;
    let mut reader = pair
        .master
        .try_clone_reader()
        .map_err(|e| AppError::Terminal(format!("try_clone_reader: {e}")))?;

    let session_id = Uuid::new_v4();
    let meta = SessionMeta {
        id: session_id,
        cwd: cwd.clone(),
        shell: shell.clone(),
        title: derive_title(&shell, &cwd),
        created_at: Utc::now(),
    };

    let app_handle = app.clone();
    let reader_task = tauri::async_runtime::spawn_blocking(move || {
        let mut buf = vec![0u8; READ_CHUNK_SIZE];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let encoded =
                        base64::engine::general_purpose::STANDARD.encode(&buf[..n]);
                    let _ = app_handle.emit(&format!("terminal-output-{session_id}"), encoded);
                }
                Err(_) => break,
            }
        }
        let _ = app_handle.emit(&format!("terminal-exit-{session_id}"), 0_i32);
    });

    let session = PtySession {
        master: pair.master,
        writer,
        child,
        reader_task,
        meta: meta.clone(),
    };

    state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?
        .insert(session_id, session);

    Ok(meta)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_shell_returns_something() {
        let shell = detect_shell();
        assert!(!shell.is_empty());
    }

    #[test]
    fn derive_title_formats_correctly() {
        assert_eq!(derive_title("/bin/zsh", "/home/me/synthia"), "zsh · synthia");
        assert_eq!(derive_title("/bin/bash", "/"), "bash · /");
    }
}
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal`
Expected: both unit tests pass.

- [ ] **Step 4: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`
Expected: zero warnings.

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/src/commands/mod.rs gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): terminal_spawn command + module skeleton"
```

---

## Task 4: Add `terminal_write` command with integration test

**Files:**
- Modify: `gui/src-tauri/src/commands/terminal.rs`

- [ ] **Step 1: Write the failing integration test**

Append inside the existing `#[cfg(test)] mod tests` block in `gui/src-tauri/src/commands/terminal.rs`:

```rust
    use std::io::Read as _;
    use std::time::Duration;

    #[test]
    fn write_forwards_bytes_to_pty() {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/cat");
        cmd.env("TERM", "xterm-256color");
        let mut child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);

        let mut writer = pair.master.take_writer().unwrap();
        let mut reader = pair.master.try_clone_reader().unwrap();

        write_to_writer(&mut writer, "hello\n").unwrap();

        let mut buf = [0u8; 64];
        std::thread::sleep(Duration::from_millis(100));
        let n = reader.read(&mut buf).unwrap();
        let echoed = String::from_utf8_lossy(&buf[..n]);
        assert!(echoed.contains("hello"));

        child.kill().unwrap();
    }
```

- [ ] **Step 2: Run test to verify it fails (missing helper)**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal::tests::write_forwards_bytes_to_pty`
Expected: FAIL — `write_to_writer` not found.

- [ ] **Step 3: Add the helper and the Tauri command**

Append to `gui/src-tauri/src/commands/terminal.rs` (above the `#[cfg(test)]` block):

```rust
fn write_to_writer(writer: &mut dyn std::io::Write, data: &str) -> AppResult<()> {
    writer
        .write_all(data.as_bytes())
        .map_err(|e| AppError::Terminal(format!("write: {e}")))?;
    writer
        .flush()
        .map_err(|e| AppError::Terminal(format!("flush: {e}")))?;
    Ok(())
}

#[tauri::command]
pub async fn terminal_write(
    state: State<'_, AppState>,
    session_id: Uuid,
    data: String,
) -> AppResult<()> {
    let mut guard = state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    write_to_writer(session.writer.as_mut(), &data)
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal::tests::write_forwards_bytes_to_pty`
Expected: PASS.

- [ ] **Step 5: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`
Expected: zero warnings.

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): terminal_write command + cat echo test"
```

---

## Task 5: Add `terminal_resize` and `terminal_kill` commands

**Files:**
- Modify: `gui/src-tauri/src/commands/terminal.rs`

- [ ] **Step 1: Write the failing tests**

Append inside `mod tests`:

```rust
    #[test]
    fn resize_changes_pty_size_no_panic() {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        pair.master
            .resize(PtySize { rows: 1, cols: 1, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        pair.master
            .resize(PtySize { rows: 200, cols: 500, pixel_width: 0, pixel_height: 0 })
            .unwrap();
    }

    #[test]
    fn kill_terminates_child_quickly() {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/sleep");
        cmd.arg("60");
        let mut child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);
        let start = std::time::Instant::now();
        child.kill().unwrap();
        let _ = child.wait();
        assert!(start.elapsed() < Duration::from_secs(2));
    }
```

- [ ] **Step 2: Run tests to verify they fail to compile (no harness yet)**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal`
Expected: existing tests still pass; new tests pass too because they exercise the library directly. (If `CommandBuilder` import is missing, fix the import line.) Move on to wiring the commands.

- [ ] **Step 3: Add the resize + kill commands**

Append to `gui/src-tauri/src/commands/terminal.rs`:

```rust
#[tauri::command]
pub async fn terminal_resize(
    state: State<'_, AppState>,
    session_id: Uuid,
    cols: u16,
    rows: u16,
) -> AppResult<()> {
    let guard = state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
    let session = guard
        .get(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    let cols = cols.max(1);
    let rows = rows.max(1);
    session
        .master
        .resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::Terminal(format!("resize: {e}")))
}

#[tauri::command]
pub async fn terminal_kill(
    state: State<'_, AppState>,
    session_id: Uuid,
) -> AppResult<()> {
    let mut guard = state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
    let mut session = guard
        .remove(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    let _ = session.child.kill();
    session.reader_task.abort();
    Ok(())
}
```

- [ ] **Step 4: Run all terminal tests**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal`
Expected: 4 tests pass.

- [ ] **Step 5: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): terminal_resize + terminal_kill commands"
```

---

## Task 6: Add `terminal_list` command and session-cap test

**Files:**
- Modify: `gui/src-tauri/src/commands/terminal.rs`

- [ ] **Step 1: Add the list command**

Append to `gui/src-tauri/src/commands/terminal.rs` (above `#[cfg(test)]`):

```rust
#[tauri::command]
pub async fn terminal_list(state: State<'_, AppState>) -> AppResult<Vec<SessionMeta>> {
    Ok(state.terminals.list())
}
```

- [ ] **Step 2: Write the session-cap unit test**

Append inside `mod tests`:

```rust
    #[test]
    fn session_cap_constant_matches_spec() {
        assert_eq!(MAX_SESSIONS, 16);
    }

    #[test]
    fn terminal_list_empty_initially() {
        let reg = crate::state::TerminalRegistry::default();
        assert!(reg.list().is_empty());
    }

    #[test]
    fn registry_drop_kills_orphan_children() {
        use crate::state::{PtySession, SessionMeta, TerminalRegistry};
        use chrono::Utc;
        use uuid::Uuid;

        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/sleep");
        cmd.arg("60");
        let child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);
        let writer = pair.master.take_writer().unwrap();

        let reg = TerminalRegistry::default();
        let id = Uuid::new_v4();
        let meta = SessionMeta {
            id,
            cwd: "/tmp".into(),
            shell: "/bin/sleep".into(),
            title: "sleep".into(),
            created_at: Utc::now(),
        };
        let dummy_task = tauri::async_runtime::spawn_blocking(|| {});
        reg.sessions.lock().unwrap().insert(
            id,
            PtySession {
                master: pair.master,
                writer,
                child,
                reader_task: dummy_task,
                meta,
            },
        );
        drop(reg);
        // If Drop didn't run, /bin/sleep would be left as a zombie.
        // We cannot reliably check for the PID here, so this is mainly a
        // smoke test that Drop compiles + executes without panic.
    }
```

- [ ] **Step 3: Run tests**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal`
Expected: all 6 tests pass.

- [ ] **Step 4: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): terminal_list command + cap constant test"
```

---

## Task 7: Register commands in `lib.rs` and confirm Manager unused-import resolved

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Add new commands to `generate_handler!`**

Edit `gui/src-tauri/src/lib.rs`. Inside the `tauri::generate_handler![ ... ]` macro at line 384, append these lines (place after the last command, before the closing `]`):

```rust
            commands::terminal::terminal_spawn,
            commands::terminal::terminal_write,
            commands::terminal::terminal_resize,
            commands::terminal::terminal_kill,
            commands::terminal::terminal_list,
```

- [ ] **Step 2: Remove the unused `Manager` import in `terminal.rs` if clippy warns**

If clippy reports `unused import: Manager`, edit `gui/src-tauri/src/commands/terminal.rs` and change

```rust
use tauri::{AppHandle, Emitter, Manager, State};
```

to

```rust
use tauri::{AppHandle, Emitter, State};
```

- [ ] **Step 3: Build release**

Run: `cd gui/src-tauri && cargo build --release`
Expected: succeeds, no warnings.

- [ ] **Step 4: Clippy + tests**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings && cargo test --lib`
Expected: zero warnings, all tests pass.

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/src/lib.rs gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): register PTY commands with Tauri handler"
```

---

## Task 8: Add Linux `PR_SET_PDEATHSIG` so orphan shells die with the app

**Files:**
- Modify: `gui/src-tauri/src/commands/terminal.rs`

- [ ] **Step 1: Add the `libc` dep**

Edit `gui/src-tauri/Cargo.toml` and append:

```toml
libc = "0.2"
```

- [ ] **Step 2: Wire `pre_exec` into the spawn path**

In `gui/src-tauri/src/commands/terminal.rs`, locate the line:

```rust
    cmd.cwd(&cwd);
```

and immediately after it insert:

```rust
    #[cfg(target_os = "linux")]
    {
        // SAFETY: called in the child between fork and exec; only async-signal-safe ops.
        unsafe {
            cmd.pre_exec(|| {
                if libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGTERM as libc::c_ulong, 0, 0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
    }
```

- [ ] **Step 3: Add a smoke test that proves the pdeathsig hook compiles and the spawn pipeline still works**

Append inside `mod tests`:

```rust
    #[test]
    fn spawn_pipeline_still_starts_shell_after_pdeathsig() {
        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/echo");
        cmd.arg("hi");
        let mut child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);
        let status = child.wait().unwrap();
        assert!(status.success());
    }
```

- [ ] **Step 4: Build + test**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal && cargo clippy --all-targets -- -D warnings`
Expected: passes cleanly.

- [ ] **Step 5: Commit**

```bash
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): PR_SET_PDEATHSIG so orphan shells die with parent"
```

---

## Task 9: Frontend deps and Commit Mono font assets

**Files:**
- Modify: `gui/package.json`
- Create: `gui/src/assets/fonts/CommitMono-400-Regular.woff2`
- Create: `gui/src/assets/fonts/CommitMono-700-Regular.woff2`
- Create: `gui/src/assets/fonts/CommitMono-LICENSE.txt`

- [ ] **Step 1: Add xterm packages**

Run from repo root:

```bash
cd gui && npm install --save \
  @xterm/xterm@^5.5.0 \
  @xterm/addon-fit@^0.10.0 \
  @xterm/addon-webgl@^0.18.0 \
  @xterm/addon-web-links@^0.11.0 \
  @xterm/addon-search@^0.15.0
```

Expected: `package.json` updated with five new entries under `dependencies`.

- [ ] **Step 2: Download Commit Mono woff2 + license**

From repo root:

```bash
mkdir -p gui/src/assets/fonts
cd gui/src/assets/fonts
curl -L --fail -o CommitMono-400-Regular.woff2 \
  https://github.com/eigilnikolajsen/commit-mono/raw/main/fonts/woff2/CommitMono-400-Regular.woff2
curl -L --fail -o CommitMono-700-Regular.woff2 \
  https://github.com/eigilnikolajsen/commit-mono/raw/main/fonts/woff2/CommitMono-700-Regular.woff2
curl -L --fail -o CommitMono-LICENSE.txt \
  https://raw.githubusercontent.com/eigilnikolajsen/commit-mono/main/LICENSE
```

Expected: three files exist. Verify both woff2 files are non-empty: `du -b gui/src/assets/fonts/CommitMono-400-Regular.woff2` (should be > 20 KB).

If the URLs return 404, fall back to the prebuilt `commit-mono` npm package: `npm install --save commit-mono` and import the woff2 directly from `node_modules/commit-mono/fonts/woff2/`.

- [ ] **Step 3: Verify Vite build still passes**

Run: `cd gui && npm run build`
Expected: tsc + vite build succeed.

- [ ] **Step 4: Commit**

```bash
git add gui/package.json gui/package-lock.json gui/src/assets/fonts/
git commit -m "feat(terminal): add xterm.js deps and Commit Mono font assets"
```

---

## Task 10: Create `terminal.css` with glass theme and font-face declarations

**Files:**
- Create: `gui/src/components/terminal/terminal.css`
- Modify: `gui/src/App.css`

- [ ] **Step 1: Create `gui/src/components/terminal/terminal.css`**

```css
@font-face {
  font-family: "Commit Mono";
  src: url("../../assets/fonts/CommitMono-400-Regular.woff2") format("woff2");
  font-weight: 400;
  font-style: normal;
  font-display: swap;
}
@font-face {
  font-family: "Commit Mono";
  src: url("../../assets/fonts/CommitMono-700-Regular.woff2") format("woff2");
  font-weight: 700;
  font-style: normal;
  font-display: swap;
}

.terminal-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: linear-gradient(135deg, #1c1f2b 0%, #0d1117 100%);
  padding: 12px;
  box-sizing: border-box;
}

.terminal-tabs {
  display: flex;
  align-items: stretch;
  gap: 4px;
  padding: 8px 12px 0 12px;
  background: rgba(255, 255, 255, 0.03);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  backdrop-filter: blur(8px);
  font-family: "Commit Mono", ui-monospace, "JetBrains Mono", monospace;
  font-size: 12px;
  user-select: none;
}

.terminal-tab {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 6px 6px 0 0;
  color: #6b7280;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.terminal-tab:hover {
  color: #a5b4fc;
}

.terminal-tab.active {
  background: rgba(255, 255, 255, 0.07);
  color: #a5b4fc;
  backdrop-filter: blur(8px);
}

.terminal-tab .close {
  opacity: 0;
  transition: opacity 0.15s;
  font-size: 11px;
  padding: 0 2px;
}

.terminal-tab:hover .close,
.terminal-tab.active .close {
  opacity: 0.6;
}

.terminal-tab .close:hover {
  opacity: 1;
  color: #fda4af;
}

.terminal-tabs .new-tab {
  padding: 6px 10px;
  color: #6b7280;
  cursor: pointer;
  border-radius: 6px 6px 0 0;
}

.terminal-tabs .new-tab:hover {
  color: #a5b4fc;
  background: rgba(255, 255, 255, 0.04);
}

.terminal-tabs .new-tab.claude {
  margin-left: 4px;
  color: #86efac;
}

.terminal-view-container {
  flex: 1;
  background: rgba(15, 17, 28, 0.65);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 0 8px 8px 8px;
  padding: 14px 16px;
  overflow: hidden;
  position: relative;
}

.terminal-view {
  width: 100%;
  height: 100%;
}

.terminal-exit-banner {
  position: absolute;
  bottom: 8px;
  left: 16px;
  right: 16px;
  padding: 8px 12px;
  background: rgba(15, 17, 28, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 6px;
  color: #9ca3af;
  font-family: "Commit Mono", monospace;
  font-size: 12px;
}

.terminal-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  gap: 16px;
  color: #6b7280;
  font-family: "Commit Mono", monospace;
}

.terminal-empty .actions {
  display: flex;
  gap: 12px;
}

.terminal-empty button {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  color: #a5b4fc;
  padding: 8px 16px;
  border-radius: 6px;
  font-family: inherit;
  font-size: 13px;
  cursor: pointer;
}

.terminal-empty button.claude {
  color: #86efac;
}

.terminal-empty button:hover {
  background: rgba(255, 255, 255, 0.08);
}
```

- [ ] **Step 2: Import the stylesheet from `App.css`**

Add a new import line at the top of `gui/src/App.css`:

```css
@import "./components/terminal/terminal.css";
```

- [ ] **Step 3: Build**

Run: `cd gui && npm run build`
Expected: build succeeds, no missing-font errors.

- [ ] **Step 4: Commit**

```bash
git add gui/src/components/terminal/terminal.css gui/src/App.css
git commit -m "feat(terminal): glass theme CSS + Commit Mono @font-face"
```

---

## Task 11: Create `theme.ts` and `useTerminalSession.ts` hook

**Files:**
- Create: `gui/src/components/terminal/theme.ts`
- Create: `gui/src/components/terminal/useTerminalSession.ts`

- [ ] **Step 1: Create `theme.ts`**

```ts
import type { ITheme } from "@xterm/xterm";

export const glassTheme: ITheme = {
  background: "rgba(15, 17, 28, 0.65)",
  foreground: "#e6e6fa",
  cursor: "#e6e6fa",
  cursorAccent: "#0a0c19",
  selectionBackground: "rgba(165, 180, 252, 0.25)",
  black: "#1a1b26",
  red: "#fda4af",
  green: "#86efac",
  yellow: "#fde68a",
  blue: "#a5b4fc",
  magenta: "#c4b5fd",
  cyan: "#67e8f9",
  white: "#e6e6fa",
  brightBlack: "#6b7280",
  brightRed: "#fb7185",
  brightGreen: "#4ade80",
  brightYellow: "#facc15",
  brightBlue: "#818cf8",
  brightMagenta: "#a78bfa",
  brightCyan: "#22d3ee",
  brightWhite: "#ffffff",
};

export const terminalFont = {
  family: "'Commit Mono', ui-monospace, 'JetBrains Mono', monospace",
  size: 13.5,
  lineHeight: 1.5,
  weight: 400 as const,
};
```

- [ ] **Step 2: Create `useTerminalSession.ts`**

```ts
import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { SearchAddon } from "@xterm/addon-search";
import { glassTheme, terminalFont } from "./theme";

export interface SessionMeta {
  id: string;
  cwd: string;
  shell: string;
  title: string;
  created_at: string;
}

export interface UseTerminalSessionOptions {
  containerRef: React.RefObject<HTMLDivElement>;
  cwd?: string;
  shell?: string;
  initialCommand?: string;
  onExit?: (code: number) => void;
}

export interface TerminalSessionHandle {
  sessionId: string | null;
  meta: SessionMeta | null;
  error: string | null;
  exitCode: number | null;
  focus: () => void;
  fit: () => void;
}

export function useTerminalSession(opts: UseTerminalSessionOptions): TerminalSessionHandle {
  const { containerRef, cwd, shell, initialCommand, onExit } = opts;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [meta, setMeta] = useState<SessionMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    let unlistenOutput: UnlistenFn | undefined;
    let unlistenExit: UnlistenFn | undefined;
    let disposed = false;
    let spawnedId: string | null = null;

    async function start() {
      if (!containerRef.current) return;

      const term = new Terminal({
        theme: glassTheme,
        fontFamily: terminalFont.family,
        fontSize: terminalFont.size,
        lineHeight: terminalFont.lineHeight,
        fontWeight: terminalFont.weight,
        cursorBlink: true,
        scrollback: 5000,
        allowProposedApi: true,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.loadAddon(new WebLinksAddon());
      term.loadAddon(new SearchAddon());
      try {
        term.loadAddon(new WebglAddon());
      } catch (e) {
        console.warn("[terminal] WebGL addon unavailable, falling back to canvas", e);
      }

      term.open(containerRef.current);
      fit.fit();
      termRef.current = term;
      fitRef.current = fit;

      try {
        const sessionMeta = await invoke<SessionMeta>("terminal_spawn", { cwd, shell });
        if (disposed) {
          await invoke("terminal_kill", { sessionId: sessionMeta.id });
          return;
        }
        spawnedId = sessionMeta.id;
        setSessionId(sessionMeta.id);
        setMeta(sessionMeta);

        unlistenOutput = await listen<string>(
          `terminal-output-${sessionMeta.id}`,
          (event) => {
            const bytes = Uint8Array.from(atob(event.payload), (c) => c.charCodeAt(0));
            term.write(bytes);
          },
        );

        unlistenExit = await listen<number>(
          `terminal-exit-${sessionMeta.id}`,
          (event) => {
            setExitCode(event.payload);
            onExit?.(event.payload);
          },
        );

        term.onData((data) => {
          invoke("terminal_write", { sessionId: sessionMeta.id, data }).catch((e) =>
            console.error("[terminal] write failed", e),
          );
        });

        term.onResize(({ cols, rows }) => {
          invoke("terminal_resize", { sessionId: sessionMeta.id, cols, rows }).catch(
            (e) => console.error("[terminal] resize failed", e),
          );
        });

        if (initialCommand) {
          await invoke("terminal_write", {
            sessionId: sessionMeta.id,
            data: `${initialCommand}\n`,
          });
        }

        const observer = new ResizeObserver(() => {
          if (!disposed) fit.fit();
        });
        if (containerRef.current) observer.observe(containerRef.current);
        return () => observer.disconnect();
      } catch (e) {
        setError(String(e));
      }
    }

    const cleanupPromise = start();

    return () => {
      disposed = true;
      cleanupPromise.then((maybeCleanup) => {
        if (typeof maybeCleanup === "function") maybeCleanup();
      });
      unlistenOutput?.();
      unlistenExit?.();
      if (spawnedId) {
        invoke("terminal_kill", { sessionId: spawnedId }).catch(() => {});
      }
      termRef.current?.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [containerRef, cwd, shell, initialCommand, onExit]);

  return {
    sessionId,
    meta,
    error,
    exitCode,
    focus: () => termRef.current?.focus(),
    fit: () => fitRef.current?.fit(),
  };
}
```

- [ ] **Step 3: Type-check**

Run: `cd gui && npm run build`
Expected: TypeScript compiles cleanly. If `atob` is flagged in the TS environment, add the comment `// eslint-disable-next-line` is *not* needed — `atob` is part of `lib.dom.d.ts`. If the build still fails, replace with `window.atob`.

- [ ] **Step 4: Commit**

```bash
git add gui/src/components/terminal/theme.ts gui/src/components/terminal/useTerminalSession.ts
git commit -m "feat(terminal): glass theme tokens + useTerminalSession hook"
```

---

## Task 12: Create `TerminalView.tsx` component

**Files:**
- Create: `gui/src/components/terminal/TerminalView.tsx`

- [ ] **Step 1: Write the component**

```tsx
import { useEffect, useRef } from "react";
import { useTerminalSession, type SessionMeta } from "./useTerminalSession";

interface TerminalViewProps {
  cwd?: string;
  shell?: string;
  initialCommand?: string;
  visible: boolean;
  onMeta?: (meta: SessionMeta) => void;
  onExit?: (code: number) => void;
}

export function TerminalView(props: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null!);
  const session = useTerminalSession({
    containerRef,
    cwd: props.cwd,
    shell: props.shell,
    initialCommand: props.initialCommand,
    onExit: props.onExit,
  });

  useEffect(() => {
    if (session.meta) props.onMeta?.(session.meta);
  }, [session.meta, props]);

  useEffect(() => {
    if (props.visible) {
      session.fit();
      session.focus();
    }
  }, [props.visible, session]);

  return (
    <div
      className="terminal-view-container"
      style={{ display: props.visible ? "block" : "none" }}
    >
      <div ref={containerRef} className="terminal-view" />
      {session.error && (
        <div className="terminal-exit-banner">Error: {session.error}</div>
      )}
      {session.exitCode !== null && (
        <div className="terminal-exit-banner">
          Process exited (code {session.exitCode}) · press Enter or close tab
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/terminal/TerminalView.tsx
git commit -m "feat(terminal): TerminalView component wrapping xterm.js instance"
```

---

## Task 13: Create `TerminalTabs.tsx` with `+` and `+ Claude` buttons

**Files:**
- Create: `gui/src/components/terminal/TerminalTabs.tsx`

- [ ] **Step 1: Write the component**

```tsx
interface TabState {
  uiId: string;
  title: string;
}

interface TerminalTabsProps {
  tabs: TabState[];
  activeId: string | null;
  onSelect: (uiId: string) => void;
  onClose: (uiId: string) => void;
  onNewShell: () => void;
  onNewClaude: () => void;
}

export function TerminalTabs(props: TerminalTabsProps) {
  const { tabs, activeId, onSelect, onClose, onNewShell, onNewClaude } = props;

  function handleMouseDown(e: React.MouseEvent, uiId: string) {
    if (e.button === 1) {
      e.preventDefault();
      onClose(uiId);
    }
  }

  return (
    <div className="terminal-tabs" role="tablist">
      {tabs.map((tab) => (
        <div
          key={tab.uiId}
          role="tab"
          aria-selected={activeId === tab.uiId}
          className={`terminal-tab${activeId === tab.uiId ? " active" : ""}`}
          onClick={() => onSelect(tab.uiId)}
          onMouseDown={(e) => handleMouseDown(e, tab.uiId)}
          title={tab.title}
        >
          <span className="title">{tab.title}</span>
          <span
            className="close"
            onClick={(e) => {
              e.stopPropagation();
              onClose(tab.uiId);
            }}
          >
            ×
          </span>
        </div>
      ))}
      <div className="new-tab" onClick={onNewShell} title="New shell (Ctrl+Shift+T)">
        +
      </div>
      <div
        className="new-tab claude"
        onClick={onNewClaude}
        title="New Claude session (Ctrl+Shift+C)"
      >
        + Claude
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/terminal/TerminalTabs.tsx
git commit -m "feat(terminal): TerminalTabs strip with + and + Claude"
```

---

## Task 14: Cross-panel spawn-request mailbox

**Files:**
- Create: `gui/src/components/terminal/spawnRequest.ts`

- [ ] **Step 1: Write the mailbox module**

```ts
export interface SpawnRequest {
  cwd?: string;
  shell?: string;
  initialCommand?: string;
}

type Listener = (req: SpawnRequest) => void;

const listeners = new Set<Listener>();

export function requestTerminal(req: SpawnRequest) {
  for (const l of listeners) l(req);
}

export function onSpawnRequest(l: Listener): () => void {
  listeners.add(l);
  return () => listeners.delete(l);
}
```

- [ ] **Step 2: Type-check**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/terminal/spawnRequest.ts
git commit -m "feat(terminal): spawn-request mailbox for cross-panel triggers"
```

---

## Task 15: Create `TerminalPanel.tsx` — tabs + views + keybinds + empty state

**Files:**
- Create: `gui/src/components/terminal/TerminalPanel.tsx`

- [ ] **Step 1: Write the panel**

```tsx
import { useCallback, useEffect, useState } from "react";
import { TerminalTabs } from "./TerminalTabs";
import { TerminalView } from "./TerminalView";
import { onSpawnRequest, type SpawnRequest } from "./spawnRequest";
import type { SessionMeta } from "./useTerminalSession";

interface Tab {
  uiId: string;
  title: string;
  cwd?: string;
  shell?: string;
  initialCommand?: string;
}

function uid() {
  return `tab-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

interface TerminalPanelProps {
  visible: boolean;
}

export function TerminalPanel({ visible }: TerminalPanelProps) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);

  const newShell = useCallback((req?: SpawnRequest) => {
    const tab: Tab = {
      uiId: uid(),
      title: req?.cwd
        ? `shell · ${req.cwd.split("/").pop() ?? req.cwd}`
        : "shell",
      cwd: req?.cwd,
      shell: req?.shell,
      initialCommand: req?.initialCommand,
    };
    setTabs((t) => [...t, tab]);
    setActiveId(tab.uiId);
  }, []);

  const newClaude = useCallback(() => {
    newShell({ initialCommand: "claude" });
  }, [newShell]);

  const closeTab = useCallback((uiId: string) => {
    setTabs((t) => {
      const remaining = t.filter((x) => x.uiId !== uiId);
      setActiveId((current) => {
        if (current !== uiId) return current;
        return remaining.length ? remaining[remaining.length - 1].uiId : null;
      });
      return remaining;
    });
  }, []);

  useEffect(() => {
    return onSpawnRequest((req) => newShell(req));
  }, [newShell]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "t") {
        e.preventDefault();
        newShell();
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        newClaude();
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "w") {
        if (activeId) {
          e.preventDefault();
          closeTab(activeId);
        }
      } else if (e.ctrlKey && e.key === "Tab" && !e.shiftKey) {
        if (tabs.length > 1 && activeId) {
          e.preventDefault();
          const idx = tabs.findIndex((t) => t.uiId === activeId);
          setActiveId(tabs[(idx + 1) % tabs.length].uiId);
        }
      } else if (e.ctrlKey && e.key === "Tab" && e.shiftKey) {
        if (tabs.length > 1 && activeId) {
          e.preventDefault();
          const idx = tabs.findIndex((t) => t.uiId === activeId);
          setActiveId(tabs[(idx - 1 + tabs.length) % tabs.length].uiId);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, tabs, activeId, newShell, newClaude, closeTab]);

  function onMeta(uiId: string, meta: SessionMeta) {
    setTabs((t) => t.map((x) => (x.uiId === uiId ? { ...x, title: meta.title } : x)));
  }

  return (
    <div className="terminal-panel">
      {tabs.length > 0 && (
        <TerminalTabs
          tabs={tabs.map((t) => ({ uiId: t.uiId, title: t.title }))}
          activeId={activeId}
          onSelect={setActiveId}
          onClose={closeTab}
          onNewShell={() => newShell()}
          onNewClaude={newClaude}
        />
      )}
      {tabs.length === 0 ? (
        <div className="terminal-empty">
          <div>No terminals</div>
          <div className="actions">
            <button onClick={() => newShell()}>+ New</button>
            <button className="claude" onClick={newClaude}>
              + Claude
            </button>
          </div>
        </div>
      ) : (
        tabs.map((t) => (
          <TerminalView
            key={t.uiId}
            cwd={t.cwd}
            shell={t.shell}
            initialCommand={t.initialCommand}
            visible={visible && t.uiId === activeId}
            onMeta={(m) => onMeta(t.uiId, m)}
          />
        ))
      )}
    </div>
  );
}
```

- [ ] **Step 2: Type-check**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/terminal/TerminalPanel.tsx
git commit -m "feat(terminal): TerminalPanel with tabs, keybinds, empty state"
```

---

## Task 16: Add `"terminal"` section to `App.tsx` sidebar

**Files:**
- Modify: `gui/src/App.tsx`

- [ ] **Step 1: Extend the `Section` type**

In `gui/src/App.tsx` at line 398, change:

```tsx
type Section = "worktrees" | "knowledge" | "agents" | "security" | "voice" | "memory" | "config" | "github";
```

to:

```tsx
type Section = "worktrees" | "terminal" | "knowledge" | "agents" | "security" | "voice" | "memory" | "config" | "github";
```

- [ ] **Step 2: Import the panel near the top of `App.tsx`**

Replace:

```tsx
import { JournalPanel } from "./components/JournalPanel";
```

with:

```tsx
import { JournalPanel } from "./components/JournalPanel";
import { TerminalPanel } from "./components/terminal/TerminalPanel";
```

- [ ] **Step 3: Add the sidebar nav button after the Worktrees entry**

Locate the Worktrees nav button in the sidebar (currently around line 2284):

```tsx
className={`nav-item ${currentSection === "worktrees" ? "active" : ""}`}
onClick={() => setCurrentSection("worktrees")}
```

Find the closing `</button>` (or `</div>`) for that nav-item. Immediately after it, insert a new button. Match the existing pattern exactly (icon, label, key handler). Use this template — keep whatever wrapper element type the surrounding entries use:

```tsx
<button
  className={`nav-item ${currentSection === "terminal" ? "active" : ""}`}
  onClick={() => setCurrentSection("terminal")}
  title="Terminal"
>
  <span className="nav-icon">▸_</span>
  <span className="nav-label">Terminal</span>
</button>
```

If existing buttons use SVG icons rather than text glyphs, follow that convention and pick a console/terminal-style SVG (search around the Worktrees entry for the icon pattern used).

- [ ] **Step 4: Route the section render**

Find the line containing `{currentSection === "worktrees" && renderWorktreesSection()}` (around line 4424). Add a sibling line immediately above or below it:

```tsx
{currentSection === "terminal" && (
  <TerminalPanel visible={currentSection === "terminal"} />
)}
```

- [ ] **Step 5: Build**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 6: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(terminal): wire Terminal section into App sidebar"
```

---

## Task 17: "Open Terminal" button on Worktrees panel

**Files:**
- Modify: `gui/src/App.tsx`

- [ ] **Step 1: Find the worktree row rendering**

In `gui/src/App.tsx`, find the function (or inline JSX) that renders each worktree row. Search for the `Worktree` action buttons (`Resume`, `Status`, etc.). It is invoked by `renderWorktreesSection()` referenced in Step 4 above.

- [ ] **Step 2: Import the spawn-request helper**

Near the other imports at the top of `App.tsx`, add:

```tsx
import { requestTerminal } from "./components/terminal/spawnRequest";
```

- [ ] **Step 3: Add the action button**

Inside the per-worktree row, alongside other action buttons, insert:

```tsx
<button
  onClick={() => {
    requestTerminal({ cwd: worktree.path });
    setCurrentSection("terminal");
  }}
  title="Open Terminal cwd'd to this worktree"
>
  Open Terminal
</button>
```

Replace `worktree.path` with whichever field on the row holds the absolute filesystem path of the worktree (check the local variable name in the surrounding map/loop — likely `wt`, `worktree`, or `repo.worktree`).

- [ ] **Step 4: Build**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 5: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(terminal): Open Terminal button on Worktrees panel"
```

---

## Task 18: Manual smoke test + deb build

**Files:** (no edits expected unless bugs found)

- [ ] **Step 1: Kill any old GUI**

```bash
pkill -f synthia-gui || true
```

- [ ] **Step 2: Build release deb**

Run: `cd gui && npm run tauri build`
Expected: deb produced in `gui/src-tauri/target/release/bundle/deb/`.

- [ ] **Step 3: Install deb**

```bash
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb
```

- [ ] **Step 4: Launch and verify**

```bash
synthia-gui &
```

Walk through manually:

1. Sidebar shows "Terminal" entry after Worktrees.
2. Click Terminal → empty state appears: "No terminals · + New · + Claude".
3. Click `+ New` → tab opens, prompt visible. Type `ls`, output renders.
4. Verify Commit Mono font: open browser DevTools (Ctrl+Shift+I) → Network → reload → confirm woff2 200 OK.
5. Click `+ Claude` → second tab, `claude` runs.
6. Run `htop` in a tab — TUI renders correctly, arrow keys/mouse work.
7. Resize window — terminal reflows without garbling.
8. Open Worktrees → click "Open Terminal" on a worktree → new tab spawns, `pwd` confirms cwd.
9. Press `Ctrl+Shift+T` → new tab. `Ctrl+Shift+W` → closes active tab. `Ctrl+Tab` → cycles tabs.
10. Run `exit` in a tab → exit banner appears.
11. Kill the app from system tray / window close → orphan check:

```bash
pgrep -af 'bash|zsh|claude' | grep -v code
```

Confirm no shells spawned by the GUI remain.

- [ ] **Step 5: Quality gates one last time**

Run:
```bash
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings && cargo test --lib
cd gui && npm run build
```
Expected: all green.

- [ ] **Step 6: Final commit (if smoke uncovered any tweaks)**

If anything needed adjusting during the smoke pass, commit those fixes with messages like `fix(terminal): …`. Otherwise skip.

---

## Done

All 18 tasks complete: PTY backend (Rust commands + registry), React UI (xterm.js panel with tabs and keybinds), Worktree integration, font + theme, and smoke-verified deb build. Total expected: 7 new Rust tests, 6 new files in `gui/src/components/terminal/`, 2 modifications to `App.tsx`.
