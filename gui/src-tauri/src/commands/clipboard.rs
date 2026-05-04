//! Clipboard history Tauri commands.

use std::fs;
use std::io::Write;
use std::process::{Command, Stdio};

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{get_clipboard_file, is_wayland_env};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct ClipboardEntry {
    id: u64,
    content: String,
    timestamp: String,
    hash: String,
}

#[tauri::command]
pub fn get_clipboard_history() -> Vec<ClipboardEntry> {
    let clipboard_file = get_clipboard_file();
    if let Ok(content) = fs::read_to_string(&clipboard_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
pub fn copy_from_clipboard_history(content: String) -> AppResult<String> {
    if is_wayland_env() {
        let mut child = Command::new("wl-copy")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| AppError::Process(format!("Failed to spawn wl-copy: {}", e)))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(content.as_bytes())
                .map_err(|e| AppError::Io(format!("Failed to write to wl-copy: {}", e)))?;
        }

        child
            .wait()
            .map_err(|e| AppError::Process(format!("wl-copy failed: {}", e)))?;
    } else {
        let mut child = Command::new("xclip")
            .args(["-selection", "clipboard"])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| AppError::Process(format!("Failed to spawn xclip: {}", e)))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(content.as_bytes())
                .map_err(|e| AppError::Io(format!("Failed to write to xclip: {}", e)))?;
        }

        child
            .wait()
            .map_err(|e| AppError::Process(format!("xclip failed: {}", e)))?;
    }

    Ok("Copied to clipboard".to_string())
}
