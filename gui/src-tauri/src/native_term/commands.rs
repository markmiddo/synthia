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
    let window = app
        .get_webview_window("main")
        .ok_or_else(|| AppError::Terminal("no main window".into()))?;
    let parent_ptr = crate::native_term::subsurface::parent_surface_from_tauri(&window)?;

    let conn = match crate::native_term::wayland_connection() {
        Some(c) => c.clone(),
        None => {
            let c = wayland_client::Connection::connect_to_env()
                .map_err(|e| AppError::Terminal(format!("wayland connect: {e}")))?;
            crate::native_term::init_wayland_connection(c.clone());
            c
        }
    };

    let subsurface = crate::native_term::subsurface::create_subsurface(
        &conn, parent_ptr, geom.x, geom.y, geom.width, geom.height,
    )?;
    let subsurface_arc = std::sync::Arc::new(parking_lot::Mutex::new(subsurface));

    let mut leased = crate::commands::terminal::lease_for_native(&state.terminals, session_id)?
        .ok_or_else(|| AppError::Terminal("session already leased or not spawned".into()))?;

    // Compute cell dims from font metrics (8x16 placeholder; D Task 16+ calibrates from cosmic-text).
    let cell_w = 8u32;
    let cell_h = 16u32;
    let cols = (geom.width / cell_w).max(1) as usize;
    let rows = (geom.height / cell_h).max(1) as usize;

    let renderer = crate::native_term::renderer::Renderer::new(geom.width, geom.height, cell_w, cell_h, 13.0)?;
    let renderer_arc = std::sync::Arc::new(parking_lot::Mutex::new(renderer));
    let grid = std::sync::Arc::new(parking_lot::Mutex::new(crate::native_term::grid::Grid::new(rows, cols)));

    // Take reader out of leased into a separate var so it can move into the spawn_blocking closure.
    let mut reader = std::mem::replace(
        &mut leased.reader,
        Box::new(std::io::empty()) as Box<dyn std::io::Read + Send>,
    );

    // Reader task: PTY bytes → vte parser → grid mutation
    let grid_for_reader = grid.clone();
    let reader_task = tokio::task::spawn_blocking(move || {
        use std::io::Read as _;
        let mut parser = vte::Parser::new();
        let mut buf = [0u8; 4096];
        loop {
            match reader.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    let mut g = grid_for_reader.lock();
                    for &byte in &buf[..n] {
                        parser.advance(&mut *g, byte);
                    }
                }
            }
        }
    });

    // Render task: 60fps poll on dirty flag, blit to renderer buffer.
    // Stage 3 (D Task 16) presents to wl_surface via softbuffer.
    let grid_for_render = grid.clone();
    let renderer_for_render = renderer_arc.clone();
    let subsurface_for_render = subsurface_arc.clone();
    let render_task = tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_millis(16));
        loop {
            interval.tick().await;
            let dirty = {
                let mut g = grid_for_render.lock();
                if g.dirty { g.dirty = false; true } else { false }
            };
            if dirty {
                let g = grid_for_render.lock();
                let mut r = renderer_for_render.lock();
                r.render_grid(&g);
                // Stage 3 scaffold: damage + commit (real present in D Task 16).
                let _ = crate::native_term::subsurface::present_buffer(
                    &subsurface_for_render,
                    &r.buffer,
                    r.width,
                    r.height,
                );
            }
        }
    });

    // Input task: placeholder until D Task 17's Wayland keyboard binding lands.
    let input_task = tokio::spawn(async move {
        loop { tokio::time::sleep(std::time::Duration::from_secs(60)).await; }
    });

    let session = crate::native_term::NativeSession {
        session_id,
        subsurface: subsurface_arc,
        renderer: renderer_arc,
        grid,
        leased,
        reader_task,
        render_task,
        input_task,
    };

    state.native_terminals.sessions.lock().insert(session_id, session);
    Ok(())
}
