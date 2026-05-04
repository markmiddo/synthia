//! Overlay window Tauri commands.

use tauri::{Emitter, Manager};

use crate::error::{AppError, AppResult};

#[tauri::command]
pub fn show_overlay(app: tauri::AppHandle) -> AppResult<()> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.show().map_err(|e| AppError::Other(e.to_string()))?;
    }
    Ok(())
}

#[tauri::command]
pub fn hide_overlay(app: tauri::AppHandle) -> AppResult<()> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.hide().map_err(|e| AppError::Other(e.to_string()))?;
    }
    Ok(())
}

#[tauri::command]
pub fn set_overlay_recording(app: tauri::AppHandle, active: bool) -> AppResult<()> {
    if let Some(window) = app.get_webview_window("overlay") {
        window
            .emit("recording", active)
            .map_err(|e| AppError::Other(e.to_string()))?;
    }
    Ok(())
}
