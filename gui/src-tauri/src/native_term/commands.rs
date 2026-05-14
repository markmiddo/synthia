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
            // Wrap Tauri's existing wl_display so we share the connection.
            // SAFETY: the display ptr lives as long as the Tauri main window does.
            // Caller must ensure attach is invoked while the window is alive.
            let backend = unsafe {
                wayland_backend::sys::client::Backend::from_foreign_display(
                    display_ptr.as_ptr() as *mut _,
                )
            };
            let c = wayland_client::Connection::from_backend(backend);
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

    // Measure cell dims via ab_glyph (no FontSystem needed).
    let (cell_w, cell_h) = crate::native_term::renderer::measure_cell(13.5);
    let usable_w = geom.width.saturating_sub(crate::native_term::renderer::PADDING_X * 2);
    let usable_h = geom.height.saturating_sub(crate::native_term::renderer::PADDING_Y * 2);
    let cols = (usable_w / cell_w).max(1) as usize;
    let rows = (usable_h / cell_h).max(1) as usize;

    eprintln!("[native-term] attach geom = ({}, {}) {}x{}", geom.x, geom.y, geom.width, geom.height);
    eprintln!("[native-term] cell_w={cell_w} cell_h={cell_h} cols={cols} rows={rows}");

    let renderer = crate::native_term::renderer::Renderer::new(geom.width, geom.height, cell_w, cell_h, 13.5)?;
    let renderer_arc = std::sync::Arc::new(parking_lot::Mutex::new(renderer));
    let grid = std::sync::Arc::new(parking_lot::Mutex::new(crate::native_term::grid::Grid::new(rows, cols)));

    // Inform the PTY child of the real terminal size so bash wraps lines correctly.
    let _ = crate::commands::terminal::set_pty_size(
        &state.terminals, session_id, cols as u16, rows as u16,
    );

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
        // 16ms render tick.  Cursor blinks at ~530ms half-cycle, repainting
        // even when the grid hasn't changed so the user gets a visible
        // "this terminal is alive and accepting input" cue.
        let mut interval = tokio::time::interval(std::time::Duration::from_millis(16));
        let start = std::time::Instant::now();
        let mut last_blink = true;
        loop {
            interval.tick().await;
            // Blink phase: visible for 530ms, hidden for 530ms.
            let phase = (start.elapsed().as_millis() / 530).is_multiple_of(2);
            let dirty = {
                let mut g = grid_for_render.lock();
                if g.dirty { g.dirty = false; true } else { false }
            };
            let blink_changed = phase != last_blink;
            if dirty || blink_changed {
                last_blink = phase;
                let g = grid_for_render.lock();
                let mut r = renderer_for_render.lock();
                r.render_grid(&g, phase);
                let _ = crate::native_term::subsurface::present_buffer(
                    &softbuffer_for_render,
                    &r.buffer,
                );
            }
        }
    });

    // Take the PTY writer out of `leased` and stash it in an Arc that the
    // global keyboard task can swap to as the active writer slot when this
    // session becomes the visible tab.
    let writer_owned: Box<dyn std::io::Write + Send> = std::mem::replace(
        &mut leased.writer,
        Box::new(std::io::sink()) as Box<dyn std::io::Write + Send>,
    );
    let writer_arc = std::sync::Arc::new(parking_lot::Mutex::new(writer_owned));

    // Spawn the global wl_keyboard listener once.  Subsequent calls are no-ops.
    crate::native_term::ensure_keyboard_task(conn.clone(), app.clone());
    // Make this session the active typing + pointer target.
    crate::native_term::set_active_writer(Some(writer_arc.clone()));
    crate::native_term::set_active_surface(Some(crate::native_term::ActiveSurfaceInfo {
        grid: grid.clone(),
        cell_w,
        cell_h,
        padding_x: crate::native_term::renderer::PADDING_X,
        padding_y: crate::native_term::renderer::PADDING_Y,
    }));

    // Dummy task to satisfy NativeSession.input_task — the real keyboard
    // loop is global now (see `ensure_keyboard_task`).  This handle is
    // never aborted to anything meaningful.
    let input_task = tokio::spawn(async {});

    let session = crate::native_term::NativeSession {
        session_id,
        subsurface: subsurface_arc,
        softbuffer: softbuffer_arc,
        renderer: renderer_arc,
        grid,
        leased,
        writer: writer_arc,
        reader_task,
        render_task,
        input_task,
    };

    state.native_terminals.sessions.lock().insert(session_id, session);
    Ok(())
}

