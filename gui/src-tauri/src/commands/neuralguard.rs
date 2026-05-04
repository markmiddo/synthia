//! NeuralGuard / security Tauri commands.

use std::fs;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::error::{AppError, AppResult};
use crate::{egress, get_settings_file, get_synthia_root, security};

#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct PendingPrompt {
    id: String,
    ts: String,
    tool: String,
    raw: serde_json::Value,
    events: Vec<serde_json::Value>,
    agent_pid: Option<u32>,
    timeout_s: Option<u64>,
}

fn pending_prompts_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security/pending-prompts")
}

fn prompt_responses_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/security/prompt-responses")
}

fn synthia_python_path() -> PathBuf {
    let root = get_synthia_root();
    root.join("venv/bin/python")
}

fn security_gate_path() -> PathBuf {
    let root = get_synthia_root();
    root.join("src/synthia/hooks/security_gate.py")
}

#[tauri::command]
pub fn list_security_events(limit: Option<usize>) -> Vec<security::SecurityEvent> {
    security::read_events(limit.unwrap_or(200))
}

#[tauri::command]
pub fn clear_security_events() -> AppResult<()> {
    security::clear_events().map_err(|e| AppError::Io(e.to_string()))
}

#[tauri::command]
pub fn get_egress_enabled() -> bool {
    egress::is_enabled()
}

#[tauri::command]
pub fn set_egress_enabled(enabled: bool) -> AppResult<()> {
    let path = egress::runtime_state_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let mut state: serde_json::Value = fs::read_to_string(&path)
        .ok()
        .and_then(|c| serde_json::from_str(&c).ok())
        .unwrap_or_else(|| serde_json::json!({}));
    if let Some(obj) = state.as_object_mut() {
        obj.insert("egress_enabled".to_string(), serde_json::Value::Bool(enabled));
    }
    fs::write(&path, serde_json::to_string_pretty(&state)?)?;
    Ok(())
}

#[tauri::command]
pub fn list_pending_prompts() -> Vec<PendingPrompt> {
    let dir = pending_prompts_dir();
    if !dir.is_dir() {
        return Vec::new();
    }
    let mut out = Vec::new();
    if let Ok(entries) = fs::read_dir(&dir) {
        for entry in entries.flatten() {
            if entry.path().extension().and_then(|s| s.to_str()) != Some("json") {
                continue;
            }
            if let Ok(text) = fs::read_to_string(entry.path()) {
                if let Ok(p) = serde_json::from_str::<PendingPrompt>(&text) {
                    out.push(p);
                }
            }
        }
    }
    out.sort_by(|a, b| a.ts.cmp(&b.ts));
    out
}

#[tauri::command]
pub fn respond_to_prompt(id: String, decision: String) -> AppResult<()> {
    let allow = decision == "allow";
    let dir = prompt_responses_dir();
    fs::create_dir_all(&dir)?;
    let payload = serde_json::json!({
        "id": id,
        "decision": if allow { "allow" } else { "deny" },
        "ts": chrono::Utc::now().to_rfc3339(),
    });
    let file = dir.join(format!("{}.json", id));
    fs::write(&file, payload.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn neuralguard_status() -> serde_json::Value {
    let settings = get_settings_file();
    let installed = match fs::read_to_string(&settings) {
        Ok(c) => c.contains("security_gate.py"),
        Err(_) => false,
    };
    serde_json::json!({
        "installed": installed,
        "events_path": security::events_path_for_display(),
        "policy_path": security::policy_path_for_display(),
        "gate_script": security_gate_path().to_string_lossy(),
    })
}

#[tauri::command]
pub fn install_neuralguard_hooks() -> AppResult<String> {
    let settings = get_settings_file();
    fs::create_dir_all(
        settings
            .parent()
            .ok_or_else(|| AppError::Path("no parent".to_string()))?,
    )?;
    let mut root: serde_json::Value = if settings.exists() {
        let txt = fs::read_to_string(&settings)?;
        serde_json::from_str(&txt).unwrap_or_else(|_| serde_json::json!({}))
    } else {
        serde_json::json!({})
    };
    let py = synthia_python_path();
    let gate = security_gate_path();
    let cmd = format!("{} {}", py.to_string_lossy(), gate.to_string_lossy());

    let entry = serde_json::json!({
        "matcher": "",
        "hooks": [
            { "type": "command", "command": cmd, "timeout": 35 }
        ]
    });

    for event in ["PreToolUse", "PostToolUse"] {
        let hooks = root
            .as_object_mut()
            .unwrap()
            .entry("hooks")
            .or_insert_with(|| serde_json::json!({}))
            .as_object_mut()
            .ok_or_else(|| AppError::Other("hooks not object".to_string()))?;
        let arr = hooks
            .entry(event.to_string())
            .or_insert_with(|| serde_json::json!([]))
            .as_array_mut()
            .ok_or_else(|| AppError::Other("event not array".to_string()))?;
        // dedupe: drop existing security_gate entries first
        arr.retain(|item| {
            !item
                .get("hooks")
                .and_then(|h| h.as_array())
                .map(|hs| {
                    hs.iter().any(|h| {
                        h.get("command")
                            .and_then(|c| c.as_str())
                            .map(|s| s.contains("security_gate.py"))
                            .unwrap_or(false)
                    })
                })
                .unwrap_or(false)
        });
        arr.push(entry.clone());
    }

    let serialized = serde_json::to_string_pretty(&root)?;
    fs::write(&settings, serialized)?;
    security::ensure_dir().map_err(|e| AppError::Io(e.to_string()))?;
    Ok("NeuralGuard hooks installed".to_string())
}

#[tauri::command]
pub fn uninstall_neuralguard_hooks() -> AppResult<String> {
    let settings = get_settings_file();
    if !settings.exists() {
        return Ok("Nothing to remove".to_string());
    }
    let txt = fs::read_to_string(&settings)?;
    let mut root: serde_json::Value = serde_json::from_str(&txt)?;
    if let Some(hooks) = root.get_mut("hooks").and_then(|v| v.as_object_mut()) {
        for event in ["PreToolUse", "PostToolUse"] {
            if let Some(arr) = hooks.get_mut(event).and_then(|v| v.as_array_mut()) {
                arr.retain(|item| {
                    !item
                        .get("hooks")
                        .and_then(|h| h.as_array())
                        .map(|hs| {
                            hs.iter().any(|h| {
                                h.get("command")
                                    .and_then(|c| c.as_str())
                                    .map(|s| s.contains("security_gate.py"))
                                    .unwrap_or(false)
                            })
                        })
                        .unwrap_or(false)
                });
            }
        }
    }
    let serialized = serde_json::to_string_pretty(&root)?;
    fs::write(&settings, serialized)?;
    Ok("NeuralGuard hooks removed".to_string())
}
