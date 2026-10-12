use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Emitter, Manager, WindowEvent,
};
use std::process::Command;
use std::fs;
use std::path::PathBuf;
use serde::Deserialize;

mod error;
mod paths;
mod state;
mod yaml_writer;
mod commands;

/// Get the Synthia project root directory.
/// Resolves from the executable path (gui/src-tauri/target/release/synthia-gui)
/// or falls back to finding run.sh relative to the binary.
pub(crate) fn get_synthia_root() -> PathBuf {
    // Try to find the root by looking for run.sh relative to the executable
    if let Ok(exe) = std::env::current_exe() {
        // The binary is at gui/src-tauri/target/release/synthia-gui
        // So root is 4 levels up: release -> target -> src-tauri -> gui -> root
        let mut path = exe.clone();
        for _ in 0..5 {
            path = path.parent().unwrap_or(&path).to_path_buf();
            if path.join("run.sh").exists() {
                return path;
            }
        }
    }
    // Fallback: check if SYNTHIA_ROOT env var is set
    if let Ok(root) = std::env::var("SYNTHIA_ROOT") {
        return PathBuf::from(root);
    }
    // Fallback: check the known development path
    let dev_path = PathBuf::from(
        std::env::var("HOME").unwrap_or_default()
    ).join("dev/misc/synthia");
    if dev_path.join("run.sh").exists() {
        return dev_path;
    }
    // Last resort: current directory
    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// Get the XDG runtime directory for temp files (not world-readable /tmp).
pub(crate) fn get_runtime_dir() -> PathBuf {
    PathBuf::from(std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string()))
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

/// The voice process's state file (`synthia-state.json`), forwarded to the HUD as the
/// `synthia-state` event so the orb can show "listening".
#[derive(Deserialize, serde::Serialize, Debug, Default, Clone, PartialEq)]
struct SynthiaState {
    status: String,
    recording: bool,
    /// "murmur" when Murmur hears the assistant key (older voice apps omit it).
    #[serde(default)]
    stt_source: Option<String>,
    /// Murmur's assistant key label: absent/null = unknown, "" = no key set in Murmur.
    #[serde(default)]
    talk_key: Option<String>,
}

#[tauri::command]
fn get_synthia_state() -> SynthiaState {
    read_synthia_state()
}

pub(crate) fn get_lock_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-gui.lock")
}

pub(crate) fn get_state_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-state.json")
}

pub(crate) fn get_history_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-history.json")
}

pub(crate) fn get_claude_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".claude")
}

pub(crate) fn get_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

pub(crate) fn get_runtime_state_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/runtime.json")
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

/// Spawn a notify-based watcher on the synthia state file's parent dir.
/// Updates the tray icon whenever the state file changes. Returns the watcher
/// handle, which the caller MUST keep alive (dropping it stops watching).
fn spawn_state_watcher(
    app_handle: tauri::AppHandle,
    normal_icon: Option<Image<'static>>,
    recording_icon: Option<Image<'static>>,
) -> Option<notify::RecommendedWatcher> {
    use notify::{Event, EventKind, RecursiveMode, Watcher};

    let state_file = get_state_file();
    let parent = state_file.parent()?.to_path_buf();
    let target = state_file.clone();
    let last_state = std::sync::Arc::new(std::sync::Mutex::new(SynthiaState::default()));

    let mut watcher = notify::recommended_watcher(move |res: notify::Result<Event>| {
        let Ok(event) = res else { return };
        if !matches!(
            event.kind,
            EventKind::Modify(_) | EventKind::Create(_) | EventKind::Remove(_)
        ) {
            return;
        }
        if !event.paths.iter().any(|p| p == &target) {
            return;
        }
        let state = read_synthia_state();
        let mut last = match last_state.lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        if state == *last {
            return;
        }
        let recording_changed = state.recording != last.recording;
        *last = state.clone();
        let _ = app_handle.emit("synthia-state", &state);
        if !recording_changed {
            return;
        }
        if let Some(tray) = app_handle.tray_by_id("main-tray") {
            if state.recording {
                if let Some(ref icon) = recording_icon {
                    let _ = tray.set_icon(Some(icon.clone()));
                    let _ = tray.set_tooltip(Some("Synthia - Recording..."));
                }
            } else if let Some(ref icon) = normal_icon {
                let _ = tray.set_icon(Some(icon.clone()));
                let _ = tray.set_tooltip(Some("Synthia - Voice Assistant"));
            }
        }
    })
    .ok()?;

    watcher.watch(&parent, RecursiveMode::NonRecursive).ok()?;
    Some(watcher)
}

pub fn run() {
    if !acquire_lock() {
        eprintln!("Synthia GUI is already running");
        std::process::exit(0);
    }

    tauri::Builder::default()
        .manage(state::AppState::default())
        .setup(|app| {
            // Clean up any stale remote mode state from previous sessions
            let _ = fs::remove_file(get_runtime_dir().join("synthia-remote-mode"));
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
            let _tray = TrayIconBuilder::with_id("main-tray")
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
            let dev_icons_dir = get_synthia_root().join("gui/src-tauri/icons");

            let _normal_icon_path = if resource_dir.join("icons/tray-icon.png").exists() {
                resource_dir.join("icons/tray-icon.png")
            } else {
                dev_icons_dir.join("tray-icon.png")
            };

            let _recording_icon_path = if resource_dir.join("icons/tray-recording.png").exists() {
                resource_dir.join("icons/tray-recording.png")
            } else {
                dev_icons_dir.join("tray-recording.png")
            };

            // Start state watcher (notify-based, event-driven)
            let app_handle = app.handle().clone();
            let normal_icon = load_embedded_icon(TRAY_ICON_PNG);
            let recording_icon = load_embedded_icon(TRAY_RECORDING_PNG);

            // Set initial icon immediately
            if let Some(tray) = app_handle.tray_by_id("main-tray") {
                if let Some(ref icon) = normal_icon {
                    let _ = tray.set_icon(Some(icon.clone()));
                }
            }

            if let Some(watcher) = spawn_state_watcher(app_handle, normal_icon, recording_icon) {
                app.state::<state::AppState>().watchers.lock().push(Box::new(watcher));
            }

            commands::fleet::spawn_emitter(app.handle().clone());

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::lifecycle::get_status,
            commands::lifecycle::start_synthia,
            commands::lifecycle::stop_synthia,
            commands::lifecycle::set_mode,
            commands::lifecycle::get_voice_muted,
            commands::lifecycle::set_voice_muted,
            commands::overlay::show_overlay,
            commands::overlay::hide_overlay,
            commands::overlay::set_overlay_recording,
            commands::remote::start_remote_mode,
            commands::remote::stop_remote_mode,
            commands::remote::get_remote_status,
            commands::history::get_history,
            commands::history::clear_history,
            commands::history::resend_to_assistant,
            commands::hotkeys::get_hotkeys,
            commands::hotkeys::save_hotkeys,
            commands::hotkeys::get_word_replacements,
            commands::hotkeys::save_word_replacements,
            commands::usage::get_usage_stats,
            get_synthia_state,
            commands::desk::get_desk_token,
            commands::fleet::fleet_snapshot,
            commands::fleet::fleet_focus,
            commands::fleet::fleet_day,
            commands::squads::squads_list,
            commands::squads::squad_role_save,
            commands::squads::squad_open_job,
            commands::squads::squad_job_detail,
            commands::squads::squad_open_file,
            commands::squads::squad_stop_job,
            commands::squads::squad_start_job
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

