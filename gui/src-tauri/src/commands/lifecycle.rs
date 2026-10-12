//! Lifecycle Tauri commands: status, start/stop synthia, set mode, voice muted.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use crate::error::{AppError, AppResult};
use crate::get_runtime_state_path;
use crate::state::AppState;

/// The voice app runs as this systemd user unit.
const VOICE_UNIT: &str = "synthia-voice.service";

fn unit_active() -> bool {
    Command::new("systemctl")
        .args(["--user", "is-active", "--quiet", VOICE_UNIT])
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

fn process_running() -> bool {
    Command::new("pgrep")
        .args(["-f", "synthia.main"])
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[tauri::command]
pub fn get_status() -> String {
    if unit_active() || process_running() {
        "running".to_string()
    } else {
        "stopped".to_string()
    }
}

#[tauri::command]
pub fn start_synthia() -> AppResult<String> {
    if unit_active() {
        return Ok("Already running".to_string());
    }
    let out = Command::new("systemctl")
        .args(["--user", "start", VOICE_UNIT])
        .output()
        .map_err(|e| AppError::Process(format!("Failed to start: {}", e)))?;
    if !out.status.success() {
        let why = String::from_utf8_lossy(&out.stderr).trim().to_string();
        return Err(AppError::Process(format!(
            "systemctl could not start {}: {}",
            VOICE_UNIT,
            if why.is_empty() {
                "unknown error"
            } else {
                &why
            }
        )));
    }
    Ok("Synthia started".to_string())
}

#[tauri::command]
pub fn stop_synthia(state: tauri::State<'_, AppState>) -> AppResult<String> {
    let _ = Command::new("pkill").args(["-f", "synthia.main"]).output();

    let mut proc = state.synthia_process.lock();
    *proc = None;

    Ok("Synthia stopped".to_string())
}

#[tauri::command]
pub fn set_mode(mode: &str) -> AppResult<String> {
    Ok(format!("Mode set to: {}", mode))
}

#[tauri::command]
pub fn get_voice_muted() -> bool {
    let path: PathBuf = get_runtime_state_path();
    let content = match fs::read_to_string(&path) {
        Ok(c) => c,
        Err(_) => return false,
    };
    serde_json::from_str::<serde_json::Value>(&content)
        .ok()
        .and_then(|v| v.get("tts_muted").and_then(|b| b.as_bool()))
        .unwrap_or(false)
}

#[tauri::command]
pub fn set_voice_muted(muted: bool) -> AppResult<()> {
    let path = get_runtime_state_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut state: serde_json::Value = fs::read_to_string(&path)
        .ok()
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = state.as_object_mut() {
        obj.insert("tts_muted".to_string(), serde_json::Value::Bool(muted));
    }
    let serialized = serde_json::to_string_pretty(&state)?;
    fs::write(&path, serialized)?;
    Ok(())
}
