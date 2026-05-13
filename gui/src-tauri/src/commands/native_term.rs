//! Fake-embed prototype: spawn a borderless Wezterm window and position it over
//! the Terminal pane area inside the Synthia main window.
//!
//! # Wayland / Xwayland note
//!
//! `wmctrl` and `xdotool` only work under Xwayland (they require an X11
//! `DISPLAY`). Pure Wayland compositors (no `$DISPLAY`) cannot reposition
//! external windows — this is a fundamental protocol limitation.  When we
//! detect a pure Wayland environment we return a descriptive error so the React
//! layer can fall back to xterm.js gracefully.

use std::collections::HashMap;
use std::process::{Command, Stdio};
use std::time::Duration;

use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use tauri::State;
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::state::AppState;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// Physical-pixel geometry of the terminal pane as computed by React.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TermGeom {
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
}

/// Internal record kept for each live native-terminal session.
pub struct NativeTermSession {
    pub pid: u32,
    /// X11 window ID (decimal string) obtained via wmctrl, empty if not found yet.
    pub window_id: String,
    pub geom: TermGeom,
}

// ---------------------------------------------------------------------------
// State extension — stored in AppState.native_terminals
// ---------------------------------------------------------------------------

/// Newtype wrapper so we can store the map in `AppState` without touching the
/// existing `TerminalRegistry`.
#[derive(Default)]
pub struct NativeTermRegistry {
    pub sessions: Mutex<HashMap<String, NativeTermSession>>,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Return `true` if we are running under a pure Wayland display server with no
/// `DISPLAY` env-var available (i.e. Xwayland is not running / not the parent).
fn is_pure_wayland() -> bool {
    std::env::var("WAYLAND_DISPLAY").is_ok() && std::env::var("DISPLAY").is_err()
}

/// Try to find the X11 window ID of a wezterm window whose WM_CLASS contains
/// `class_fragment`.  Returns the decimal window ID string on success.
fn find_window_by_class(class_fragment: &str) -> Option<String> {
    // wmctrl -lG lists: "<wid>  <desktop>  <x>  <y>  <w>  <h>  <host>  <title>"
    let output = Command::new("wmctrl")
        .args(["-l", "-x"])
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    for line in stdout.lines() {
        if line.to_lowercase().contains(&class_fragment.to_lowercase()) {
            return line.split_whitespace().next().map(|s| s.to_string());
        }
    }
    None
}

/// Move and resize a window by its decimal X11 window ID using wmctrl.
/// Falls back to xdotool if wmctrl repositioning fails.
fn reposition_window(window_id: &str, geom: &TermGeom) -> AppResult<()> {
    // wmctrl: -i = use numeric ID, -r = target, -e = "gravity,x,y,w,h"
    let gravity_spec = format!("0,{},{},{},{}", geom.x, geom.y, geom.width, geom.height);
    let status = Command::new("wmctrl")
        .args(["-i", "-r", window_id, "-e", &gravity_spec])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    if status.map(|s| s.success()).unwrap_or(false) {
        return Ok(());
    }

    // Fallback: xdotool
    let move_ok = Command::new("xdotool")
        .args([
            "windowmove",
            "--sync",
            window_id,
            &geom.x.to_string(),
            &geom.y.to_string(),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    let size_ok = Command::new("xdotool")
        .args([
            "windowsize",
            "--sync",
            window_id,
            &geom.width.to_string(),
            &geom.height.to_string(),
        ])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false);

    if move_ok && size_ok {
        Ok(())
    } else {
        Err(AppError::Terminal(
            "wmctrl and xdotool both failed to reposition window".into(),
        ))
    }
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

/// Spawn a borderless Wezterm window and position it at `geom`.
///
/// Returns a `native_session_id` (UUID string) that the caller uses for
/// subsequent reposition / kill calls.
#[tauri::command]
pub async fn native_term_spawn(
    state: State<'_, AppState>,
    cwd: Option<String>,
    geom: TermGeom,
) -> AppResult<String> {
    if is_pure_wayland() {
        return Err(AppError::Terminal(
            "native embed unsupported on pure Wayland — Synthia must run under Xwayland \
             (set DISPLAY=:0 or launch via Xwayland)"
                .into(),
        ));
    }

    let session_id = Uuid::new_v4().to_string();
    let wm_class = format!("synthia-embed-{session_id}");

    // Resolve cwd — fall back to $HOME.
    let resolved_cwd = cwd
        .filter(|p| std::path::Path::new(p).is_dir())
        .or_else(|| std::env::var("HOME").ok())
        .unwrap_or_else(|| "/".to_string());

    // Build wezterm command.
    // --always-new-process: never reuse an existing wezterm instance.
    // --class:             sets WM_CLASS so we can locate the window via wmctrl.
    let mut cmd = Command::new("wezterm");
    cmd.arg("start")
        .arg("--always-new-process")
        .arg("--class")
        .arg(&wm_class)
        .arg("--cwd")
        .arg(&resolved_cwd)
        .arg("--config")
        .arg("window_decorations=\"NONE\"")
        .arg("--config")
        .arg("window_padding={left=0,right=0,top=0,bottom=0}")
        .arg("--config")
        .arg("enable_tab_bar=false")
        .arg("--config")
        .arg("window_close_confirmation=\"NeverPrompt\"")
        .stdout(Stdio::null())
        .stderr(Stdio::null());

    let child = cmd
        .spawn()
        .map_err(|e| AppError::Terminal(format!("wezterm spawn failed: {e}")))?;

    let pid = child.id();

    // Give wezterm time to open its window before we try to find it.
    tokio::time::sleep(Duration::from_millis(400)).await;

    // Attempt to locate the X11 window ID.
    let window_id = find_window_by_class(&wm_class).unwrap_or_default();

    // Position immediately if we found the window.
    if !window_id.is_empty() {
        let _ = reposition_window(&window_id, &geom);
    }

    let session = NativeTermSession {
        pid,
        window_id,
        geom: geom.clone(),
    };

    state
        .native_terminals
        .sessions
        .lock()
        .insert(session_id.clone(), session);

    Ok(session_id)
}

/// Move and resize the Wezterm window to match the new pane geometry.
#[tauri::command]
pub async fn native_term_reposition(
    state: State<'_, AppState>,
    native_session_id: String,
    geom: TermGeom,
) -> AppResult<()> {
    if is_pure_wayland() {
        return Err(AppError::Terminal(
            "native embed unsupported on pure Wayland".into(),
        ));
    }

    let mut sessions = state.native_terminals.sessions.lock();
    let session = sessions.get_mut(&native_session_id).ok_or_else(|| {
        AppError::Terminal(format!("unknown native session {native_session_id}"))
    })?;

    // If we didn't find the window on spawn, try again.
    if session.window_id.is_empty() {
        let wm_class = format!("synthia-embed-{native_session_id}");
        if let Some(wid) = find_window_by_class(&wm_class) {
            session.window_id = wid;
        }
    }

    if session.window_id.is_empty() {
        // Window not found yet — not a hard error, just skip silently.
        return Ok(());
    }

    session.geom = geom.clone();
    reposition_window(&session.window_id, &geom)
}

/// Kill the Wezterm process and remove the session.
#[tauri::command]
pub async fn native_term_kill(
    state: State<'_, AppState>,
    native_session_id: String,
) -> AppResult<()> {
    let session = state
        .native_terminals
        .sessions
        .lock()
        .remove(&native_session_id)
        .ok_or_else(|| {
            AppError::Terminal(format!("unknown native session {native_session_id}"))
        })?;

    // Best-effort SIGTERM — don't propagate errors (process may already be gone).
    let _ = Command::new("kill")
        .args(["-TERM", &session.pid.to_string()])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();

    Ok(())
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn geom_roundtrips_json() {
        let g = TermGeom {
            x: 100,
            y: 200,
            width: 800,
            height: 600,
        };
        let json = serde_json::to_string(&g).unwrap();
        let g2: TermGeom = serde_json::from_str(&json).unwrap();
        assert_eq!(g2.x, 100);
        assert_eq!(g2.y, 200);
        assert_eq!(g2.width, 800);
        assert_eq!(g2.height, 600);
    }

    #[test]
    fn native_term_registry_starts_empty() {
        let reg = NativeTermRegistry::default();
        assert!(reg.sessions.lock().is_empty());
    }

    #[test]
    fn pure_wayland_detection_does_not_panic() {
        // Just assert the function runs without panic.
        let _ = is_pure_wayland();
    }
}
