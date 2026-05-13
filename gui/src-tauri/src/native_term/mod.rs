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
    /// Hidden persistent state.  When `Some`, contains the grid + PTY of
    /// a terminal that's been hidden but kept alive for a future `show`.
    pub persistent: Mutex<Option<PersistentNativeState>>,
}

#[allow(dead_code)] // wired up in commands.rs (D Task 13)
pub fn wayland_connection() -> Option<&'static wayland_client::Connection> {
    WAYLAND_CONNECTION.get()
}

#[allow(dead_code)] // wired up in commands.rs (D Task 13)
pub fn init_wayland_connection(conn: wayland_client::Connection) {
    let _ = WAYLAND_CONNECTION.set(conn);
}
