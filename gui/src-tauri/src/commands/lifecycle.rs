//! Lifecycle Tauri commands: status, start/stop synthia, set mode, voice muted.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use crate::error::{AppError, AppResult};
use crate::state::AppState;
use crate::{get_runtime_state_path, get_synthia_root};

#[tauri::command]
pub fn get_status() -> String {
    let output = Command::new("pgrep")
        .args(["-f", "synthia.main"])
        .output();

    match output {
        Ok(out) if out.status.success() => "running".to_string(),
        _ => "stopped".to_string(),
    }
}

#[tauri::command]
pub fn start_synthia(state: tauri::State<'_, AppState>) -> AppResult<String> {
    let mut proc = state.synthia_process.lock().unwrap();
    if proc.is_some() {
        return Ok("Already running".to_string());
    }

    let root = get_synthia_root();
    let log_path = root.join("synthia.log");
    let log_file = std::fs::File::create(&log_path)
        .map_err(|e| AppError::Io(format!("Failed to create log file: {}", e)))?;
    let stderr_file = log_file
        .try_clone()
        .map_err(|e| AppError::Io(format!("Failed to clone log file: {}", e)))?;
    let child = Command::new(root.join("run.sh"))
        .current_dir(&root)
        .stdout(std::process::Stdio::from(log_file))
        .stderr(std::process::Stdio::from(stderr_file))
        .spawn()
        .map_err(|e| AppError::Process(format!("Failed to start: {}", e)))?;

    *proc = Some(child);
    Ok("Synthia started".to_string())
}

#[tauri::command]
pub fn stop_synthia(state: tauri::State<'_, AppState>) -> AppResult<String> {
    let _ = Command::new("pkill")
        .args(["-f", "synthia.main"])
        .output();

    let mut proc = state.synthia_process.lock().unwrap();
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
