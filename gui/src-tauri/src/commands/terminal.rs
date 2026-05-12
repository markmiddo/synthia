//! Built-in PTY terminal sessions. See `docs/superpowers/specs/2026-05-13-terminal-emulator-design.md`.

use std::io::Read;

use base64::Engine;
use chrono::Utc;
use portable_pty::{native_pty_system, CommandBuilder, PtySize};
use tauri::{AppHandle, Emitter, State};
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
    let reader_task = tokio::task::spawn_blocking(move || {
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
