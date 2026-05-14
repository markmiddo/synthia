//! Native Wayland-subsurface terminal renderer.
//!
//! See `docs/2026-05-13-native-terminal-renderer-design.md`.
//!
//! All rendering happens in-process. The per-keystroke path does not touch
//! Tauri IPC — Wayland keyboard events feed directly into the PTY writer,
//! and PTY output flows into a vte parser that mutates the grid, which is
//! then blitted to a softbuffer surface.

use std::collections::HashMap;
use std::sync::OnceLock;

use parking_lot::Mutex;
use uuid::Uuid;

pub mod commands;
pub mod grid;
pub mod input;
pub mod keyboard;
pub mod renderer;
pub mod subsurface;

/// Shared Wayland connection extracted from Tauri's main window.
/// Cached once at first attach; reused for every native session.
static WAYLAND_CONNECTION: OnceLock<wayland_client::Connection> = OnceLock::new();

/// Single global slot pointing at the currently-visible tab's PTY writer.
/// The keyboard event loop reads from this on every keystroke so we don't
/// have to spawn (and try to abort) a new wl_keyboard listener per tab —
/// stale listeners couldn't be reliably stopped (spawn_blocking can't
/// cancel mid-blocking-dispatch) and accumulated, causing every keystroke
/// to be duplicated N times.  One global listener + a swappable writer
/// slot eliminates the duplication entirely.
pub type WriterSlot =
    std::sync::Arc<Mutex<Option<std::sync::Arc<Mutex<Box<dyn std::io::Write + Send>>>>>>;
static ACTIVE_WRITER: OnceLock<WriterSlot> = OnceLock::new();
static KEYBOARD_TASK_SPAWNED: OnceLock<()> = OnceLock::new();

/// Information needed by the global pointer handler to translate Wayland
/// surface-local coordinates into a grid cell + apply selection updates.
#[derive(Clone)]
pub struct ActiveSurfaceInfo {
    pub grid: std::sync::Arc<Mutex<grid::Grid>>,
    pub cell_w: u32,
    pub cell_h: u32,
    pub padding_x: u32,
    pub padding_y: u32,
}

pub type ActiveSurfaceSlot = std::sync::Arc<Mutex<Option<ActiveSurfaceInfo>>>;
static ACTIVE_SURFACE: OnceLock<ActiveSurfaceSlot> = OnceLock::new();

pub fn active_surface_slot() -> ActiveSurfaceSlot {
    ACTIVE_SURFACE
        .get_or_init(|| std::sync::Arc::new(Mutex::new(None)))
        .clone()
}

pub fn set_active_surface(info: Option<ActiveSurfaceInfo>) {
    *active_surface_slot().lock() = info;
}

pub fn active_writer_slot() -> WriterSlot {
    ACTIVE_WRITER
        .get_or_init(|| std::sync::Arc::new(Mutex::new(None)))
        .clone()
}

pub fn set_active_writer(
    writer: Option<std::sync::Arc<Mutex<Box<dyn std::io::Write + Send>>>>,
) {
    *active_writer_slot().lock() = writer;
}

pub fn ensure_keyboard_task(conn: wayland_client::Connection, app: tauri::AppHandle) {
    if KEYBOARD_TASK_SPAWNED.set(()).is_err() {
        return; // already spawned
    }
    let slot = active_writer_slot();
    tokio::task::spawn_blocking(move || {
        if let Err(e) = keyboard::run_keyboard_loop(conn, slot, app) {
            eprintln!("[native-term] keyboard loop ended: {e}");
        }
    });
}

#[allow(dead_code)] // populated by attach (D Task 14), drained by detach (D Task 18)
pub struct NativeSession {
    pub session_id: Uuid,
    pub subsurface: std::sync::Arc<parking_lot::Mutex<subsurface::SubsurfaceHandle>>,
    /// Softbuffer context + surface bound to the child wl_surface (D Task 16).
    pub softbuffer:
        std::sync::Arc<parking_lot::Mutex<subsurface::SoftbufferState>>,
    pub renderer: std::sync::Arc<parking_lot::Mutex<renderer::Renderer>>,
    pub grid: std::sync::Arc<parking_lot::Mutex<grid::Grid>>,
    pub leased: crate::commands::terminal::LeasedPty,
    /// PTY writer shared with the input task — also stored here so the
    /// writer survives hide → show cycles (input_task is aborted on hide).
    pub writer:
        std::sync::Arc<parking_lot::Mutex<Box<dyn std::io::Write + Send>>>,
    pub reader_task: tokio::task::JoinHandle<()>,
    pub render_task: tokio::task::JoinHandle<()>,
    pub input_task: tokio::task::JoinHandle<()>,
}

/// State preserved across hide → show transitions.  The subsurface +
/// softbuffer + renderer + render_task + input_task are torn down on hide
/// (so the subsurface visually disappears via destroy + parent commit)
/// but `grid`, `leased`, and `reader_task` keep running so PTY output is
/// drained and the on-screen state is rebuilt instantly on the next show.
pub struct PersistentNativeState {
    pub session_id: Uuid,
    pub grid: std::sync::Arc<parking_lot::Mutex<grid::Grid>>,
    pub leased: crate::commands::terminal::LeasedPty,
    pub writer:
        std::sync::Arc<parking_lot::Mutex<Box<dyn std::io::Write + Send>>>,
    pub reader_task: tokio::task::JoinHandle<()>,
}

#[derive(Default)]
pub struct NativeTermRegistry {
    #[allow(dead_code)] // wired up in commands.rs (D Task 13)
    pub sessions: Mutex<HashMap<Uuid, NativeSession>>,
    /// Hidden persistent state keyed by session id.  Each terminal tab
    /// that isn't currently the visible one lives here — PTY + grid +
    /// reader_task keep running so background output is preserved.
    pub persistent: Mutex<HashMap<Uuid, PersistentNativeState>>,
    /// Insertion order of tabs (active + persistent) for stable tab strip
    /// rendering across show/hide cycles.
    pub tab_order: Mutex<Vec<Uuid>>,
    /// User-supplied tab titles.  Overrides the PTY meta title in
    /// `native_term_list_tabs` when present.  Cleared when the tab is
    /// closed.
    pub custom_titles: Mutex<HashMap<Uuid, String>>,
}

#[allow(dead_code)] // wired up in commands.rs (D Task 13)
pub fn wayland_connection() -> Option<&'static wayland_client::Connection> {
    WAYLAND_CONNECTION.get()
}

#[allow(dead_code)] // wired up in commands.rs (D Task 13)
pub fn init_wayland_connection(conn: wayland_client::Connection) {
    let _ = WAYLAND_CONNECTION.set(conn);
}
