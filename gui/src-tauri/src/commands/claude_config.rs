//! Synthia config + knowledge meta Tauri commands.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{get_config_path, get_runtime_dir};
use crate::commands::notes::get_notes_base_path;

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
pub struct SynthiaConfig {
    // Local vs Cloud
    use_local_stt: bool,
    use_local_llm: bool,
    use_local_tts: bool,
    // Models
    local_stt_model: String,
    local_llm_model: String,
    local_tts_voice: String,
    assistant_model: String,
    // TTS settings
    tts_voice: String,
    tts_speed: f64,
    // Other
    conversation_memory: i32,
    show_notifications: bool,
    play_sound_on_record: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone, Default)]
pub struct KnowledgeMeta {
    pinned: Vec<String>,
    recent: Vec<String>,
    #[serde(default)]
    expanded_folders: Vec<String>,
}

pub(crate) fn get_knowledge_meta_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("synthia")
        .join("knowledge-meta.json")
}

impl From<crate::config::SynthiaConfigYaml> for SynthiaConfig {
    fn from(y: crate::config::SynthiaConfigYaml) -> Self {
        SynthiaConfig {
            use_local_stt: y.use_local_stt,
            use_local_llm: y.use_local_llm,
            use_local_tts: y.use_local_tts,
            local_stt_model: y.local_stt_model,
            local_llm_model: y.local_llm_model,
            local_tts_voice: y.local_tts_voice,
            assistant_model: y.assistant_model,
            tts_voice: y.tts_voice,
            tts_speed: y.tts_speed,
            conversation_memory: y.conversation_memory,
            show_notifications: y.show_notifications,
            play_sound_on_record: y.play_sound_on_record,
        }
    }
}

#[tauri::command]
pub fn get_synthia_config() -> SynthiaConfig {
    let config_path = get_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return SynthiaConfig::default(),
    };

    // Parse the whole file via serde_yaml. Unknown keys are ignored
    // (SynthiaConfigYaml uses `#[serde(default)]` per field, no flatten).
    // On malformed YAML we fall back to defaults rather than crashing.
    let parsed: crate::config::SynthiaConfigYaml =
        serde_yaml::from_str(&content).unwrap_or_default();
    parsed.into()
}

#[tauri::command]
pub fn save_synthia_config(config: SynthiaConfig) -> AppResult<String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| AppError::Io(format!("Failed to read config: {}", e)))?;

    // Build the (key, formatted_value) update list. Quoting matches the
    // pre-refactor behaviour: model names + voices are double-quoted, bools
    // and numbers are bare. Preserves the on-disk shape Synthia's Python
    // loader has been seeing for months.
    let updates: Vec<(&str, String)> = vec![
        ("use_local_stt", config.use_local_stt.to_string()),
        ("use_local_llm", config.use_local_llm.to_string()),
        ("use_local_tts", config.use_local_tts.to_string()),
        ("local_stt_model", format!("\"{}\"", config.local_stt_model)),
        ("local_llm_model", format!("\"{}\"", config.local_llm_model)),
        ("local_tts_voice", config.local_tts_voice.clone()),
        ("assistant_model", format!("\"{}\"", config.assistant_model)),
        ("tts_voice", format!("\"{}\"", config.tts_voice)),
        ("tts_speed", config.tts_speed.to_string()),
        ("conversation_memory", config.conversation_memory.to_string()),
        ("show_notifications", config.show_notifications.to_string()),
        ("play_sound_on_record", config.play_sound_on_record.to_string()),
    ];

    let new_content = crate::yaml_writer::write_synthia_config_keys(&content, &updates);

    fs::write(&config_path, new_content)
        .map_err(|e| AppError::Io(format!("Failed to write config: {}", e)))?;

    // Signal Synthia to reload config
    let signal_file = get_runtime_dir().join("synthia-reload-config");
    fs::write(&signal_file, "reload").ok();

    Ok("Config saved".to_string())
}

#[tauri::command]
pub fn get_knowledge_meta() -> KnowledgeMeta {
    let path = get_knowledge_meta_path();
    let mut meta: KnowledgeMeta = if let Ok(content) = fs::read_to_string(&path) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        return KnowledgeMeta::default();
    };

    // Filter out pinned/recent entries whose files were deleted externally
    let base = get_notes_base_path();
    let orig_pinned_len = meta.pinned.len();
    let orig_recent_len = meta.recent.len();

    meta.pinned.retain(|p| base.join(p).exists());
    meta.recent.retain(|p| base.join(p).exists());

    // Persist cleaned meta if any entries were removed
    if meta.pinned.len() != orig_pinned_len || meta.recent.len() != orig_recent_len {
        if let Ok(content) = serde_json::to_string_pretty(&meta) {
            let _ = fs::write(&path, content);
        }
    }

    meta
}

#[tauri::command]
pub fn save_knowledge_meta(meta: KnowledgeMeta) -> AppResult<String> {
    let path = get_knowledge_meta_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(&meta)?;
    fs::write(&path, content)?;
    Ok("saved".to_string())
}
