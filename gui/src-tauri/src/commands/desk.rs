//! Desk websocket credentials for the HUD.

use std::path::PathBuf;

use crate::error::{AppError, AppResult};

fn token_file() -> PathBuf {
    super::fleet::home_dir().join(".local/share/synthia/brain/desk.token")
}

/// The auth token synthia-brain wrote when it started. Missing means the brain is not running.
#[tauri::command]
pub fn get_desk_token() -> AppResult<String> {
    let text = std::fs::read_to_string(token_file())
        .map_err(|e| AppError::NotFound(format!("desk token: {e}")))?;
    let token = text.trim();
    if token.is_empty() {
        return Err(AppError::NotFound("desk token is empty".into()));
    }
    Ok(token.to_string())
}
