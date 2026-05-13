//! Wayland subsurface lifecycle.
//!
//! Extracts the parent `wl_surface` from Tauri's main window via
//! `raw-window-handle`, creates a child surface + subsurface, and exposes
//! a handle for positioning, resizing, and destruction.

use std::ptr::NonNull;

use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use wayland_client::Connection;

use crate::error::{AppError, AppResult};

#[allow(dead_code)] // populated in D Task 9
pub struct SubsurfaceHandle {
    pub child_surface: wayland_client::protocol::wl_surface::WlSurface,
    pub subsurface: wayland_client::protocol::wl_subsurface::WlSubsurface,
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
}

/// Extract the parent wl_surface pointer from a Tauri window.
/// Returns an error if the window isn't running on native Wayland.
#[allow(dead_code)] // wired up in D Task 13
pub fn parent_surface_from_tauri(
    window: &tauri::WebviewWindow,
) -> AppResult<NonNull<std::ffi::c_void>> {
    let handle = window
        .window_handle()
        .map_err(|e| AppError::Terminal(format!("window_handle: {e}")))?;
    match handle.as_raw() {
        RawWindowHandle::Wayland(h) => Ok(h.surface),
        _ => Err(AppError::Terminal(
            "native renderer requires native Wayland".into(),
        )),
    }
}

/// Create a wl_subsurface as a child of `parent_surface_ptr`. Real implementation
/// lands in D Task 9; this stub returns an error so dependent code compiles.
#[allow(dead_code)] // wired up in D Task 13 (real body in D Task 9)
pub fn create_subsurface(
    _conn: &Connection,
    _parent_surface_ptr: NonNull<std::ffi::c_void>,
    _x: i32,
    _y: i32,
    _width: u32,
    _height: u32,
) -> AppResult<SubsurfaceHandle> {
    Err(AppError::Terminal(
        "subsurface creation not yet implemented (D Task 9)".into(),
    ))
}

#[cfg(test)]
mod tests {
    #[test]
    fn module_compiles() {
        // Sanity: module compiles. Real subsurface tests need a live Wayland compositor
        // and are part of the D Task 21 manual smoke checklist.
    }
}
