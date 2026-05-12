//! Built-in PTY terminal sessions. See `docs/superpowers/specs/2026-05-13-terminal-emulator-design.md`.
//!
//! Orphan cleanup: portable-pty 0.8/0.9 does not expose `pre_exec` on `CommandBuilder`,
//! so we cannot install `PR_SET_PDEATHSIG`. Graceful shutdown is handled by the `Drop`
//! impl on `TerminalRegistry`. Hard parent crashes (SIGKILL/SIGSEGV) will leave shell
//! children orphaned — deferred to v2.

use std::io::Read;

use base64::Engine;
use chrono::Utc;
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use tauri::{AppHandle, Emitter, State, ipc::Channel};
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

    state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?
        .insert(session_id, session);

    let _ = app; // app handle is used by terminal_attach
    Ok(meta)
}

/// Start streaming PTY output for an already-spawned session.
///
/// `on_output` is a `Channel<String>` that receives base64-encoded PTY chunks.
/// Using a typed channel instead of the global event bus eliminates per-byte
/// routing overhead and removes visible keystroke lag.
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
        let mut guard = state
            .terminals
            .sessions
            .lock()
            .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
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

    let app_handle = app.clone();
    let task = tokio::task::spawn_blocking(move || {
        let mut buf = vec![0u8; READ_CHUNK_SIZE];
        loop {
            match reader.read(&mut buf) {
                Ok(0) => break,
                Ok(n) => {
                    let encoded =
                        base64::engine::general_purpose::STANDARD.encode(&buf[..n]);
                    // Channel::send is much faster than app_handle.emit for high-frequency
                    // streaming: it bypasses the global event router entirely.
                    if on_output.send(encoded).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
        // Exit notification stays on the event bus — it fires once and is low-frequency.
        let _ = app_handle.emit(&format!("terminal-exit-{session_id}"), 0_i32);
    });

    let mut guard = state
        .terminals
        .sessions
        .lock()
        .map_err(|_| AppError::Terminal("registry poisoned".into()))?;
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
    if let Some(t) = session.reader_task.take() {
        t.abort();
    }
    Ok(())
}

#[tauri::command]
pub async fn terminal_list(state: State<'_, AppState>) -> AppResult<Vec<SessionMeta>> {
    Ok(state.terminals.list())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;
    use std::io::Read;

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
}
