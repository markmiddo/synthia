//! Tauri commands for the native renderer.

use raw_window_handle::{HasDisplayHandle, RawDisplayHandle};
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

    // Extract the Wayland display pointer from the window's display handle.
    let display_handle = window
        .display_handle()
        .map_err(|e| AppError::Terminal(format!("display_handle: {e}")))?;
    let display_ptr = match display_handle.as_raw() {
        RawDisplayHandle::Wayland(h) => h.display,
        _ => return Err(AppError::Terminal("display not wayland".into())),
    };

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

    // Extract the child wl_surface pointer for softbuffer binding.
    let child_surface_ptr = {
        use wayland_client::Proxy as _;
        let id = subsurface_arc.lock().child_surface.id();
        // ObjectId::as_ptr() returns *mut wl_proxy (null if destroyed).
        let raw = id.as_ptr();
        std::ptr::NonNull::new(raw as *mut std::ffi::c_void)
            .ok_or_else(|| AppError::Terminal("null child surface ptr".into()))?
    };

    let softbuffer_state = crate::native_term::subsurface::init_softbuffer(
        display_ptr,
        child_surface_ptr,
        geom.width,
        geom.height,
    )?;
    let softbuffer_arc = std::sync::Arc::new(parking_lot::Mutex::new(softbuffer_state));

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
    // D Task 16: presents pixel buffer to child wl_surface via softbuffer.
    let grid_for_render = grid.clone();
    let renderer_for_render = renderer_arc.clone();
    let softbuffer_for_render = softbuffer_arc.clone();
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
                let _ = crate::native_term::subsurface::present_buffer(
                    &softbuffer_for_render,
                    &r.buffer,
                );
            }
        }
    });

    // Input task (D Task 17): move the PTY writer into a shared Arc so the
    // keyboard event loop can write to it without borrowing `leased`.
    let writer_owned: Box<dyn std::io::Write + Send> = std::mem::replace(
        &mut leased.writer,
        Box::new(std::io::sink()) as Box<dyn std::io::Write + Send>,
    );
    let writer_arc = std::sync::Arc::new(parking_lot::Mutex::new(writer_owned));
    let writer_for_input = writer_arc.clone();
    let conn_for_input = conn.clone();
    let input_task = tokio::task::spawn_blocking(move || {
        if let Err(e) =
            crate::native_term::keyboard::run_keyboard_loop(conn_for_input, writer_for_input)
        {
            eprintln!("[native-term] keyboard loop ended: {e}");
        }
    });

    let session = crate::native_term::NativeSession {
        session_id,
        subsurface: subsurface_arc,
        softbuffer: softbuffer_arc,
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

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (D Task 19)
pub async fn native_term_resize(
    state: State<'_, AppState>,
    session_id: Uuid,
    geom: TermGeom,
) -> AppResult<()> {
    let mut sessions = state.native_terminals.sessions.lock();
    let session = sessions
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown native session {session_id}")))?;
    {
        let h = session.subsurface.lock();
        h.subsurface.set_position(geom.x, geom.y);
        h.child_surface.commit();
    }
    let cell_w = 8u32;
    let cell_h = 16u32;
    let cols = (geom.width / cell_w).max(1) as usize;
    let rows = (geom.height / cell_h).max(1) as usize;
    session.grid.lock().resize(rows, cols);
    {
        let mut r = session.renderer.lock();
        r.width = geom.width;
        r.height = geom.height;
        r.buffer = vec![0u32; (geom.width * geom.height) as usize];
    }
    {
        let mut sb = session.softbuffer.lock();
        sb.surface.resize(
            std::num::NonZeroU32::new(geom.width).ok_or_else(|| AppError::Terminal("zero w".into()))?,
            std::num::NonZeroU32::new(geom.height).ok_or_else(|| AppError::Terminal("zero h".into()))?,
        ).map_err(|e| AppError::Terminal(format!("sb resize: {e}")))?;
    }
    Ok(())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (D Task 19)
pub async fn native_term_detach(
    state: State<'_, AppState>,
    session_id: Uuid,
) -> AppResult<()> {
    let mut sessions = state.native_terminals.sessions.lock();
    let session = sessions
        .remove(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown native session {session_id}")))?;
    session.reader_task.abort();
    session.render_task.abort();
    session.input_task.abort();
    let leased = session.leased;
    crate::commands::terminal::restore_from_native(&state.terminals, session_id, leased)?;
    Ok(())
}
