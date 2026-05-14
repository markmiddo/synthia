//! Wayland keyboard binding for the native renderer.
//!
//! Spawned as a blocking task by `commands::native_term_attach`. Owns its
//! own EventQueue + KeyboardState. Translates wl_keyboard events into PTY
//! byte sequences via the existing InputHandler.

use std::os::fd::AsFd;

use tauri::Emitter;
use wayland_client::{
    protocol::{
        wl_data_device, wl_data_device_manager, wl_data_offer, wl_keyboard, wl_pointer,
        wl_registry, wl_seat,
    },
    Connection, Dispatch, Proxy, QueueHandle, WEnum,
};
use xkbcommon::xkb;

/// Run the Wayland keyboard event loop.
///
/// Binds `wl_seat`, calls `get_keyboard()`, then dispatches events in a
/// blocking loop. Returns when the compositor closes the connection.
///
/// Uses `conn.new_event_queue()` rather than `registry_queue_init` so that
/// the shared (foreign-display) Connection is not re-initialised and the
/// underlying `wl_display` is not double-registered with the compositor.
#[allow(dead_code)] // wired up in mod.rs (multi-tab safe global)
pub fn run_keyboard_loop(
    conn: Connection,
    writer_slot: crate::native_term::WriterSlot,
    app: tauri::AppHandle,
) -> Result<(), String> {
    let mut event_queue: wayland_client::EventQueue<KeyboardState> = conn.new_event_queue();
    let qh = event_queue.handle();

    // Bind the global registry on this event queue.  The Dispatch impl below
    // will receive Global events and bind wl_seat (and from that, wl_keyboard).
    let display = conn.display();
    let _registry = display.get_registry(&qh, ());

    let mut state = KeyboardState {
        xkb_ctx: xkb::Context::new(xkb::CONTEXT_NO_FLAGS),
        keymap: None,
        xkb_state: None,
        input: crate::native_term::input::InputHandler::new(),
        writer_slot,
        seat: None,
        keyboard_obtained: false,
        app,
        repeat: None,
        repeat_rate: 25,
        repeat_delay: 600,
        data_device_mgr: None,
        data_device: None,
        current_offer: None,
        offer_mimes: Vec::new(),
        pointer: None,
        pointer_x: 0.0,
        pointer_y: 0.0,
        selecting: false,
        press_anchor: None,
    };

    // Initial roundtrip: compositor sends all current globals, we bind wl_seat
    // and request get_keyboard.  A second roundtrip delivers the Keymap event.
    event_queue
        .roundtrip(&mut state)
        .map_err(|e| format!("initial roundtrip: {e}"))?;
    event_queue
        .roundtrip(&mut state)
        .map_err(|e| format!("keymap roundtrip: {e}"))?;

    loop {
        if event_queue.blocking_dispatch(&mut state).is_err() {
            break;
        }
    }
    Ok(())
}

/// State object for the keyboard event loop.
pub struct KeyboardState {
    xkb_ctx: xkb::Context,
    keymap: Option<xkb::Keymap>,
    xkb_state: Option<xkb::State>,
    input: crate::native_term::input::InputHandler,
    writer_slot: crate::native_term::WriterSlot,
    /// The bound wl_seat (kept alive so the keyboard object isn't destroyed).
    seat: Option<wl_seat::WlSeat>,
    /// Set to true once `get_keyboard()` has been called.
    keyboard_obtained: bool,
    /// Tauri app handle so we can emit shortcut events to React.
    app: tauri::AppHandle,
    /// Active autorepeat task (if any) — cancelled on key release or
    /// when a different key is pressed.
    repeat: Option<RepeatState>,
    /// Compositor-advertised key repeat rate (keys per second) and the
    /// initial delay (ms) before repeats begin.  Wayland defaults: 25 / 600.
    repeat_rate: i32,
    repeat_delay: i32,
    /// Drag-and-drop bookkeeping.  We bind wl_data_device for the seat so
    /// the subsurface can receive drag drops (the webview's own drag-drop
    /// path doesn't fire because the subsurface intercepts pointer events).
    data_device_mgr: Option<wl_data_device_manager::WlDataDeviceManager>,
    data_device: Option<wl_data_device::WlDataDevice>,
    current_offer: Option<wl_data_offer::WlDataOffer>,
    /// Last advertised mime types on the most recent data_offer.  We use
    /// this to pick `text/uri-list` (file drops) over `text/plain`.
    offer_mimes: Vec<String>,
    /// Pointer state (mouse selection).
    pointer: Option<wl_pointer::WlPointer>,
    pointer_x: f64,
    pointer_y: f64,
    /// True while the left mouse button is held.
    selecting: bool,
    /// (row, col) at button-press time; selection only materialises on
    /// the first motion event after press, so a plain click clears any
    /// previous selection without creating a new one.
    press_anchor: Option<(usize, usize)>,
}

