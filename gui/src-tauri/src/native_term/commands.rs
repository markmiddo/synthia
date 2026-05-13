//! Tauri commands for the native renderer.

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::state::AppState;

#[derive(Deserialize, Serialize, Clone, Copy)]
#[allow(dead_code)] // registered in lib.rs (D Task 19)
pub struct TermGeom {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (D Task 19)
pub async fn native_term_attach(
    app: AppHandle,
    state: State<'_, AppState>,
    session_id: Uuid,
    geom: TermGeom,
) -> AppResult<()> {
    // Resolve Tauri main window
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| AppError::Terminal("no main window".into()))?;

    // Extract parent surface
    let parent_ptr = crate::native_term::subsurface::parent_surface_from_tauri(&window)?;

    // Acquire / cache shared Wayland connection
    let conn = match crate::native_term::wayland_connection() {
        Some(c) => c.clone(),
        None => {
            let c = wayland_client::Connection::connect_to_env()
                .map_err(|e| AppError::Terminal(format!("wayland connect: {e}")))?;
            crate::native_term::init_wayland_connection(c.clone());
            c
        }
    };

    // Create subsurface (stage 2 — pipeline glue happens in D Task 14)
    let _handle = crate::native_term::subsurface::create_subsurface(
        &conn, parent_ptr, geom.x, geom.y, geom.width, geom.height,
    )?;

    // Lease PTY from the existing terminal session
    let _leased = crate::commands::terminal::lease_for_native(&state.terminals, session_id)?
        .ok_or_else(|| AppError::Terminal("session already leased or not spawned".into()))?;

    // FIXME(D Task 14): wire reader → vte parser → grid mutation,
    // wire grid dirty → renderer → softbuffer present (D Task 16),
    // wire wl_keyboard events → input handler → leased.writer (D Task 17).
    // Stage 1 of this task only proves attach succeeds end-to-end (compiles + invokable).

    Ok(())
}