#[derive(Serialize)]
pub struct TabInfo {
    pub id: Uuid,
    pub title: String,
    pub is_active: bool,
}

/// Show the requested terminal tab at the given rect.  Semantics:
///   - `tab_id == None`: show the currently-active tab if there is one,
///     otherwise the most recently-added persistent tab, otherwise spawn
///     a fresh PTY as the first tab.
///   - `tab_id == Some(id)`: switch to that tab.  Hides the current active
///     tab (moves it to persistent) and restores `id` from persistent
///     into a new active session.
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_show(
    app: AppHandle,
    state: State<'_, AppState>,
    tab_id: Option<Uuid>,
    geom: TermGeom,
) -> AppResult<Uuid> {
    // Resolve the target tab id.
    let target = tab_id.or_else(|| {
        let active = state.native_terminals.sessions.lock().keys().next().copied();
        if active.is_some() {
            return active;
        }
        state.native_terminals.tab_order.lock().last().copied()
    });

    // Fast path: target already active → just reposition.
    if let Some(id) = target {
        let is_active = state.native_terminals.sessions.lock().contains_key(&id);
        if is_active {
            return reposition_active_session(&state, id, geom);
        }
    }

    // Need to mutate active set.  First, move the current active tab
    // (if any) into persistent so its subsurface goes away before we
    // create the new one.
    let current = state.native_terminals.sessions.lock().keys().next().copied();
    if let Some(active_id) = current {
        hide_active_to_persistent(&state, active_id, &app)?;
    }

    // Restore target from persistent if present.
    if let Some(id) = target {
        let p = state.native_terminals.persistent.lock().remove(&id);
        if let Some(p) = p {
            return attach_from_persistent(app, state, p, geom).await;
        }
    }

    // Cold path: no persistent entry, no active.  Spawn a new tab.
    let meta =
        crate::commands::terminal::spawn_pty_session_inline(&state.terminals, None, None)?;
    let session_id = meta.id;
    native_term_attach(app, state.clone(), session_id, geom).await?;
    {
        let mut order = state.native_terminals.tab_order.lock();
        if !order.contains(&session_id) {
            order.push(session_id);
        }
    }
    Ok(session_id)
}

/// Spawn a new PTY in a new tab and make it the active visible tab.  The
/// previously-active tab (if any) is moved into the persistent map so the
/// user can switch back to it later.
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_new_tab(
    app: AppHandle,
    state: State<'_, AppState>,
    geom: TermGeom,
) -> AppResult<Uuid> {
    let current = state.native_terminals.sessions.lock().keys().next().copied();
    if let Some(active_id) = current {
        hide_active_to_persistent(&state, active_id, &app)?;
    }
    let meta =
        crate::commands::terminal::spawn_pty_session_inline(&state.terminals, None, None)?;
    let session_id = meta.id;
    native_term_attach(app, state.clone(), session_id, geom).await?;
    {
        let mut order = state.native_terminals.tab_order.lock();
        order.push(session_id);
    }
    Ok(session_id)
}

