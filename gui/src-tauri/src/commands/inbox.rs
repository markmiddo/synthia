//! Inbox Tauri commands.

use std::fs;
use std::process::Command;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::get_inbox_file;

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct InboxItem {
    id: String,
    #[serde(rename = "type")]
    item_type: String,
    filename: String,
    path: Option<String>,
    url: Option<String>,
    received_at: String,
    size_bytes: Option<u64>,
    from_user: Option<String>,
    opened: bool,
}

#[derive(Deserialize, Serialize, Debug)]
pub struct InboxData {
    items: Vec<InboxItem>,
}

#[tauri::command]
pub fn get_inbox_items() -> Vec<InboxItem> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(data) = serde_json::from_str::<InboxData>(&content) {
            return data.items;
        }
    }
    Vec::new()
}

#[tauri::command]
pub fn open_inbox_item(
    id: String,
    item_type: String,
    path: Option<String>,
    url: Option<String>,
) -> AppResult<String> {
    // Open the item with xdg-open
    let target = if item_type == "url" {
        url.ok_or_else(|| AppError::Validation("No URL provided".to_string()))?
    } else {
        path.ok_or_else(|| AppError::Validation("No path provided".to_string()))?
    };

    Command::new("xdg-open")
        .arg(&target)
        .spawn()
        .map_err(|e| AppError::Process(format!("Failed to open: {}", e)))?;

    // Mark as opened in the inbox file
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(mut data) = serde_json::from_str::<InboxData>(&content) {
            for item in &mut data.items {
                if item.id == id {
                    item.opened = true;
                    break;
                }
            }
            let _ = fs::write(&inbox_file, serde_json::to_string_pretty(&data).unwrap_or_default());
        }
    }

    Ok("Opened".to_string())
}

#[tauri::command]
pub fn delete_inbox_item(id: String) -> AppResult<String> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(mut data) = serde_json::from_str::<InboxData>(&content) {
            // Find and remove the item, also delete file if exists
            let mut path_to_delete: Option<String> = None;
            data.items.retain(|item| {
                if item.id == id {
                    path_to_delete = item.path.clone();
                    false
                } else {
                    true
                }
            });

            // Delete the file if it exists
            if let Some(path) = path_to_delete {
                let _ = fs::remove_file(&path);
            }

            let _ = fs::write(&inbox_file, serde_json::to_string_pretty(&data).unwrap_or_default());
            return Ok("Deleted".to_string());
        }
    }
    Err(AppError::Other("Failed to delete item".to_string()))
}

#[tauri::command]
pub fn clear_inbox() -> AppResult<String> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(data) = serde_json::from_str::<InboxData>(&content) {
            // Delete all files
            for item in &data.items {
                if let Some(path) = &item.path {
                    let _ = fs::remove_file(path);
                }
            }
        }
    }

    // Clear the inbox
    let _ = fs::write(&inbox_file, r#"{"items": []}"#);
    Ok("Inbox cleared".to_string())
}