struct RepeatState {
    keycode: u32,
    cancel: std::sync::Arc<std::sync::atomic::AtomicBool>,
}

// ---------------------------------------------------------------------------
// Dispatch impls
// ---------------------------------------------------------------------------

impl Dispatch<wl_registry::WlRegistry, ()> for KeyboardState {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: <wl_registry::WlRegistry as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        qh: &QueueHandle<Self>,
    ) {
        if let wl_registry::Event::Global {
            name,
            interface,
            version,
        } = event
        {
            if interface == "wl_seat" {
                let seat: wl_seat::WlSeat = registry.bind(name, version.min(8), qh, ());
                if !state.keyboard_obtained {
                    let _kb = seat.get_keyboard(qh, ());
                    state.keyboard_obtained = true;
                }
                if state.pointer.is_none() {
                    state.pointer = Some(seat.get_pointer(qh, ()));
                }
                state.seat = Some(seat);
                // Link the data device now if the manager was bound first.
                if let (Some(mgr), Some(seat)) =
                    (state.data_device_mgr.as_ref(), state.seat.as_ref())
                {
                    if state.data_device.is_none() {
                        state.data_device = Some(mgr.get_data_device(seat, qh, ()));
                    }
                }
            }
            if interface == "wl_data_device_manager" {
                eprintln!("[native-term-dnd] binding wl_data_device_manager v{}", version);
                let mgr: wl_data_device_manager::WlDataDeviceManager =
                    registry.bind(name, version.min(3), qh, ());
                state.data_device_mgr = Some(mgr);
                if let (Some(mgr), Some(seat)) =
                    (state.data_device_mgr.as_ref(), state.seat.as_ref())
                {
                    if state.data_device.is_none() {
                        state.data_device = Some(mgr.get_data_device(seat, qh, ()));
                        eprintln!("[native-term-dnd] data_device created");
                    }
                }
            }
        }
    }
}

impl Dispatch<wl_pointer::WlPointer, ()> for KeyboardState {
    fn event(
        state: &mut Self,
        _proxy: &wl_pointer::WlPointer,
        event: <wl_pointer::WlPointer as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
        match event {
            wl_pointer::Event::Enter { surface_x, surface_y, .. } => {
                state.pointer_x = surface_x;
                state.pointer_y = surface_y;
            }
            wl_pointer::Event::Motion { surface_x, surface_y, .. } => {
                state.pointer_x = surface_x;
                state.pointer_y = surface_y;
                if state.selecting {
                    // Only materialise a selection once the cursor has
                    // actually moved to a *different* cell from where the
                    // button was pressed.  Tiny sub-pixel jitter that
                    // doesn't cross a cell boundary should not produce a
                    // single-cell highlight on plain clicks.
                    if let Some(anchor) = state.press_anchor {
                        let cur = pointer_cell(state.pointer_x, state.pointer_y);
                        if cur == Some(anchor) {
                            return; // still in same cell — no drag yet
                        }
                        state.press_anchor = None;
                        update_selection(state, Some(anchor));
                    } else {
                        update_selection(state, None);
                    }
                }
            }
            wl_pointer::Event::Button {
                button,
                state: WEnum::Value(wl_pointer::ButtonState::Pressed),
                ..
            } => {
                if button == 0x110 {
                    // BTN_LEFT — clear any prior selection but DON'T
                    // create a new one yet.  The selection only starts
                    // once the user actually drags (first Motion event).
                    state.selecting = true;
                    let cell = pointer_cell(state.pointer_x, state.pointer_y);
                    state.press_anchor = cell;
                    if let Some(info) = crate::native_term::active_surface_slot().lock().clone() {
                        let mut g = info.grid.lock();
                        if g.selection.is_some() {
                            g.selection = None;
                            g.dirty = true;
                        }
                    }
                }
            }
            wl_pointer::Event::Button {
                button,
                state: WEnum::Value(wl_pointer::ButtonState::Released),
                ..
            } => {
                if button == 0x110 {
                    state.selecting = false;
                    state.press_anchor = None;
                }
            }
            _ => {}
        }
    }
}