/// Close the given tab.  Tears down the subsurface (if active), kills the
/// PTY, and removes the tab from the order list.
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_close_tab(
    app: AppHandle,
    state: State<'_, AppState>,
    tab_id: Uuid,
) -> AppResult<()> {
    // If active, destroy subsurface first.
    let active = {
        let mut sessions = state.native_terminals.sessions.lock();
        sessions.remove(&tab_id)
    };
    if let Some(session) = active {
        // Closing the active tab — make sure the keyboard slot doesn't
        // keep pointing at a freed writer.
        crate::native_term::set_active_writer(None);
    crate::native_term::set_active_surface(None);
        let crate::native_term::NativeSession {
            subsurface,
            render_task,
            input_task,
            reader_task,
            leased,
            ..
        } = session;
        render_task.abort();
        input_task.abort();
        reader_task.abort();
        {
            let h = subsurface.lock();
            h.subsurface.set_position(-100000, -100000);
            h.child_surface.attach(None, 0, 0);
            h.child_surface.commit();
            h.subsurface.destroy();
            h.child_surface.destroy();
            h.parent_surface.commit();
        }
        drop(leased);
        if let Some(window) = app.get_webview_window("main") {
            if let Ok(size) = window.outer_size() {
                let w = size.width;
                let h = size.height;
                let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h + 1)));
                let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h)));
            }
            let _ = window.eval(
                "document.body.style.opacity='0.999';\
                 requestAnimationFrame(()=>{document.body.style.opacity='1';});",
            );
        }
    } else {
        // Not active — drop from persistent and kill PTY.
        let p = state.native_terminals.persistent.lock().remove(&tab_id);
        if let Some(p) = p {
            p.reader_task.abort();
            drop(p.leased);
        }
    }
    // Kill the PTY child entirely so the shell process exits.
    let _ = crate::commands::terminal::kill_pty_session(&state.terminals, tab_id);
    state.native_terminals.tab_order.lock().retain(|id| *id != tab_id);
    Ok(())
}

/// List all known tabs (active + persistent), in insertion order, with a
/// flag marking which one is currently the visible/active tab.
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_list_tabs(
    state: State<'_, AppState>,
) -> AppResult<Vec<TabInfo>> {
    let active_id = state.native_terminals.sessions.lock().keys().next().copied();
    let order = state.native_terminals.tab_order.lock().clone();
    let terms = state.terminals.sessions.lock();
    let mut out = Vec::with_capacity(order.len());
    for id in order {
        let title = terms
            .get(&id)
            .map(|s| s.meta.title.clone())
            .unwrap_or_else(|| "shell".to_string());
        out.push(TabInfo {
            id,
            title,
            is_active: Some(id) == active_id,
        });
    }
    Ok(out)
}

/// Move the currently-active tab into the persistent map.  Used by both
/// `show` (when switching tabs) and `new_tab` (when bumping the previous
/// active out of the way).
fn hide_active_to_persistent(
    state: &State<'_, AppState>,
    active_id: Uuid,
    app: &AppHandle,
) -> AppResult<()> {
    let session = state.native_terminals.sessions.lock().remove(&active_id);
    let Some(session) = session else { return Ok(()) };
    // Detach the writer slot — the keyboard task will drop keystrokes
    // until the next show repoints it at a tab.  Prevents typing into a
    // hidden terminal during the navigation gap.
    crate::native_term::set_active_writer(None);
    crate::native_term::set_active_surface(None);

    let crate::native_term::NativeSession {
        session_id,
        subsurface,
        softbuffer: _,
        renderer: _,
        grid,
        leased,
        writer,
        reader_task,
        render_task,
        input_task,
    } = session;

    state.native_terminals.persistent.lock().insert(
        session_id,
        crate::native_term::PersistentNativeState {
            session_id,
            grid,
            leased,
            writer,
            reader_task,
        },
    );

    render_task.abort();
    input_task.abort();
    {
        let h = subsurface.lock();
        h.subsurface.set_position(-100000, -100000);
        h.child_surface.attach(None, 0, 0);
        h.child_surface.commit();
        h.subsurface.destroy();
        h.child_surface.destroy();
        h.parent_surface.commit();
    }
    if let Some(conn) = crate::native_term::wayland_connection() {
        let _ = conn.flush();
        let _ = conn.roundtrip();
    }
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(size) = window.outer_size() {
            let w = size.width;
            let h = size.height;
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h + 1)));
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h)));
        }
        let _ = window.eval(
            "document.body.style.opacity='0.999';\
             requestAnimationFrame(()=>{document.body.style.opacity='1';});",
        );
    }
    Ok(())
}

