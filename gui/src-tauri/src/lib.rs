use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};
use std::process::{Command, Child, Stdio};
use std::sync::Mutex;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;
use serde::{Deserialize, Serialize};

fn load_icon_from_path(path: &PathBuf) -> Option<Image<'static>> {
    let img = image::open(path).ok()?.to_rgba8();
    let (width, height) = img.dimensions();
    let rgba = img.into_raw();
    Some(Image::new_owned(rgba, width, height))
}

// Embed icons directly in binary for better compatibility
static TRAY_ICON_PNG: &[u8] = include_bytes!("../icons/tray-icon.png");
static TRAY_RECORDING_PNG: &[u8] = include_bytes!("../icons/tray-recording.png");

fn load_embedded_icon(data: &'static [u8]) -> Option<Image<'static>> {
    let img = image::load_from_memory(data).ok()?.to_rgba8();
    let (width, height) = img.dimensions();
    let rgba = img.into_raw();
    Some(Image::new_owned(rgba, width, height))
}

static SYNTHIA_PROCESS: Mutex<Option<Child>> = Mutex::new(None);

#[derive(Deserialize, Debug, Default)]
struct SynthiaState {
    status: String,
    recording: bool,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct HistoryEntry {
    id: u32,
    text: String,
    mode: String,
    timestamp: String,
    response: Option<String>,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct WordReplacement {
    from: String,
    to: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct ClipboardEntry {
    id: u64,
    content: String,
    timestamp: String,
    hash: String,
}

#[derive(Deserialize, Serialize, Debug, Clone)]
struct InboxItem {
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

fn get_lock_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-gui.lock")
}

fn get_state_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-state.json")
}

fn get_history_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-history.json")
}

fn get_clipboard_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-clipboard.json")
}

fn get_inbox_file() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".local/share/synthia/inbox/inbox.json")
}

fn is_wayland_env() -> bool {
    std::env::var("WAYLAND_DISPLAY").is_ok()
}

fn acquire_lock() -> bool {
    let lock_file = get_lock_file();

    if lock_file.exists() {
        if let Ok(pid_str) = fs::read_to_string(&lock_file) {
            if let Ok(pid) = pid_str.trim().parse::<i32>() {
                let check = Command::new("kill")
                    .args(["-0", &pid.to_string()])
                    .output();
                if check.map(|o| o.status.success()).unwrap_or(false) {
                    return false;
                }
            }
        }
    }

    let pid = std::process::id();
    fs::write(&lock_file, pid.to_string()).ok();
    true
}

fn release_lock() {
    let lock_file = get_lock_file();
    fs::remove_file(lock_file).ok();
}

fn read_synthia_state() -> SynthiaState {
    let state_file = get_state_file();
    if let Ok(content) = fs::read_to_string(&state_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        SynthiaState::default()
    }
}

#[tauri::command]
fn get_status() -> String {
    let output = Command::new("pgrep")
        .args(["-f", "synthia.main"])
        .output();

    match output {
        Ok(out) if out.status.success() => "running".to_string(),
        _ => "stopped".to_string(),
    }
}

#[tauri::command]
fn start_synthia() -> Result<String, String> {
    let mut proc = SYNTHIA_PROCESS.lock().unwrap();
    if proc.is_some() {
        return Ok("Already running".to_string());
    }

    let child = Command::new("/home/markmiddo/dev/misc/synthia/run.sh")
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .spawn()
        .map_err(|e| format!("Failed to start: {}", e))?;

    *proc = Some(child);
    Ok("Synthia started".to_string())
}

#[tauri::command]
fn stop_synthia() -> Result<String, String> {
    let _ = Command::new("pkill")
        .args(["-f", "synthia.main"])
        .output();

    let mut proc = SYNTHIA_PROCESS.lock().unwrap();
    *proc = None;

    Ok("Synthia stopped".to_string())
}

#[tauri::command]
fn set_mode(mode: &str) -> Result<String, String> {
    Ok(format!("Mode set to: {}", mode))
}

