use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};
use std::process::{Command, Child};
use std::sync::Mutex;
use std::fs;
use std::path::PathBuf;
use std::thread;
use std::time::Duration;
use serde::Deserialize;

fn load_icon_from_path(path: &PathBuf) -> Option<Image<'static>> {
    let img = image::open(path).ok()?.to_rgba8();
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

    // Start the telegram bot with CUDA disabled
    Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args(["/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py"])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .env("CUDA_VISIBLE_DEVICES", "")
        .spawn()
        .map_err(|e| format!("Failed to start remote mode: {}", e))?;

    // Send notification to Telegram
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
    // Send notification before stopping
    let _ = Command::new("/home/markmiddo/dev/misc/synthia/venv/bin/python")
        .args([
            "/home/markmiddo/dev/misc/synthia/src/synthia/remote/telegram_bot.py",
            "--notify",
            "🔴 *Remote Mode DISABLED*\n\nTelegram bot stopped."
        ])
        .current_dir("/home/markmiddo/dev/misc/synthia")
        .output();

    // Give notification time to send
    std::thread::sleep(std::time::Duration::from_millis(500));

    let _ = Command::new("pkill")
        .args(["-f", "telegram_bot.py"])
        .output();

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

pub fn run() {
    if !acquire_lock() {
        eprintln!("Synthia GUI is already running");
        std::process::exit(0);
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Create tray menu
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let show = MenuItem::with_id(app, "show", "Show Settings", true, None::<&str>)?;

            let menu = Menu::with_items(app, &[
                &show,
                &quit,
            ])?;

            // Create tray icon with ID so we can update it later
            let tray = TrayIconBuilder::with_id("main-tray")
                .icon(app.default_window_icon().unwrap().clone())
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
                let mut last_recording = false;

                // Load icons
                let normal_icon = load_icon_from_path(&normal_icon_path);
                let recording_icon = load_icon_from_path(&recording_icon_path);

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
            get_remote_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
