use tauri::{
    image::Image,
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, WindowEvent,
};
use std::process::Command;
use std::fs;
use std::path::PathBuf;
use serde::Deserialize;

mod security;
mod egress;
mod error;
mod paths;
mod state;
mod config;
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

#[allow(dead_code)]
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

#[derive(Deserialize, Debug, Default)]
struct SynthiaState {
    #[allow(dead_code)]
    status: String,
    recording: bool,
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

pub(crate) fn get_clipboard_file() -> PathBuf {
    let runtime_dir = std::env::var("XDG_RUNTIME_DIR")
        .unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(runtime_dir).join("synthia-clipboard.json")
}

pub(crate) fn get_inbox_file() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".local/share/synthia/inbox/inbox.json")
}

pub(crate) fn get_worktrees_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/worktrees.yaml")
}

pub(crate) fn get_claude_dir() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".claude")
}

pub(crate) fn get_memory_dir() -> PathBuf {
    get_claude_dir().join("memory")
}

pub(crate) fn get_agents_dir() -> PathBuf {
    get_claude_dir().join("agents")
}

pub(crate) fn get_commands_dir() -> PathBuf {
    get_claude_dir().join("commands")
}

pub(crate) fn get_skills_dir() -> PathBuf {
    get_claude_dir().join("skills")
}

pub(crate) fn get_settings_file() -> PathBuf {
    get_claude_dir().join("settings.json")
}

pub(crate) fn get_plugins_file() -> PathBuf {
    get_claude_dir().join("plugins").join("installed_plugins.json")
}

pub(crate) fn get_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

pub(crate) fn get_runtime_state_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(home).join(".config/synthia/runtime.json")
}

pub(crate) fn parse_frontmatter(content: &str) -> (std::collections::HashMap<String, String>, String) {
    if !content.starts_with("---") {
        return (std::collections::HashMap::new(), content.to_string());
    }

    let parts: Vec<&str> = content.splitn(3, "---").collect();
    if parts.len() < 3 {
        return (std::collections::HashMap::new(), content.to_string());
    }

    let mut frontmatter = std::collections::HashMap::new();
    for line in parts[1].trim().lines() {
        if let Some(colon_pos) = line.find(':') {
            let key = line[..colon_pos].trim().to_string();
            let value = line[colon_pos + 1..].trim().to_string();
            frontmatter.insert(key, value);
        }
    }

    (frontmatter, parts[2].to_string())
}

pub(crate) fn is_wayland_env() -> bool {
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
    let last_recording = std::sync::Arc::new(std::sync::Mutex::new(false));

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
        let mut last = match last_recording.lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        if state.recording == *last {
            return;
        }
        *last = state.recording;
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

    egress::spawn_watcher();

    tauri::Builder::default()
        .manage(state::AppState::default())
        .plugin(tauri_plugin_opener::init())
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
                if let Ok(mut guard) = app.state::<state::AppState>().watchers.lock() {
                    guard.push(Box::new(watcher));
                }
            }

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::lifecycle::get_status,
            commands::lifecycle::start_synthia,
            commands::lifecycle::stop_synthia,
            commands::lifecycle::set_mode,
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
            commands::clipboard::get_clipboard_history,
            commands::clipboard::copy_from_clipboard_history,
            commands::inbox::get_inbox_items,
            commands::inbox::open_inbox_item,
            commands::inbox::delete_inbox_item,
            commands::inbox::clear_inbox,
            commands::worktrees::get_worktrees,
            commands::worktrees::resume_session,
            commands::worktrees::set_worktree_status,
            commands::memory::get_memory_stats,
            commands::memory::get_memory_entries,
            commands::memory::search_memory,
            commands::memory::update_memory_entry,
            commands::memory::delete_memory_entry,
            commands::claude_config::get_synthia_config,
            commands::claude_config::save_synthia_config,
            commands::worktrees::get_worktree_repos,
            commands::worktrees::save_worktree_repos,
            commands::agents::list_agents,
            commands::agents::save_agent,
            commands::agents::delete_agent,
            commands::agents::list_commands,
            commands::agents::save_command,
            commands::agents::delete_command,
            commands::agents::list_skills,
            commands::agents::save_skill,
            commands::agents::delete_skill,
            commands::lifecycle::get_voice_muted,
            commands::lifecycle::set_voice_muted,
            commands::neuralguard::list_security_events,
            commands::neuralguard::clear_security_events,
            commands::agents::scan_all_sessions,
            commands::neuralguard::list_pending_prompts,
            commands::neuralguard::respond_to_prompt,
            commands::neuralguard::neuralguard_status,
            commands::neuralguard::install_neuralguard_hooks,
            commands::neuralguard::uninstall_neuralguard_hooks,
            commands::neuralguard::get_egress_enabled,
            commands::neuralguard::set_egress_enabled,
            commands::neuralguard::add_to_allowlist,
            commands::agents::list_hooks,
            commands::agents::list_plugins,
            commands::agents::toggle_plugin,
            commands::claude_config::get_knowledge_meta,
            commands::claude_config::save_knowledge_meta,
            commands::notes::list_notes,
            commands::notes::read_note,
            commands::notes::get_note_preview,
            commands::notes::get_note_modified,
            commands::notes::save_note,
            commands::notes::rename_note,
            commands::notes::move_note,
            commands::notes::create_folder,
            commands::notes::delete_note,
            commands::usage::get_usage_stats,
            commands::notes::get_pinned_note,
            commands::notes::save_pinned_note,
            commands::github::get_github_config,
            commands::github::save_github_config,
            commands::github::get_github_issues,
            commands::notes::get_notes_base_path_cmd,
            commands::agents::list_active_agents,
            commands::agents::kill_agent
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

