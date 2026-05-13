//! Wayland subsurface lifecycle.
//!
//! Extracts the parent `wl_surface` from Tauri's main window via
//! `raw-window-handle`, creates a child surface + subsurface, and exposes
//! a handle for positioning, resizing, and destruction.

use std::ptr::NonNull;

use raw_window_handle::{HasWindowHandle, RawWindowHandle};
use wayland_client::{
    globals::{registry_queue_init, GlobalListContents},
    protocol::{
        wl_compositor::WlCompositor,
        wl_registry::WlRegistry,
        wl_subcompositor::WlSubcompositor,
        wl_subsurface::WlSubsurface,
        wl_surface::WlSurface,
    },
    Connection, Dispatch, Proxy, QueueHandle,
};

use crate::error::{AppError, AppResult};

#[allow(dead_code)] // populated in D Task 9
pub struct SubsurfaceHandle {
    pub child_surface: WlSurface,
    pub subsurface: WlSubsurface,
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
}

// ---------------------------------------------------------------------------
// Minimal Dispatch implementations required by registry_queue_init
// ---------------------------------------------------------------------------

struct AppData;

impl Dispatch<WlRegistry, GlobalListContents> for AppData {
    fn event(
        _state: &mut Self,
        _proxy: &WlRegistry,
        _event: <WlRegistry as Proxy>::Event,
        _data: &GlobalListContents,
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<WlCompositor, ()> for AppData {
    fn event(
        _state: &mut Self,
        _proxy: &WlCompositor,
        _event: <WlCompositor as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<WlSubcompositor, ()> for AppData {
    fn event(
        _state: &mut Self,
        _proxy: &WlSubcompositor,
        _event: <WlSubcompositor as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<WlSurface, ()> for AppData {
    fn event(
        _state: &mut Self,
        _proxy: &WlSurface,
        _event: <WlSurface as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<WlSubsurface, ()> for AppData {
    fn event(
        _state: &mut Self,
        _proxy: &WlSubsurface,
        _event: <WlSubsurface as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

// ---------------------------------------------------------------------------
// Public helpers
// ---------------------------------------------------------------------------

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

/// Create a wl_subsurface as a child of `parent_surface_ptr`.
///
/// # Safety contract (caller must uphold)
///
/// `parent_surface_ptr` must be a valid `*mut wl_proxy` for a `wl_surface`
/// owned by Tauri's main window, and must remain valid for the entire lifetime
/// of the returned [`SubsurfaceHandle`].  Tauri holds the surface alive as
/// long as the window exists, so this is satisfied when the caller keeps the
/// handle within the window's lifetime.
///
/// # Lifecycle concern
///
/// The reconstructed `parent_surface` wraps the *same* C proxy that Tauri
/// already owns.  We do not take ownership — we merely read/commit through it.
/// Dropping the returned handle will destroy the child surface and subsurface,
/// but will NOT destroy the parent.
#[allow(dead_code)] // wired up in D Task 13
pub fn create_subsurface(
    conn: &Connection,
    parent_surface_ptr: NonNull<std::ffi::c_void>,
    x: i32,
    y: i32,
    width: u32,
    height: u32,
) -> AppResult<SubsurfaceHandle> {
    let (globals, mut event_queue) = registry_queue_init::<AppData>(conn)
        .map_err(|e| AppError::Terminal(format!("registry init: {e}")))?;
    let qh: QueueHandle<AppData> = event_queue.handle();

    let compositor: WlCompositor = globals
        .bind(&qh, 1..=4, ())
        .map_err(|e| AppError::Terminal(format!("bind compositor: {e}")))?;
    let subcompositor: WlSubcompositor = globals
        .bind(&qh, 1..=1, ())
        .map_err(|e| AppError::Terminal(format!("bind subcompositor: {e}")))?;

    let mut data = AppData;
    event_queue
        .roundtrip(&mut data)
        .map_err(|e| AppError::Terminal(format!("roundtrip: {e}")))?;

    // Reconstruct the parent WlSurface from its raw wl_proxy pointer.
    // SAFETY: `parent_surface_ptr` is a valid, live `wl_surface` proxy
    // owned by Tauri's window for the duration of the handle's use.
    let parent_id = unsafe {
        wayland_backend::sys::client::ObjectId::from_ptr(
            WlSurface::interface(),
            parent_surface_ptr.as_ptr().cast(),
        )
        .map_err(|e| AppError::Terminal(format!("parent surface from ptr: {e}")))?
    };
    let parent_surface = WlSurface::from_id(conn, parent_id)
        .map_err(|e| AppError::Terminal(format!("parent surface from id: {e}")))?;

    let child_surface = compositor.create_surface(&qh, ());
    let subsurface = subcompositor.get_subsurface(&child_surface, &parent_surface, &qh, ());
    subsurface.set_position(x, y);
    subsurface.set_desync();
    child_surface.commit();
    parent_surface.commit();

    let _ = (width, height); // used in handle fields below
    Ok(SubsurfaceHandle {
        child_surface,
        subsurface,
        width,
        height,
        x,
        y,
    })
}

/// Present a buffer of u32 ARGB pixels to the subsurface.
///
/// D Task 15 stage: marks the surface damaged and commits — no actual buffer
/// is attached yet. D Task 16 wires real softbuffer integration here.
#[allow(dead_code)] // wired in D Task 14 render task; real impl in D Task 16
pub fn present_buffer(
    handle: &std::sync::Arc<parking_lot::Mutex<SubsurfaceHandle>>,
    pixels: &[u32],
    width: u32,
    height: u32,
) -> AppResult<()> {
    let h = handle.lock();
    h.child_surface.damage_buffer(0, 0, width as i32, height as i32);
    h.child_surface.commit();
    let _ = pixels; // consumed in D Task 16
    Ok(())
}

#[cfg(test)]
mod tests {
    #[test]
    fn module_compiles() {
        // Sanity: module compiles. Real subsurface tests need a live Wayland compositor
        // and are part of the D Task 21 manual smoke checklist.
    }
}