fn reposition_active_session(
    state: &State<'_, AppState>,
    id: Uuid,
    geom: TermGeom,
) -> AppResult<Uuid> {
    let mut sessions = state.native_terminals.sessions.lock();
    let session = sessions
        .get_mut(&id)
        .ok_or_else(|| AppError::Terminal("session vanished mid-show".into()))?;
    let (cell_w, cell_h) = crate::native_term::renderer::measure_cell(13.5);
    let usable_w =
        geom.width.saturating_sub(crate::native_term::renderer::PADDING_X * 2);
    let usable_h =
        geom.height.saturating_sub(crate::native_term::renderer::PADDING_Y * 2);
    let cols = (usable_w / cell_w).max(1) as usize;
    let rows = (usable_h / cell_h).max(1) as usize;
    {
        let h = session.subsurface.lock();
        h.subsurface.set_position(geom.x, geom.y);
        h.child_surface.commit();
        h.parent_surface.commit();
    }
    session.grid.lock().resize(rows, cols);
    let _ = crate::commands::terminal::set_pty_size(
        &state.terminals, id, cols as u16, rows as u16,
    );
    {
        let mut r = session.renderer.lock();
        r.width = geom.width;
        r.height = geom.height;
        r.cell_w = cell_w;
        r.cell_h = cell_h;
        r.buffer = vec![0u32; (geom.width * geom.height) as usize];
    }
    {
        let mut sb = session.softbuffer.lock();
        sb.surface
            .resize(
                std::num::NonZeroU32::new(geom.width)
                    .ok_or_else(|| AppError::Terminal("zero w".into()))?,
                std::num::NonZeroU32::new(geom.height)
                    .ok_or_else(|| AppError::Terminal("zero h".into()))?,
            )
            .map_err(|e| AppError::Terminal(format!("sb resize: {e}")))?;
    }
    session.grid.lock().dirty = true;
    Ok(id)
}

/// Recreate subsurface + softbuffer + renderer + render/input tasks for
/// a session whose state survived a hide.  The grid + writer + reader_task
/// are reused from the persistent slot.
async fn attach_from_persistent(
    app: AppHandle,
    state: State<'_, AppState>,
    p: crate::native_term::PersistentNativeState,
    geom: TermGeom,
) -> AppResult<Uuid> {
    use raw_window_handle::RawDisplayHandle;
    use raw_window_handle::HasDisplayHandle as _;

    let window = app
        .get_webview_window("main")
        .ok_or_else(|| AppError::Terminal("no main window".into()))?;
    let parent_ptr = crate::native_term::subsurface::parent_surface_from_tauri(&window)?;
    let display_handle = window
        .display_handle()
        .map_err(|e| AppError::Terminal(format!("display_handle: {e}")))?;
    let display_ptr = match display_handle.as_raw() {
        RawDisplayHandle::Wayland(h) => h.display,
        _ => return Err(AppError::Terminal("display not wayland".into())),
    };
    let conn = crate::native_term::wayland_connection()
        .cloned()
        .ok_or_else(|| AppError::Terminal("wayland conn not initialised".into()))?;

    let subsurface = crate::native_term::subsurface::create_subsurface(
        &conn, parent_ptr, geom.x, geom.y, geom.width, geom.height,
    )?;
    let subsurface_arc = std::sync::Arc::new(parking_lot::Mutex::new(subsurface));
    let child_surface_ptr = {
        use wayland_client::Proxy as _;
        let id = subsurface_arc.lock().child_surface.id();
        let raw = id.as_ptr();
        std::ptr::NonNull::new(raw as *mut std::ffi::c_void)
            .ok_or_else(|| AppError::Terminal("null child surface ptr".into()))?
    };
    let softbuffer_state = crate::native_term::subsurface::init_softbuffer(
        display_ptr, child_surface_ptr, geom.width, geom.height,
    )?;
    let softbuffer_arc = std::sync::Arc::new(parking_lot::Mutex::new(softbuffer_state));

    let (cell_w, cell_h) = crate::native_term::renderer::measure_cell(13.5);
    let usable_w =
        geom.width.saturating_sub(crate::native_term::renderer::PADDING_X * 2);
    let usable_h =
        geom.height.saturating_sub(crate::native_term::renderer::PADDING_Y * 2);
    let cols = (usable_w / cell_w).max(1) as usize;
    let rows = (usable_h / cell_h).max(1) as usize;
    p.grid.lock().resize(rows, cols);
    let _ = crate::commands::terminal::set_pty_size(
        &state.terminals, p.session_id, cols as u16, rows as u16,
    );

    let renderer = crate::native_term::renderer::Renderer::new(
        geom.width, geom.height, cell_w, cell_h, 13.5,
    )?;
    let renderer_arc = std::sync::Arc::new(parking_lot::Mutex::new(renderer));
    p.grid.lock().dirty = true;

    let grid_for_render = p.grid.clone();
    let renderer_for_render = renderer_arc.clone();
    let softbuffer_for_render = softbuffer_arc.clone();
    let render_task = tokio::spawn(async move {
        let mut interval = tokio::time::interval(std::time::Duration::from_millis(16));
        let start = std::time::Instant::now();
        let mut last_blink = true;
        loop {
            interval.tick().await;
            let phase = (start.elapsed().as_millis() / 530).is_multiple_of(2);
            let dirty = {
                let mut g = grid_for_render.lock();
                if g.dirty { g.dirty = false; true } else { false }
            };
            let blink_changed = phase != last_blink;
            if dirty || blink_changed {
                last_blink = phase;
                let g = grid_for_render.lock();
                let mut r = renderer_for_render.lock();
                r.render_grid(&g, phase);
                let _ = crate::native_term::subsurface::present_buffer(
                    &softbuffer_for_render,
                    &r.buffer,
                );
            }
        }
    });

    // Use the global keyboard listener.  Just point the active-writer slot
    // at this session so keystrokes go to its PTY.
    crate::native_term::ensure_keyboard_task(conn.clone(), app.clone());
    crate::native_term::set_active_writer(Some(p.writer.clone()));
    crate::native_term::set_active_surface(Some(crate::native_term::ActiveSurfaceInfo {
        grid: p.grid.clone(),
        cell_w,
        cell_h,
        padding_x: crate::native_term::renderer::PADDING_X,
        padding_y: crate::native_term::renderer::PADDING_Y,
    }));
    let input_task = tokio::spawn(async {});

    let session = crate::native_term::NativeSession {
        session_id: p.session_id,
        subsurface: subsurface_arc,
        softbuffer: softbuffer_arc,
        renderer: renderer_arc,
        grid: p.grid,
        leased: p.leased,
        writer: p.writer,
        reader_task: p.reader_task,
        render_task,
        input_task,
    };

    state
        .native_terminals
        .sessions
        .lock()
        .insert(p.session_id, session);
    Ok(p.session_id)
}

