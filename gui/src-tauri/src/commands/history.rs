//! History Tauri commands.

use std::fs;
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{get_history_file, get_runtime_dir};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct HistoryEntry {
    id: u32,
    text: String,
    mode: String,
    timestamp: String,
    response: Option<String>,
}

#[tauri::command]
pub fn get_history() -> Vec<HistoryEntry> {
    let history_file = get_history_file();
    if let Ok(content) = fs::read_to_string(&history_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
pub fn clear_history() -> AppResult<String> {
    let history_file = get_history_file();
    fs::write(&history_file, "[]")?;
    Ok("History cleared".to_string())
}

#[tauri::command]
pub fn resend_to_assistant(text: String) -> AppResult<String> {
    // Use xdotool to type the text into Claude Code terminal
    // First, we'll write to a temp file that the stop hook can check
    let prompt_file = get_runtime_dir().join("synthia-resend-prompt");
    fs::write(&prompt_file, &text)?;

    // Use xdotool to focus Claude Code window and type the text
    let _ = Command::new("xdotool")
        .args(["search", "--name", "Claude Code", "windowactivate", "--sync"])
        .output();

    // Type the text
    Command::new("xdotool")
        .args(["type", "--clearmodifiers", &text])
        .output()
        .map_err(|e| AppError::Process(format!("Failed to type text: {}", e)))?;

    // Press Enter to submit
    Command::new("xdotool")
        .args(["key", "Return"])
        .output()
        .map_err(|e| AppError::Process(format!("Failed to press Enter: {}", e)))?;

    // Clean up
    let _ = fs::remove_file(&prompt_file);

    Ok("Sent to assistant".to_string())
}
