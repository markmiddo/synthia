//! Hotkeys + word replacement Tauri commands.

use std::fs;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{get_config_path, get_runtime_dir};

#[derive(Deserialize, Serialize, Debug, Clone)]
pub struct WordReplacement {
    from: String,
    to: String,
}

#[tauri::command]
pub fn get_hotkeys() -> AppResult<(String, String)> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| AppError::Io(format!("Failed to read config: {}", e)))?;

    // Parse YAML manually for simplicity
    let mut dictation_key = "Right Ctrl".to_string();
    let mut assistant_key = "Right Alt".to_string();

    for line in content.lines() {
        if line.starts_with("dictation_key:") {
            dictation_key = line.split(':').nth(1)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or(dictation_key);
            // Convert from pynput format to display format
            dictation_key = dictation_key
                .replace("Key.ctrl_r", "Right Ctrl")
                .replace("Key.ctrl_l", "Left Ctrl")
                .replace("Key.alt_r", "Right Alt")
                .replace("Key.alt_l", "Left Alt")
                .replace("Key.shift_r", "Right Shift")
                .replace("Key.shift_l", "Left Shift");
        } else if line.starts_with("assistant_key:") {
            assistant_key = line.split(':').nth(1)
                .map(|s| s.trim().trim_matches('"').to_string())
                .unwrap_or(assistant_key);
            // Convert from pynput format to display format
            assistant_key = assistant_key
                .replace("Key.ctrl_r", "Right Ctrl")
                .replace("Key.ctrl_l", "Left Ctrl")
                .replace("Key.alt_r", "Right Alt")
                .replace("Key.alt_l", "Left Alt")
                .replace("Key.shift_r", "Right Shift")
                .replace("Key.shift_l", "Left Shift");
        }
    }

    Ok((dictation_key, assistant_key))
}

#[tauri::command]
pub fn save_hotkeys(dictation_key: String, assistant_key: String) -> AppResult<String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| AppError::Io(format!("Failed to read config: {}", e)))?;

    // Convert display format to pynput format
    let dictation_pynput = match dictation_key.as_str() {
        "Right Ctrl" => "Key.ctrl_r",
        "Left Ctrl" => "Key.ctrl_l",
        "Right Alt" => "Key.alt_r",
        "Left Alt" => "Key.alt_l",
        "Right Shift" => "Key.shift_r",
        "Left Shift" => "Key.shift_l",
        _ => &dictation_key,
    };

    let assistant_pynput = match assistant_key.as_str() {
        "Right Ctrl" => "Key.ctrl_r",
        "Left Ctrl" => "Key.ctrl_l",
        "Right Alt" => "Key.alt_r",
        "Left Alt" => "Key.alt_l",
        "Right Shift" => "Key.shift_r",
        "Left Shift" => "Key.shift_l",
        _ => &assistant_key,
    };

    // Update the config file
    let mut new_content = String::new();
    for line in content.lines() {
        if line.starts_with("dictation_key:") {
            new_content.push_str(&format!("dictation_key: \"{}\"\n", dictation_pynput));
        } else if line.starts_with("assistant_key:") {
            new_content.push_str(&format!("assistant_key: \"{}\"\n", assistant_pynput));
        } else {
            new_content.push_str(line);
            new_content.push('\n');
        }
    }

    fs::write(&config_path, new_content.trim_end())
        .map_err(|e| AppError::Io(format!("Failed to write config: {}", e)))?;

    // Signal Synthia to reload config by touching a signal file
    // Synthia watches for this file and updates hotkeys dynamically (no restart needed!)
    let signal_file = get_runtime_dir().join("synthia-reload-config");
    fs::write(&signal_file, "reload").ok();

    Ok("Hotkeys saved".to_string())
}

#[tauri::command]
pub fn get_word_replacements() -> Vec<WordReplacement> {
    let config_path = get_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    // Parse via serde_yaml — falls back to empty on malformed config rather
    // than crashing the GUI. The React side expects a `Vec<WordReplacement>`
    // (ordered), so we sort the HashMap keys for stable display.
    let cfg: crate::config::SynthiaConfigYaml = match serde_yaml::from_str(&content) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let mut entries: Vec<(String, String)> = cfg.word_replacements.into_iter().collect();
    entries.sort_by(|a, b| a.0.cmp(&b.0));
    entries
        .into_iter()
        .map(|(from, to)| WordReplacement { from, to })
        .collect()
}

#[tauri::command]
pub fn save_word_replacements(replacements: Vec<WordReplacement>) -> AppResult<String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| AppError::Io(format!("Failed to read config: {}", e)))?;

    let pairs: Vec<(String, String)> = replacements
        .into_iter()
        .map(|r| (r.from, r.to))
        .collect();
    let new_content = crate::yaml_writer::write_word_replacements(&content, &pairs);

    fs::write(&config_path, new_content.trim_end())
        .map_err(|e| AppError::Io(format!("Failed to write config: {}", e)))?;

    Ok("Word replacements saved".to_string())
}
