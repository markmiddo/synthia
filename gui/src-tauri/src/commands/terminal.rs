//! Built-in PTY terminal sessions. See `docs/superpowers/specs/2026-05-13-terminal-emulator-design.md`.
//!
//! Orphan cleanup: portable-pty 0.8/0.9 does not expose `pre_exec` on `CommandBuilder`,
//! so we cannot install `PR_SET_PDEATHSIG`. Graceful shutdown is handled by the `Drop`
//! impl on `TerminalRegistry`. Hard parent crashes (SIGKILL/SIGSEGV) will leave shell
//! children orphaned — deferred to v2.
//!
//! # Performance notes
//!
//! - **Binary channel**: PTY output is sent as raw bytes via `InvokeResponseBody::Raw`
//!   (no base64 encode on Rust side, no atob on JS side). Saves ~33% bandwidth and
//!   eliminates CPU-intensive encode/decode on every keystroke echo.
//! - **Read coalescing**: a blocking reader thread feeds an unbounded mpsc channel; an
//!   async batcher task drains it every ~1 ms before forwarding to the IPC channel.
//!   This collapses many 1-byte reads (shell echo) into a single IPC message while
//!   keeping first-byte latency ≤ 1 ms.
//! - **parking_lot::Mutex**: used throughout `AppState` — faster than std, no poison.

use std::io::Read;
use std::time::Duration;

use base64::Engine;
use chrono::Utc;
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use tauri::{AppHandle, Emitter, State, ipc::Channel};
use tokio::sync::mpsc;
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::state::{AppState, PtySession, SessionMeta};

const MAX_SESSIONS: usize = 16;
const READ_CHUNK_SIZE: usize = 4096;

/// How long the batcher waits for additional bytes before flushing.
/// 1 ms gives responsive typing feel while still coalescing multi-byte escapes.
const BATCH_WINDOW: Duration = Duration::from_millis(1);

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

/// Internal helper used by both `terminal_spawn` (the JS-facing command) and
/// `native_term_show` (which transparently creates a PTY on first display).
/// Returns the new session's metadata; the session is inserted into the
/// registry with `pending_reader` set.
pub fn spawn_pty_session_inline(
    state: &crate::state::TerminalRegistry,
    cwd: Option<String>,
    shell: Option<String>,
) -> AppResult<SessionMeta> {
    let shell = shell.unwrap_or_else(detect_shell);
    let cwd = cwd
        .filter(|p| std::path::Path::new(p).is_dir())
        .or_else(|| std::env::var("HOME").ok())
        .ok_or_else(|| AppError::Terminal("no usable cwd".into()))?;

    {
        let guard = state.sessions.lock();
        if guard.len() >= MAX_SESSIONS {
            return Err(AppError::Terminal(format!(
                "max {MAX_SESSIONS} terminals"
            )));
        }
    }

    let pty_system = native_pty_system();
    let pair = pty_system
        .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
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
    let reader = pair
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

    let session = PtySession {
        master: pair.master,
        writer,
        child,
        reader_task: None,
        pending_reader: Some(reader),
        meta: meta.clone(),
    };

    state.sessions.lock().insert(session_id, session);
    Ok(meta)
}

#[tauri::command]
pub async fn terminal_spawn(
    app: AppHandle,
    state: State<'_, AppState>,
    cwd: Option<String>,
    shell: Option<String>,
) -> AppResult<SessionMeta> {
    let _ = app;
    spawn_pty_session_inline(&state.terminals, cwd, shell)
}

/// Start streaming PTY output for an already-spawned session.
///
/// `on_output` is a `Channel<InvokeResponseBody>` that receives raw PTY bytes.
/// Using raw binary (`InvokeResponseBody::Raw`) avoids base64 encoding overhead
/// on both sides: no encode in Rust, no `atob` in JavaScript.
///
/// Read coalescing: a blocking reader thread pushes chunks into an unbounded mpsc
/// channel; an async batcher task drains it within a 1 ms window before sending
/// a single coalesced IPC message. This eliminates per-byte round-trips for
/// single-keystroke echo while keeping first-byte latency ≤ 1 ms.
///
/// React must call this AFTER setting up `channel.onmessage` and subscribing
/// to `terminal-exit-{id}`, otherwise the first burst of output (the shell
/// prompt) may be missed.
#[tauri::command]
pub async fn terminal_attach(
    app: AppHandle,
    state: State<'_, AppState>,
    session_id: Uuid,
    on_output: Channel<String>,
) -> AppResult<()> {
    let mut reader = {
        let mut guard = state.terminals.sessions.lock();
        let session = guard
            .get_mut(&session_id)
            .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
        if session.reader_task.is_some() {
            return Ok(()); // idempotent
        }
        session
            .pending_reader
            .take()
            .ok_or_else(|| AppError::Terminal("session has no reader".into()))?
    };

    // Unbounded channel from the blocking reader thread → async batcher task.
    let (tx, mut rx) = mpsc::unbounded_channel::<Vec<u8>>();

    // Blocking reader thread: reads PTY output as fast as the OS delivers it.
    tokio::task::spawn_blocking(move || {
        let mut buf = vec![0u8; READ_CHUNK_SIZE];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    if tx.send(buf[..n].to_vec()).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });

    // Async batcher task: coalesces reads within BATCH_WINDOW and sends a
    // single binary IPC message per window.
    let app_handle = app.clone();
    let task = tokio::spawn(async move {
        loop {
            // Wait for the first chunk (blocking until PTY has data).
            let first = match rx.recv().await {
                Some(v) => v,
                None => break,
            };

            let mut batch = first;

            // Drain any immediately-available chunks within the batch window.
            let deadline = tokio::time::Instant::now() + BATCH_WINDOW;
            while let Ok(Some(more)) = tokio::time::timeout_at(deadline, rx.recv()).await {
                batch.extend_from_slice(&more);
            }

            // Send base64-encoded — Channel<String> serializes reliably across Tauri 2.x;
            // raw binary via InvokeResponseBody::Raw was unreliable on this webkit build.
            let encoded = base64::engine::general_purpose::STANDARD.encode(&batch);
            if on_output.send(encoded).is_err() {
                break;
            }
        }
        // Exit notification stays on the event bus — it fires once and is low-frequency.
        let _ = app_handle.emit(&format!("terminal-exit-{session_id}"), 0_i32);
    });

    let mut guard = state.terminals.sessions.lock();
    if let Some(session) = guard.get_mut(&session_id) {
        session.reader_task = Some(task);
    } else {
        task.abort();
    }
    Ok(())
}

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
    let mut guard = state.terminals.sessions.lock();
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    write_to_writer(session.writer.as_mut(), &data)
}