/// Pure helper: convert pointer surface coords to a grid cell using the
/// currently-active surface info.  Returns None if no active surface.
fn pointer_cell(x: f64, y: f64) -> Option<(usize, usize)> {
    let slot = crate::native_term::active_surface_slot();
    let info = slot.lock().clone()?;
    if info.cell_w == 0 || info.cell_h == 0 {
        return None;
    }
    let g = info.grid.lock();
    let xpx = (x as i64 - info.padding_x as i64).max(0) as u32;
    let ypx = (y as i64 - info.padding_y as i64).max(0) as u32;
    let col = (xpx / info.cell_w) as usize;
    let row = (ypx / info.cell_h) as usize;
    Some((
        row.min(g.rows.saturating_sub(1)),
        col.min(g.cols.saturating_sub(1)),
    ))
}

/// Update the active grid's selection from the current pointer position.
/// If `anchor` is provided, this is the first motion of a drag — set both
/// anchor and head.  Otherwise just move head to extend the selection.
fn update_selection(state: &KeyboardState, anchor: Option<(usize, usize)>) {
    let info_opt = crate::native_term::active_surface_slot().lock().clone();
    let Some(info) = info_opt else { return };
    let Some(cell) = pointer_cell(state.pointer_x, state.pointer_y) else { return };
    let mut g = info.grid.lock();
    if let Some(a) = anchor {
        g.selection = Some(crate::native_term::grid::Selection {
            anchor: a,
            head: cell,
        });
    } else if let Some(sel) = g.selection.as_mut() {
        sel.head = cell;
    } else {
        // Drag already started but selection cleared between motions —
        // re-establish it so the highlight tracks.
        g.selection = Some(crate::native_term::grid::Selection {
            anchor: cell,
            head: cell,
        });
    }
    g.dirty = true;
}

impl Dispatch<wl_data_device_manager::WlDataDeviceManager, ()> for KeyboardState {
    fn event(
        _state: &mut Self,
        _proxy: &wl_data_device_manager::WlDataDeviceManager,
        _event: <wl_data_device_manager::WlDataDeviceManager as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
    }
}

impl Dispatch<wl_data_device::WlDataDevice, ()> for KeyboardState {
    fn event(
        state: &mut Self,
        _proxy: &wl_data_device::WlDataDevice,
        event: <wl_data_device::WlDataDevice as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
        eprintln!("[native-term-dnd] data_device event: {event:?}");
        match event {
            wl_data_device::Event::DataOffer { id } => {
                state.current_offer = Some(id);
                state.offer_mimes.clear();
            }
            wl_data_device::Event::Enter { id, serial, .. } => {
                // A drag entered our subsurface (or sibling).  Accept the
                // best-matching mime so the source knows we'll handle the
                // drop.  The Enter serial MUST be passed back to accept()
                // — passing 0 makes the source treat it as a decline.
                if let Some(offer) = id.as_ref() {
                    let mime = pick_mime(&state.offer_mimes);
                    eprintln!(
                        "[native-term-dnd] enter: mimes={:?} chose={:?} serial={}",
                        state.offer_mimes, mime, serial
                    );
                    if let Some(m) = mime.as_deref() {
                        offer.accept(serial, Some(m.to_string()));
                    } else {
                        offer.accept(serial, None);
                    }
                    // Negotiate the action — required for v3+ data offers,
                    // otherwise source emits Cancel/Leave instead of Drop.
                    if offer.version() >= 3 {
                        let copy = wl_data_device_manager::DndAction::Copy;
                        offer.set_actions(copy, copy);
                    }
                }
            }
            wl_data_device::Event::Leave => {
                if let Some(offer) = state.current_offer.take() {
                    offer.destroy();
                }
                state.offer_mimes.clear();
            }
            wl_data_device::Event::Drop => {
                let offer = match state.current_offer.take() {
                    Some(o) => o,
                    None => return,
                };
                let mime = match pick_mime(&state.offer_mimes) {
                    Some(m) => m,
                    None => {
                        offer.destroy();
                        return;
                    }
                };
                // Create a pipe; pass the write end to the source via offer.receive.
                let mut fds = [0i32; 2];
                let pipe_ok = unsafe { libc::pipe(fds.as_mut_ptr()) } == 0;
                if !pipe_ok {
                    offer.destroy();
                    return;
                }
                let (read_fd, write_fd) = (fds[0], fds[1]);
                // SAFETY: we pass the raw write fd; the compositor takes
                // ownership and closes it after writing.  We keep the read
                // fd to drain the data ourselves.
                let write_fd_owned = unsafe {
                    std::os::fd::OwnedFd::from_raw_fd(write_fd)
                };
                use std::os::fd::FromRawFd;
                offer.receive(mime.clone(), write_fd_owned.as_fd());
                offer.finish();
                offer.destroy();

                // Drain the read fd in a thread; pass the bytes to the
                // active writer slot formatted for the shell.
                let writer_slot = state.writer_slot.clone();
                std::thread::spawn(move || {
                    let mut buf = Vec::new();
                    use std::io::Read as _;
                    let mut f = unsafe { std::fs::File::from_raw_fd(read_fd) };
                    let _ = f.read_to_end(&mut buf);
                    let text = String::from_utf8_lossy(&buf).to_string();
                    let formatted = format_drop_payload(&mime, &text);
                    if formatted.is_empty() {
                        return;
                    }
                    let slot = writer_slot.lock();
                    if let Some(writer) = slot.as_ref() {
                        let mut w = writer.lock();
                        let _ = w.write_all(formatted.as_bytes());
                        let _ = w.flush();
                    }
                });
            }
            _ => {}
        }
    }