/// Hide the persistent terminal.
///
/// Destroys the subsurface (so it visually disappears via the next parent
/// commit) but preserves the PTY lease, grid, writer, and reader_task in
/// the persistent slot.  When `native_term_show` is called again we rebuild
/// the subsurface/softbuffer/render-task using those preserved pieces, so
/// the shell state, scrollback, and any running command survive the
/// navigation away.
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_hide(
    app: AppHandle,
    state: State<'_, AppState>,
) -> AppResult<()> {
    let session = {
        let mut sessions = state.native_terminals.sessions.lock();
        let id = match sessions.keys().next().copied() {
            Some(id) => id,
            None => return Ok(()),
        };
        sessions.remove(&id)
    };
    let Some(session) = session else { return Ok(()) };
    crate::native_term::set_active_writer(None);
    crate::native_term::set_active_surface(None);

    // Destructure first.  Move grid + leased + writer + reader_task into
    // the persistent slot *before* doing any teardown — otherwise a
    // rapid hide→show race (user double-clicks tabs) can have `show`
    // observe an empty persistent and fall through to a fresh spawn,
    // losing the user's shell state.
    let crate::native_term::NativeSession {
        session_id,
        subsurface,
        softbuffer: _softbuffer,
        renderer: _renderer,
        grid,
        leased,
        writer,
        reader_task,
        render_task,
        input_task,
    } = session;

    // 1. Write persistent state FIRST (covers the race window).
    state.native_terminals.persistent.lock().insert(
        session_id,
        crate::native_term::PersistentNativeState {
            session_id,
            grid,
            leased,
            writer,
            reader_task,
        },
    );

    // 2. Now tear down the show-bound pieces.  render/input tasks abort
    //    immediately; subsurface destroy queues parent state for the next
    //    webview commit.
    render_task.abort();
    input_task.abort();
    {
        let h = subsurface.lock();
        h.subsurface.set_position(-100000, -100000);
        h.child_surface.attach(None, 0, 0);
        h.child_surface.commit();
        h.subsurface.destroy();
        h.child_surface.destroy();
        h.parent_surface.commit();
    }
    if let Some(conn) = crate::native_term::wayland_connection() {
        let _ = conn.flush();
        let _ = conn.roundtrip();
    }
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(size) = window.outer_size() {
            let w = size.width;
            let h = size.height;
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h + 1)));
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h)));
        }
        let _ = window.eval(
            "document.body.style.opacity='0.999';\
             requestAnimationFrame(()=>{document.body.style.opacity='1';});",
        );
    }
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
    let (cell_w, cell_h) = crate::native_term::renderer::measure_cell(13.5);
    let usable_w = geom.width.saturating_sub(crate::native_term::renderer::PADDING_X * 2);
    let usable_h = geom.height.saturating_sub(crate::native_term::renderer::PADDING_Y * 2);
    let cols = (usable_w / cell_w).max(1) as usize;
    let rows = (usable_h / cell_h).max(1) as usize;
    session.grid.lock().resize(rows, cols);
    // Propagate new size to PTY child so bash/vim re-wrap at the new width.
    let _ = crate::commands::terminal::set_pty_size(
        &state.terminals, session_id, cols as u16, rows as u16,
    );
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
    app: AppHandle,
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

    // ---------------------------------------------------------------------
    // Visual cleanup strategy
    //
    // Wayland subsurface destruction is double-buffered on the *parent*
    // surface — meaning the destroy doesn't visually take effect until the
    // parent (Tauri's webview wl_surface) commits a new frame.  Webkit only
    // commits when DOM content changes, so the subsurface lingers as a
    // ghost overlay after the React component unmounts.
    //
    // We work around this with two layered defences:
    //   1.  Paint a buffer in the Synthia panel background colour, then
    //       commit the *child* surface.  In desync mode, child commits
    //       apply immediately — so the area instantly becomes the same
    //       colour as the surrounding chrome, hiding the subsurface even
    //       if its destruction never propagates.
    //   2.  Best-effort destroy + parent_surface.commit() so the subsurface
    //       is properly torn down when the compositor next composites.
    // ---------------------------------------------------------------------
    {
        let mut r = session.renderer.lock();
        r.paint_blank();
        let _ = crate::native_term::subsurface::present_buffer(
            &session.softbuffer,
            &r.buffer,
        );
    }
    {
        let h = session.subsurface.lock();
        // Move off-screen as belt-and-braces (queued on parent).
        h.subsurface.set_position(-100000, -100000);
        h.child_surface.attach(None, 0, 0);
        h.child_surface.commit();
        h.subsurface.destroy();
        h.child_surface.destroy();
        // Commit the parent so the destroy + position queue actually apply.
        // The parent_surface proxy was reconstructed from Tauri's surface,
        // so this issues a commit on the same wl_surface Tauri owns — safe
        // because Wayland coalesces commits and the next webview frame will
        // override our state anyway.
        h.parent_surface.commit();
    }
    if let Some(conn) = crate::native_term::wayland_connection() {
        let _ = conn.flush();
        let _ = conn.roundtrip();
    }
    // Final nudges to force the webview to commit a fresh parent buffer:
    //   1. Window size cycle triggers xdg_surface reconfigure.
    //   2. JS-injected DOM mutation (opacity flip) forces WebKit to repaint
    //      and commit on the next animation frame.
    if let Some(window) = app.get_webview_window("main") {
        if let Ok(size) = window.outer_size() {
            let w = size.width;
            let h = size.height;
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h + 1)));
            let _ = window.set_size(tauri::Size::Physical(tauri::PhysicalSize::new(w, h)));
        }
        let _ = window.eval(
            "document.body.style.opacity='0.999';\
             requestAnimationFrame(()=>{document.body.style.opacity='1';});",
        );
    }
    let leased = session.leased;
    crate::commands::terminal::restore_from_native(&state.terminals, session_id, leased)?;
    Ok(())
}
