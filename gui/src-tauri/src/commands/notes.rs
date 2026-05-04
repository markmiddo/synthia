//! Notes Tauri commands.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};

pub(crate) fn get_notes_base_path() -> PathBuf {
    // Check NOTES_PATH env var first, then fall back to ~/dev/eventflo/docs
    if let Ok(path) = std::env::var("SYNTHIA_NOTES_PATH") {
        return PathBuf::from(path);
    }
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join("dev/eventflo/docs")
}

fn get_pinned_note_path() -> PathBuf {
    let config_dir = dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia");
    config_dir.join("pinned-note.txt")
}

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct NoteEntry {
    name: String,
    path: String,
    is_dir: bool,
}

#[tauri::command]
pub fn get_notes_base_path_cmd() -> String {
    get_notes_base_path().to_string_lossy().to_string()
}

#[tauri::command]
pub fn list_notes(subpath: Option<String>) -> AppResult<Vec<NoteEntry>> {
    let base = get_notes_base_path();
    let target = match subpath.as_deref() {
        Some(p) if !p.is_empty() => crate::paths::safe_join_relative(&base, p)?,
        _ => base.clone(),
    };

    if !target.exists() {
        return Err(AppError::NotFound("Directory not found".to_string()));
    }

    let mut entries = Vec::new();

    if let Ok(dir_entries) = fs::read_dir(&target) {
        for entry in dir_entries.flatten() {
            let path = entry.path();
            let name = path.file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_default();

            // Skip hidden files
            if name.starts_with('.') {
                continue;
            }

            let is_dir = path.is_dir();

            // Only show directories and markdown files
            if is_dir || name.ends_with(".md") {
                let relative_path = path.strip_prefix(&base)
                    .map(|p| p.to_string_lossy().to_string())
                    .unwrap_or_default();

                entries.push(NoteEntry {
                    name,
                    path: relative_path,
                    is_dir,
                });
            }
        }
    }

    // Sort: directories first, then alphabetically
    entries.sort_by(|a, b| {
        match (a.is_dir, b.is_dir) {
            (true, false) => std::cmp::Ordering::Less,
            (false, true) => std::cmp::Ordering::Greater,
            _ => a.name.to_lowercase().cmp(&b.name.to_lowercase()),
        }
    });

    Ok(entries)
}

#[tauri::command]
pub fn read_note(path: String) -> AppResult<String> {
    let base = get_notes_base_path();
    let full_path = crate::paths::safe_join_relative(&base, &path)?;
    fs::read_to_string(&full_path)
        .map_err(|e| AppError::Io(format!("Failed to read file: {}", e)))
}

#[tauri::command]
pub fn get_note_preview(path: String) -> AppResult<String> {
    let base = get_notes_base_path();
    let full = crate::paths::safe_join_relative(&base, &path)?;
    let content = std::fs::read_to_string(&full)?;
    let preview: String = content.chars().take(200).collect();
    Ok(preview)
}

#[tauri::command]
pub fn get_note_modified(path: String) -> AppResult<u64> {
    let base = get_notes_base_path();
    let full = crate::paths::safe_join_relative(&base, &path)?;
    let meta = std::fs::metadata(&full)?;
    let time = meta.modified()?;
    let duration = time
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    Ok(duration.as_secs())
}

#[tauri::command]
pub fn save_note(path: String, content: String) -> AppResult<String> {
    let base = get_notes_base_path();
    // Validate the relative path: rejects traversal/absolute. The target
    // file may or may not already exist, but its parent must.
    crate::paths::validate_relative_path(&path)?;
    let path_buf = std::path::Path::new(&path);
    let parent_rel = path_buf
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or("");
    let filename = path_buf
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| AppError::Validation("missing filename".to_string()))?;
    let full_path = crate::paths::safe_new_file(&base, parent_rel, filename)?;
    fs::write(&full_path, content)
        .map_err(|e| AppError::Io(format!("Failed to save file: {}", e)))?;

    Ok("Note saved".to_string())
}

#[tauri::command]
pub fn rename_note(old_path: String, new_path: String) -> AppResult<String> {
    let base = get_notes_base_path();
    // Source must exist — safe_join_relative validates and canonicalizes.
    let old_full = crate::paths::safe_join_relative(&base, &old_path)?;
    // Destination is a new path: validate, then ensure parent canonicalizes
    // under base.
    crate::paths::validate_relative_path(&new_path)?;
    let new_path_buf = std::path::Path::new(&new_path);
    let new_parent_rel = new_path_buf
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or("");
    let new_filename = new_path_buf
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| AppError::Validation("missing filename".to_string()))?;
    let new_full = crate::paths::safe_new_file(&base, new_parent_rel, new_filename)?;

    if new_full.exists() {
        return Err(AppError::Validation(
            "A file with that name already exists".to_string(),
        ));
    }

    fs::rename(&old_full, &new_full)
        .map_err(|e| AppError::Io(format!("Failed to rename file: {}", e)))?;

    Ok(new_path)
}

