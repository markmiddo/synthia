//! Telegram remote-mode Tauri commands.

use std::fs;
use std::process::Command;

use crate::error::{AppError, AppResult};
use crate::{get_runtime_dir, get_synthia_root};

#[tauri::command]
pub fn start_remote_mode() -> AppResult<String> {
    // Check if already running
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    if check.map(|o| o.status.success()).unwrap_or(false) {
        return Ok("Remote mode already running".to_string());
    }

    let root = get_synthia_root();
    let runtime_dir = get_runtime_dir();
    let remote_mode_file = runtime_dir.join("synthia-remote-mode");

    // Create the remote mode flag file (chat ID is read from config by telegram_bot.py)
    let _ = fs::write(&remote_mode_file, "remote");

    // Start the telegram bot with CUDA disabled
    let python = root.join("venv/bin/python");
    let bot_script = root.join("src/synthia/remote/telegram_bot.py");
    Command::new(&python)
        .args([bot_script.to_str().unwrap_or("")])
        .current_dir(&root)
        .env("CUDA_VISIBLE_DEVICES", "")
        .spawn()
        .map_err(|e| AppError::Process(format!("Failed to start remote mode: {}", e)))?;

    // Send notification in background (don't block UI)
    let _ = Command::new(&python)
        .args([
            bot_script.to_str().unwrap_or(""),
            "--notify",
            "🟢 *Remote Mode ENABLED*\n\nYou can now control Claude Code via Telegram."
        ])
        .current_dir(&root)
        .spawn();

    Ok("Remote mode started".to_string())
}

#[tauri::command]
pub fn stop_remote_mode() -> AppResult<String> {
    let root = get_synthia_root();
    let runtime_dir = get_runtime_dir();
    let remote_mode_file = runtime_dir.join("synthia-remote-mode");

    // Remove the remote mode flag file (stops response forwarding to Telegram)
    let _ = fs::remove_file(&remote_mode_file);

    // Kill the bot immediately for instant UI response
    let _ = Command::new("pkill")
        .args(["-f", "telegram_bot.py"])
        .output();

    // Send notification in background (after bot is killed, uses --notify which is standalone)
    let python = root.join("venv/bin/python");
    let bot_script = root.join("src/synthia/remote/telegram_bot.py");
    let _ = Command::new(&python)
        .args([
            bot_script.to_str().unwrap_or(""),
            "--notify",
            "🔴 *Remote Mode DISABLED*\n\nTelegram bot stopped."
        ])
        .current_dir(&root)
        .spawn();

    Ok("Remote mode stopped".to_string())
}

#[tauri::command]
pub fn get_remote_status() -> bool {
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    check.map(|o| o.status.success()).unwrap_or(false)
}