    wayland_client::event_created_child!(KeyboardState, wl_data_device::WlDataDevice, [
        wl_data_device::EVT_DATA_OFFER_OPCODE => (wl_data_offer::WlDataOffer, ()),
    ]);
}

impl Dispatch<wl_data_offer::WlDataOffer, ()> for KeyboardState {
    fn event(
        state: &mut Self,
        _proxy: &wl_data_offer::WlDataOffer,
        event: <wl_data_offer::WlDataOffer as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
        eprintln!("[native-term-dnd] data_offer event: {event:?}");
        if let wl_data_offer::Event::Offer { mime_type } = event {
            state.offer_mimes.push(mime_type);
        }
    }
}

/// Prefer text/uri-list (file drops) → text/plain → first available.
fn pick_mime(mimes: &[String]) -> Option<String> {
    for preferred in &["text/uri-list", "text/plain;charset=utf-8", "text/plain", "UTF8_STRING"] {
        if mimes.iter().any(|m| m == preferred) {
            return Some((*preferred).to_string());
        }
    }
    mimes.first().cloned()
}

/// Convert raw drop bytes into a single-line shell-quoted payload that
/// the user can edit before pressing Enter.  For text/uri-list, decode
/// each `file://` URI into a path.  For plain text, paste verbatim.
fn format_drop_payload(mime: &str, text: &str) -> String {
    if mime.starts_with("text/uri-list") {
        let mut out = String::new();
        for raw in text.lines() {
            let line = raw.trim();
            if line.is_empty() || line.starts_with('#') {
                continue;
            }
            let path = if let Some(stripped) = line.strip_prefix("file://") {
                percent_decode(stripped)
            } else {
                line.to_string()
            };
            if !out.is_empty() {
                out.push(' ');
            }
            out.push('\'');
            out.push_str(&path.replace('\'', "'\\''"));
            out.push('\'');
        }
        out
    } else {
        text.trim_end_matches(['\n', '\r']).to_string()
    }
}

fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hi = (bytes[i + 1] as char).to_digit(16);
            let lo = (bytes[i + 2] as char).to_digit(16);
            if let (Some(h), Some(l)) = (hi, lo) {
                out.push((h * 16 + l) as u8);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

impl Dispatch<wl_seat::WlSeat, ()> for KeyboardState {
    fn event(
        _state: &mut Self,
        _seat: &wl_seat::WlSeat,
        _event: <wl_seat::WlSeat as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
        // We always attempt get_keyboard; seat capability events are ignored.
    }
}

impl Dispatch<wl_keyboard::WlKeyboard, ()> for KeyboardState {
    fn event(
        state: &mut Self,
        _kb: &wl_keyboard::WlKeyboard,
        event: <wl_keyboard::WlKeyboard as Proxy>::Event,
        _data: &(),
        _conn: &Connection,
        _qh: &QueueHandle<Self>,
    ) {
        eprintln!("[native-term-kb] event: {event:?}");
        match event {
            wl_keyboard::Event::Keymap {
                format: WEnum::Value(wl_keyboard::KeymapFormat::XkbV1),
                fd,
                size,
            } => {
                // Convert the OwnedFd into a File so we can read from it.
                // OwnedFd implements From for File; this transfers ownership.
                eprintln!("[native-term-kb] Keymap arrived, size={size}");
                // Wayland gives us a memory-mapped fd. Reading via File::read_exact
                // does NOT work because the fd is not a regular file (no seek/read).
                // We must mmap it instead.
                use std::os::fd::AsRawFd;
                let raw_fd = fd.as_raw_fd();
                let map_size = size as usize;
                let map_ptr = unsafe {
                    libc::mmap(
                        std::ptr::null_mut(),
                        map_size,
                        libc::PROT_READ,
                        libc::MAP_PRIVATE,
                        raw_fd,
                        0,
                    )
                };
                if map_ptr == libc::MAP_FAILED {
                    let err = std::io::Error::last_os_error();
                    eprintln!("[native-term-kb] mmap FAILED: {err}");
                } else {
                    let bytes = unsafe { std::slice::from_raw_parts(map_ptr as *const u8, map_size.saturating_sub(1)) };
                    match std::str::from_utf8(bytes) {
                        Ok(s) => {
                            eprintln!("[native-term-kb] keymap parsed, {} chars", s.len());
                            let keymap = xkb::Keymap::new_from_string(
                                &state.xkb_ctx,
                                s.to_string(),
                                xkb::KEYMAP_FORMAT_TEXT_V1,
                                xkb::KEYMAP_COMPILE_NO_FLAGS,
                            );
                            match keymap {
                                Some(km) => {
                                    eprintln!("[native-term-kb] xkb keymap loaded OK");
                                    state.xkb_state = Some(xkb::State::new(&km));
                                    state.keymap = Some(km);
                                }
                                None => eprintln!("[native-term-kb] xkb keymap NEW_FROM_STRING returned None"),
                            }
                        }
                        Err(e) => eprintln!("[native-term-kb] utf8 FAILED: {e}"),
                    }
                    unsafe { libc::munmap(map_ptr, map_size) };
                }
                // OwnedFd dropped here closes the underlying fd.
                drop(fd);
            }

            wl_keyboard::Event::Key {
                key,
                state: WEnum::Value(wl_keyboard::KeyState::Pressed),
                ..
            } => {
                let xkb_present = state.xkb_state.is_some();
                eprintln!("[native-term-kb] key={key} xkb_state_loaded={xkb_present}");
                if let Some(xkb_state) = &state.xkb_state {
                    // evdev keycodes are offset by 8 vs XKB keycodes.
                    let keycode = xkb::Keycode::new(key + 8);
                    let keysym = xkb_state.key_get_one_sym(keycode);
                    let utf8 = xkb_state.key_get_utf8(keycode);
                    let utf8_char = utf8.chars().next();

                    // Tab management shortcuts — fire BEFORE writing to PTY.
                    // Alt+T new tab, Alt+W close active, Alt+1..9 jump to N.
                    // Use raw keysym values; Alt+T preserves XK_t (0x74).
                    let ks_raw: u32 = keysym.raw();
                    if state.input.modifiers.alt && !state.input.modifiers.ctrl {
                        match ks_raw {
                            0x57 | 0x77 => {
                                let _ = state.app.emit("terminal-close-active-tab", ());
                                return;
                            }
                            0x54 | 0x74 => {
                                let _ = state.app.emit("terminal-new-tab", ());
                                return;
                            }
                            _ => {}
                        }
                    }
                    // Ctrl+(Shift+)Tab still cycles tabs.
                    if state.input.modifiers.ctrl && matches!(ks_raw, 0xff09 | 0xfe20) {
                        let payload = if state.input.modifiers.shift { "prev" } else { "next" };
                        let _ = state.app.emit("terminal-cycle-tab", payload);
                        return;
                    }
                    // Ctrl+C with an active mouse selection → copy text to
                    // clipboard, clear selection, and DON'T forward SIGINT.
                    // No selection → fall through to PTY (normal SIGINT).
                    if state.input.modifiers.ctrl
                        && !state.input.modifiers.shift
                        && matches!(ks_raw, 0x43 | 0x63)
                    {
                        let surf_slot = crate::native_term::active_surface_slot();
                        let info_opt = surf_slot.lock().clone();
                        if let Some(info) = info_opt {
                            let mut g = info.grid.lock();
                            if let Some(text) = g.selection_text() {
                                if !text.is_empty() {
                                    g.selection = None;
                                    g.dirty = true;
                                    drop(g);
                                    let app_handle = state.app.clone();
                                    std::thread::spawn(move || {
                                        use tauri_plugin_clipboard_manager::ClipboardExt;
                                        let _ = app_handle.clipboard().write_text(text);
                                    });
                                    return;
                                }
                            }
                        }
                    }
                    // Ctrl+V → read clipboard + write its text to the PTY.
                    if state.input.modifiers.ctrl
                        && !state.input.modifiers.shift
                        && matches!(ks_raw, 0x56 | 0x76)
                    {
                        let app_handle = state.app.clone();
                        let writer_slot = state.writer_slot.clone();
                        std::thread::spawn(move || {
                            use tauri_plugin_clipboard_manager::ClipboardExt;
                            if let Ok(text) = app_handle.clipboard().read_text() {
                                let slot = writer_slot.lock();
                                if let Some(writer) = slot.as_ref() {
                                    let mut w = writer.lock();
                                    let _ = w.write_all(text.as_bytes());
                                    let _ = w.flush();
                                }
                            }
                        });
                        return;
                    }

                    let bytes = state.input.keysym_to_bytes(keysym, utf8_char);
                    eprintln!("[native-term-kb] keysym={keysym:?} utf8={utf8:?} bytes={bytes:?}");
                    if !bytes.is_empty() {
                        // Initial keystroke.
                        {
                            let slot = state.writer_slot.lock();
                            if let Some(writer) = slot.as_ref() {
                                let mut w = writer.lock();
                                let _ = w.write_all(&bytes);
                                let _ = w.flush();
                            }
                        }
                        // Cancel any prior repeater for a different key, then
                        // start a new one for this press.  Holding the key
                        // down sends `bytes` repeatedly at `repeat_rate` Hz
                        // after `repeat_delay` ms.
                        if let Some(r) = &state.repeat {
                            r.cancel
                                .store(true, std::sync::atomic::Ordering::SeqCst);
                        }
                        let cancel = std::sync::Arc::new(
                            std::sync::atomic::AtomicBool::new(false),
                        );
                        let cancel_for_task = cancel.clone();
                        let writer_slot = state.writer_slot.clone();
                        let bytes_for_task = bytes.clone();
                        let delay_ms = state.repeat_delay.max(0) as u64;
                        let interval_ms =
                            if state.repeat_rate > 0 { 1000 / state.repeat_rate as u64 } else { 40 };
                        std::thread::spawn(move || {
                            std::thread::sleep(std::time::Duration::from_millis(delay_ms));
                            while !cancel_for_task
                                .load(std::sync::atomic::Ordering::SeqCst)
                            {
                                {
                                    let slot = writer_slot.lock();
                                    if let Some(writer) = slot.as_ref() {
                                        let mut w = writer.lock();
                                        let _ = w.write_all(&bytes_for_task);
                                        let _ = w.flush();
                                    }
                                }
                                std::thread::sleep(std::time::Duration::from_millis(
                                    interval_ms,
                                ));
                            }
                        });
                        state.repeat = Some(RepeatState { keycode: key, cancel });
                    }
                }
            }

            wl_keyboard::Event::Key {
                key,
                state: WEnum::Value(wl_keyboard::KeyState::Released),
                ..
            } => {
                if let Some(r) = &state.repeat {
                    if r.keycode == key {
                        r.cancel.store(true, std::sync::atomic::Ordering::SeqCst);
                        state.repeat = None;
                    }
                }
            }

            wl_keyboard::Event::RepeatInfo { rate, delay } => {
                if rate > 0 {
                    state.repeat_rate = rate;
                }
                if delay > 0 {
                    state.repeat_delay = delay;
                }
            }

            wl_keyboard::Event::Modifiers {
                mods_depressed,
                mods_latched,
                mods_locked,
                group,
                ..
            } => {
                if let Some(xkb_state) = &mut state.xkb_state {
                    xkb_state.update_mask(
                        mods_depressed,
                        mods_latched,
                        mods_locked,
                        0,
                        0,
                        group,
                    );
                }
                // Mirror modifier state into InputHandler for escape-sequence logic.
                state.input.modifiers.shift = (mods_depressed & 0b0000_0001) != 0;
                state.input.modifiers.ctrl = (mods_depressed & 0b0000_0100) != 0;
                state.input.modifiers.alt = (mods_depressed & 0b0000_1000) != 0;
                state.input.modifiers.logo = (mods_depressed & 0b0100_0000) != 0;
            }

            _ => {}
        }
    }
}