#[tauri::command]
pub fn move_note(path: String, new_parent: String) -> AppResult<String> {
    let base = get_notes_base_path();
    // Source must exist.
    let old_full = crate::paths::safe_join_relative(&base, &path)?;

    let filename = old_full
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| AppError::Validation("Invalid filename".to_string()))?
        .to_string();

    // Destination parent directory: must exist, must be under base.
    let new_dir = if new_parent.is_empty() {
        base.canonicalize()
            .map_err(|e| AppError::Path(format!("canonicalize base: {}", e)))?
    } else {
        crate::paths::safe_join_relative(&base, &new_parent)?
    };

    // Prevent moving a folder into itself.
    if old_full.is_dir() && new_dir.starts_with(&old_full) {
        return Err(AppError::Validation(
            "Cannot move a folder into itself".to_string(),
        ));
    }

    let new_full = new_dir.join(&filename);

    if new_full.exists() {
        return Err(AppError::Validation(
            "A file with that name already exists in the target folder".to_string(),
        ));
    }

    fs::rename(&old_full, &new_full)
        .map_err(|e| AppError::Io(format!("Failed to move file: {}", e)))?;

    // Return the new relative path
    let base_canonical = base
        .canonicalize()
        .map_err(|e| AppError::Path(format!("canonicalize base: {}", e)))?;
    let new_rel = new_full
        .strip_prefix(&base_canonical)
        .map_err(|_| AppError::Path("Path error".to_string()))?
        .to_string_lossy()
        .to_string();

    Ok(new_rel)
}

#[tauri::command]
pub fn create_folder(path: String) -> AppResult<String> {
    let base = get_notes_base_path();
    // Folder doesn't exist yet — validate path, canonicalize parent under base,
    // then create.
    crate::paths::validate_relative_path(&path)?;
    let path_buf = std::path::Path::new(&path);
    let parent_rel = path_buf
        .parent()
        .and_then(|p| p.to_str())
        .unwrap_or("");
    let folder_name = path_buf
        .file_name()
        .and_then(|n| n.to_str())
        .ok_or_else(|| AppError::Validation("missing folder name".to_string()))?;
    let full_path = crate::paths::safe_new_file(&base, parent_rel, folder_name)?;

    if full_path.exists() {
        return Err(AppError::Validation(
            "A folder with that name already exists".to_string(),
        ));
    }

    fs::create_dir_all(&full_path)
        .map_err(|e| AppError::Io(format!("Failed to create folder: {}", e)))?;

    Ok("Folder created".to_string())
}

#[tauri::command]
pub fn delete_note(path: String) -> AppResult<String> {
    let base = get_notes_base_path();
    let full_path = crate::paths::safe_join_relative(&base, &path)?;

    fs::remove_file(&full_path)
        .map_err(|e| AppError::Io(format!("Failed to delete file: {}", e)))?;

    Ok("Note deleted".to_string())
}

#[tauri::command]
pub fn get_pinned_note() -> String {
    fs::read_to_string(get_pinned_note_path()).unwrap_or_default()
}

#[tauri::command]
pub fn save_pinned_note(content: String) -> AppResult<String> {
    let path = get_pinned_note_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| AppError::Io(format!("Failed to create config dir: {}", e)))?;
    }
    fs::write(&path, content)
        .map_err(|e| AppError::Io(format!("Failed to write pinned note: {}", e)))?;
    Ok("saved".to_string())
}

#[cfg(test)]
mod tests {
    #[test]
    fn safe_join_blocks_traversal_in_notes_base() {
        let base = std::env::temp_dir();
        assert!(crate::paths::safe_join(&base, "../etc/passwd").is_err());
        assert!(crate::paths::safe_join(&base, "..").is_err());
    }

    #[test]
    fn validate_filename_blocks_separators() {
        assert!(crate::paths::validate_filename("foo/bar").is_err());
        assert!(crate::paths::validate_filename("foo\\bar").is_err());
    }

    #[test]
    fn validate_relative_path_blocks_notes_traversal() {
        assert!(crate::paths::validate_relative_path("../etc/passwd").is_err());
        assert!(crate::paths::validate_relative_path("subdir/../escape").is_err());
        assert!(crate::paths::validate_relative_path("/abs").is_err());
        // Legitimate nested notes path still works
        assert!(crate::paths::validate_relative_path("subfolder/note.md").is_ok());
    }
}