#[tauri::command]
fn start_remote_mode() -> Result<String, String> {
    // Check if already running
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    if check.map(|o| o.status.success()).unwrap_or(false) {
        return Ok("Remote mode already running".to_string());
    }

    // Create the remote mode flag file with chat ID (enables response forwarding to Telegram)
    // Chat ID is needed by send_telegram.py to know where to send messages
    let _ = fs::write("/tmp/synthia-remote-mode", "537808338");

    // Start the telegram bot with CUDA disabled
    Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args(["/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py"])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .env("CUDA_VISIBLE_DEVICES", "")
        .spawn()
        .map_err(|e| format!("Failed to start remote mode: {}", e))?;

    // Send notification in background (don't block UI)
    let _ = Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args([
            "/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py",
            "--notify",
            "🟢 *Remote Mode ENABLED*\n\nYou can now control Claude Code via Telegram."
        ])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .spawn();

    Ok("Remote mode started".to_string())
}

#[tauri::command]
fn stop_remote_mode() -> Result<String, String> {
    // Remove the remote mode flag file (stops response forwarding to Telegram)
    let _ = fs::remove_file("/tmp/synthia-remote-mode");

    // Kill the bot immediately for instant UI response
    let _ = Command::new("pkill")
        .args(["-f", "telegram_bot.py"])
        .output();

    // Send notification in background (after bot is killed, uses --notify which is standalone)
    let _ = Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args([
            "/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py",
            "--notify",
            "🔴 *Remote Mode DISABLED*\n\nTelegram bot stopped."
        ])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .spawn();

    Ok("Remote mode stopped".to_string())
}

#[tauri::command]
fn get_remote_status() -> bool {
    let check = Command::new("pgrep")
        .args(["-f", "telegram_bot.py"])
        .output();

    check.map(|o| o.status.success()).unwrap_or(false)
}

