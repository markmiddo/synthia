//! Wayland keyboard binding for the native renderer.
//!
//! Spawned as a blocking task by `commands::native_term_attach`. Owns its
//! own EventQueue + KeyboardState. Translates wl_keyboard events into PTY
//! byte sequences via the existing InputHandler.

use std::io::Read as _;
use std::sync::Arc;

use parking_lot::Mutex;
use wayland_client::{
    protocol::{wl_keyboard, wl_registry, wl_seat},
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
#[allow(dead_code)] // wired up in commands.rs (D Task 17)
pub fn run_keyboard_loop(
    conn: Connection,
    writer: Arc<Mutex<Box<dyn std::io::Write + Send>>>,
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
        writer,
        seat: None,
        keyboard_obtained: false,
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
    writer: Arc<Mutex<Box<dyn std::io::Write + Send>>>,
    /// The bound wl_seat (kept alive so the keyboard object isn't destroyed).
    seat: Option<wl_seat::WlSeat>,
    /// Set to true once `get_keyboard()` has been called.
    keyboard_obtained: bool,
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
                state.seat = Some(seat);
            }
        }
    }
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
                let mut file = std::fs::File::from(fd);

                // The keymap is a null-terminated XKB text string of `size` bytes.
                let read_len = (size as usize).saturating_sub(1);
                let mut buf = vec![0u8; read_len];
                if file.read_exact(&mut buf).is_ok() {
                    if let Ok(s) = std::str::from_utf8(&buf) {
                        let keymap = xkb::Keymap::new_from_string(
                            &state.xkb_ctx,
                            s.to_string(),
                            xkb::KEYMAP_FORMAT_TEXT_V1,
                            xkb::KEYMAP_COMPILE_NO_FLAGS,
                        );
                        if let Some(km) = keymap {
                            state.xkb_state = Some(xkb::State::new(&km));
                            state.keymap = Some(km);
                        }
                    }
                }
                // File is dropped here, closing the fd — safe now that we've
                // read what we need.
            }

            wl_keyboard::Event::Key {
                key,
                state: WEnum::Value(wl_keyboard::KeyState::Pressed),
                ..
            } => {
                if let Some(xkb_state) = &state.xkb_state {
                    // evdev keycodes are offset by 8 vs XKB keycodes.
                    let keycode = xkb::Keycode::new(key + 8);
                    let keysym = xkb_state.key_get_one_sym(keycode);
                    let utf8 = xkb_state.key_get_utf8(keycode);
                    let utf8_char = utf8.chars().next();
                    let bytes = state.input.keysym_to_bytes(keysym, utf8_char);
                    if !bytes.is_empty() {
                        let mut w = state.writer.lock();
                        let _ = w.write_all(&bytes);
                        let _ = w.flush();
                    }
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