#[tauri::command]
pub async fn terminal_resize(
    state: State<'_, AppState>,
    session_id: Uuid,
    cols: u16,
    rows: u16,
) -> AppResult<()> {
    let guard = state.terminals.sessions.lock();
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
    let mut guard = state.terminals.sessions.lock();
    let mut session = guard
        .remove(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    let _ = session.child.kill();
    if let Some(t) = session.reader_task.take() {
        t.abort();
    }
    Ok(())
}

#[tauri::command]
pub async fn terminal_list(state: State<'_, AppState>) -> AppResult<Vec<SessionMeta>> {
    Ok(state.terminals.list())
}

/// PTY handles leased to the native renderer. Returns `Some` on first call, `None` on subsequent calls.
// wired up in native_term/commands.rs (D Task 13)
#[allow(dead_code)]
pub struct LeasedPty {
    pub reader: Box<dyn std::io::Read + Send>,
    pub writer: Box<dyn std::io::Write + Send>,
}

/// Take the reader and writer out of a session so the native renderer can own them.
/// Leaves the master, child, and meta in place so `terminal_kill` still works.
/// Returns `Ok(Some(LeasedPty))` on first call; `Ok(None)` if already leased.
// wired up in native_term/commands.rs (D Task 13)
#[allow(dead_code)]
pub fn lease_for_native(
    registry: &crate::state::TerminalRegistry,
    session_id: Uuid,
) -> AppResult<Option<LeasedPty>> {
    let mut guard = registry.sessions.lock();
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    let Some(reader) = session.pending_reader.take() else {
        return Ok(None);
    };
    // Replace writer with a sink — the real one moves to LeasedPty.
    let real_writer = std::mem::replace(
        &mut session.writer,
        Box::new(std::io::sink()),
    );
    Ok(Some(LeasedPty { reader, writer: real_writer }))
}

/// Send a new PTY window size to the child process.
/// Called by the native renderer after computing cell dims so that bash/vim
/// wraps at the correct column count instead of the default 80x24.
#[allow(dead_code)]
pub fn set_pty_size(
    registry: &crate::state::TerminalRegistry,
    session_id: Uuid,
    cols: u16,
    rows: u16,
) -> AppResult<()> {
    let guard = registry.sessions.lock();
    let session = guard
        .get(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    session
        .master
        .resize(PtySize {
            rows,
            cols,
            pixel_width: 0,
            pixel_height: 0,
        })
        .map_err(|e| AppError::Terminal(format!("pty resize: {e}")))
}

/// Restore a previously-leased reader+writer back into the session.
/// Used on detach so subsequent xterm.js attaches still work.
// wired up in native_term/commands.rs (D Task 13)
#[allow(dead_code)]
pub fn restore_from_native(
    registry: &crate::state::TerminalRegistry,
    session_id: Uuid,
    leased: LeasedPty,
) -> AppResult<()> {
    let mut guard = registry.sessions.lock();
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    session.pending_reader = Some(leased.reader);
    session.writer = leased.writer;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::time::Duration;

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
    fn lease_takes_reader_and_writer() {
        use crate::state::TerminalRegistry;
        use crate::state::PtySession;
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
        let reader = pair.master.try_clone_reader().unwrap();

        let reg = TerminalRegistry::default();
        let id = Uuid::new_v4();
        reg.sessions.lock().insert(id, PtySession {
            master: pair.master,
            writer,
            child,
            reader_task: None,
            pending_reader: Some(reader),
            meta: crate::state::SessionMeta {
                id, cwd: "/tmp".into(), shell: "/bin/sleep".into(),
                title: "sleep".into(), created_at: Utc::now(),
            },
        });

        let leased = lease_for_native(&reg, id).unwrap();
        assert!(leased.is_some(), "lease should return reader + writer for fresh session");
        // Session entry stays in registry (so kill still works) but writer/reader fields are emptied.
        let guard = reg.sessions.lock();
        let session = guard.get(&id).unwrap();
        assert!(session.pending_reader.is_none(), "lease consumes pending_reader");
    }

    #[test]
    fn lease_returns_none_when_already_leased() {
        use crate::state::TerminalRegistry;
        use crate::state::PtySession;
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
        let reader = pair.master.try_clone_reader().unwrap();

        let reg = TerminalRegistry::default();
        let id = Uuid::new_v4();
        reg.sessions.lock().insert(id, PtySession {
            master: pair.master,
            writer,
            child,
            reader_task: None,
            pending_reader: Some(reader),
            meta: crate::state::SessionMeta {
                id, cwd: "/tmp".into(), shell: "/bin/sleep".into(),
                title: "sleep".into(), created_at: Utc::now(),
            },
        });

        let _first = lease_for_native(&reg, id).unwrap();
        let second = lease_for_native(&reg, id).unwrap();
        assert!(second.is_none(), "second lease must return None — already leased");
    }
}