#[tauri::command]
fn show_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.show().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn hide_overlay(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.hide().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn set_overlay_recording(app: tauri::AppHandle, active: bool) -> Result<(), String> {
    if let Some(window) = app.get_webview_window("overlay") {
        window.emit("recording", active).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn get_history() -> Vec<HistoryEntry> {
    let history_file = get_history_file();
    if let Ok(content) = fs::read_to_string(&history_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
fn clear_history() -> Result<String, String> {
    let history_file = get_history_file();
    fs::write(&history_file, "[]").map_err(|e| e.to_string())?;
    Ok("History cleared".to_string())
}

fn get_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/home/markmiddo".to_string());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

#[tauri::command]
fn get_hotkeys() -> Result<(String, String), String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

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
fn save_hotkeys(dictation_key: String, assistant_key: String) -> Result<String, String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

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
        .map_err(|e| format!("Failed to write config: {}", e))?;

    // Signal Synthia to reload config by touching a signal file
    // Synthia watches for this file and updates hotkeys dynamically (no restart needed!)
    let signal_file = PathBuf::from("/tmp/synthia-reload-config");
    fs::write(&signal_file, "reload").ok();

    Ok("Hotkeys saved".to_string())
}

#[tauri::command]
fn get_word_replacements() -> Vec<WordReplacement> {
    let config_path = get_config_path();
    let content = match fs::read_to_string(&config_path) {
        Ok(c) => c,
        Err(_) => return Vec::new(),
    };

    let mut replacements = Vec::new();
    let mut in_word_replacements = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("word_replacements:") {
            in_word_replacements = true;
            continue;
        }

        // Check if we've left the word_replacements section
        if in_word_replacements && !trimmed.is_empty() && !trimmed.starts_with('#') {
            if !line.starts_with(' ') && !line.starts_with('\t') {
                // New top-level key, we're done
                break;
            }

            // Parse "from: to" format
            if let Some(colon_pos) = trimmed.find(':') {
                let from = trimmed[..colon_pos].trim().to_string();
                let to = trimmed[colon_pos + 1..].trim().to_string();
                if !from.is_empty() && !to.is_empty() {
                    replacements.push(WordReplacement { from, to });
                }
            }
        }
    }

    replacements
}

#[tauri::command]
fn save_word_replacements(replacements: Vec<WordReplacement>) -> Result<String, String> {
    let config_path = get_config_path();
    let content = fs::read_to_string(&config_path)
        .map_err(|e| format!("Failed to read config: {}", e))?;

    let mut new_content = String::new();
    let mut in_word_replacements = false;
    let mut wrote_replacements = false;

    for line in content.lines() {
        let trimmed = line.trim();

        if trimmed.starts_with("word_replacements:") {
            in_word_replacements = true;
            new_content.push_str("word_replacements:\n");
            // Write all replacements
            for r in &replacements {
                new_content.push_str(&format!("  {}: {}\n", r.from, r.to));
            }
            wrote_replacements = true;
            continue;
        }

        if in_word_replacements {
            // Skip old replacement lines (indented lines)
            if line.starts_with(' ') || line.starts_with('\t') {
                if !trimmed.is_empty() && !trimmed.starts_with('#') {
                    continue; // Skip old entries
                }
            } else if !trimmed.is_empty() {
                // New top-level key, we're done with word_replacements
                in_word_replacements = false;
            }
        }

        if !in_word_replacements {
            new_content.push_str(line);
            new_content.push('\n');
        }
    }

    // If word_replacements section didn't exist, add it
    if !wrote_replacements {
        new_content.push_str("\n# Word replacements for dictation\nword_replacements:\n");
        for r in &replacements {
            new_content.push_str(&format!("  {}: {}\n", r.from, r.to));
        }
    }

    fs::write(&config_path, new_content.trim_end())
        .map_err(|e| format!("Failed to write config: {}", e))?;

    Ok("Word replacements saved".to_string())
}

#[tauri::command]
fn get_clipboard_history() -> Vec<ClipboardEntry> {
    let clipboard_file = get_clipboard_file();
    if let Ok(content) = fs::read_to_string(&clipboard_file) {
        serde_json::from_str(&content).unwrap_or_default()
    } else {
        Vec::new()
    }
}

#[tauri::command]
fn copy_from_clipboard_history(content: String) -> Result<String, String> {
    if is_wayland_env() {
        let mut child = Command::new("wl-copy")
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn wl-copy: {}", e))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(content.as_bytes())
                .map_err(|e| format!("Failed to write to wl-copy: {}", e))?;
        }

        child.wait().map_err(|e| format!("wl-copy failed: {}", e))?;
    } else {
        let mut child = Command::new("xclip")
            .args(["-selection", "clipboard"])
            .stdin(Stdio::piped())
            .spawn()
            .map_err(|e| format!("Failed to spawn xclip: {}", e))?;

        if let Some(mut stdin) = child.stdin.take() {
            stdin.write_all(content.as_bytes())
                .map_err(|e| format!("Failed to write to xclip: {}", e))?;
        }

        child.wait().map_err(|e| format!("xclip failed: {}", e))?;
    }

    Ok("Copied to clipboard".to_string())
}

#[derive(Deserialize, Serialize, Debug)]
struct InboxData {
    items: Vec<InboxItem>,
}

#[tauri::command]
fn get_inbox_items() -> Vec<InboxItem> {
    let inbox_file = get_inbox_file();
    if let Ok(content) = fs::read_to_string(&inbox_file) {
        if let Ok(data) = serde_json::from_str::<InboxData>(&content) {
            return data.items;
        }
    }
    Vec::new()
}

#[tauri::command]
fn open_inbox_item(id: String, item_type: String, path: Option<String>, url: Option<String>) -> Result<String, String> {
    // Open the item with xdg-open
    let target = if item_type == "url" {
        url.ok_or("No URL provided")?
    } else {
        path.ok_or("No path provided")?
    };

    Command::new("xdg-open")
        .arg(&target)
        .spawn()
        .map_err(|e| format!("Failed to open: {}", e))?;

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
fn delete_inbox_item(id: String) -> Result<String, String> {
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
    Err("Failed to delete item".to_string())
}

#[tauri::command]
fn clear_inbox() -> Result<String, String> {
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

#[tauri::command]
fn resend_to_assistant(text: String) -> Result<String, String> {
    // Use xdotool to type the text into Claude Code terminal
    // First, we'll write to a temp file that the stop hook can check
    let prompt_file = PathBuf::from("/tmp/synthia-resend-prompt");
    fs::write(&prompt_file, &text).map_err(|e| e.to_string())?;

    // Use xdotool to focus Claude Code window and type the text
    let _ = Command::new("xdotool")
        .args(["search", "--name", "Claude Code", "windowactivate", "--sync"])
        .output();

    // Type the text
    Command::new("xdotool")
        .args(["type", "--clearmodifiers", &text])
        .output()
        .map_err(|e| format!("Failed to type text: {}", e))?;

    // Press Enter to submit
    Command::new("xdotool")
        .args(["key", "Return"])
        .output()
        .map_err(|e| format!("Failed to press Enter: {}", e))?;

    // Clean up
    let _ = fs::remove_file(&prompt_file);

    Ok("Sent to assistant".to_string())
}

pub fn run() {
    if !acquire_lock() {
        eprintln!("Synthia GUI is already running");
        std::process::exit(0);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Clean up any stale remote mode state from previous sessions
            let _ = fs::remove_file("/tmp/synthia-remote-mode");
            let _ = Command::new("pkill")
                .args(["-f", "telegram_bot.py"])
                .output();

            // Create tray menu
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show Settings", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[
                &show,
                &quit,
            ])?;

            // Load the tray icon immediately for COSMIC/StatusNotifierItem compatibility
            let initial_icon = load_embedded_icon(TRAY_ICON_PNG)
                .unwrap_or_else(|| app.default_window_icon().unwrap().clone());

            // Create tray icon with ID so we can update it later
            let tray = TrayIconBuilder::with_id("main-tray")
                .icon(initial_icon)
                .menu(&menu)
                .tooltip("Synthia - Voice Assistant")
                .on_menu_event(|app, event| {
                    match event.id.as_ref() {
                        "quit" => {
                            release_lock();
                            app.exit(0);
                        }
                        "show" => {
                            if let Some(window) = app.get_webview_window("main") {
                                let _ = window.show();
                                let _ = window.set_focus();
                            }
                        }
                        _ => {}
                    }
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(window) = app.get_webview_window("main") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                })
                .build(app)?;

            // Handle window close - hide instead of quit
            if let Some(window) = app.get_webview_window("main") {
                let window_clone = window.clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        let _ = window_clone.hide();
                    }
                });
            }

            // Load tray icons - try bundled resources first, then fall back to dev path
            let resource_dir = app.path().resource_dir().unwrap_or_default();
            let dev_icons_dir = PathBuf::from("/home/markmiddo/dev/misc/synthia/gui/src-tauri/icons");

            let normal_icon_path = if resource_dir.join("icons/tray-icon.png").exists() {
                resource_dir.join("icons/tray-icon.png")
            } else {
                dev_icons_dir.join("tray-icon.png")
            };

            let recording_icon_path = if resource_dir.join("icons/tray-recording.png").exists() {
                resource_dir.join("icons/tray-recording.png")
            } else {
                dev_icons_dir.join("tray-recording.png")
            };

            // Start state watcher thread for tray icon
            let app_handle = app.handle().clone();
            thread::spawn(move || {
                // Load embedded icons (more reliable across desktop environments)
                let normal_icon = load_embedded_icon(TRAY_ICON_PNG);
                let recording_icon = load_embedded_icon(TRAY_RECORDING_PNG);

                // Set initial icon immediately
                if let Some(tray) = app_handle.tray_by_id("main-tray") {
                    if let Some(ref icon) = normal_icon {
                        let _ = tray.set_icon(Some(icon.clone()));
                    }
                }

                let mut last_recording = false;

                loop {
                    let state = read_synthia_state();

                    // Update tray icon when state changes
                    if state.recording != last_recording {
                        last_recording = state.recording;

                        if let Some(tray) = app_handle.tray_by_id("main-tray") {
                            if state.recording {
                                if let Some(ref icon) = recording_icon {
                                    let _ = tray.set_icon(Some(icon.clone()));
                                    let _ = tray.set_tooltip(Some("Synthia - Recording..."));
                                }
                            } else {
                                if let Some(ref icon) = normal_icon {
                                    let _ = tray.set_icon(Some(icon.clone()));
                                    let _ = tray.set_tooltip(Some("Synthia - Voice Assistant"));
                                }
                            }
                        }
                    }

                    thread::sleep(Duration::from_millis(50));
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_status,
            start_synthia,
            stop_synthia,
            set_mode,
            show_overlay,
            hide_overlay,
            set_overlay_recording,
            start_remote_mode,
            stop_remote_mode,
            get_remote_status,
            get_history,
            clear_history,
            resend_to_assistant,
            get_hotkeys,
            save_hotkeys,
            get_word_replacements,
            save_word_replacements,
            get_clipboard_history,
            copy_from_clipboard_history,
            get_inbox_items,
            open_inbox_item,
            delete_inbox_item,
            clear_inbox
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
