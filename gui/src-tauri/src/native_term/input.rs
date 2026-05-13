//! Keyboard input mapping. Pure logic for keysym → PTY byte sequence.
//!
//! Wayland event loop binding is in `subsurface.rs` and stitched together
//! by `commands.rs::native_term_attach` in D Task 17.

use xkbcommon::xkb::Keysym;

#[allow(dead_code)] // wired up in attach (D Task 14 + 17)
pub struct InputHandler {
    pub modifiers: Modifiers,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Modifiers {
    #[allow(dead_code)]
    pub shift: bool,
    pub ctrl: bool,
    pub alt: bool,
    #[allow(dead_code)]
    pub logo: bool,
}

#[allow(dead_code)] // wired up in attach (D Task 17)
impl InputHandler {
    pub fn new() -> Self {
        Self { modifiers: Modifiers::default() }
    }

    /// Map a keysym + current modifier state to a PTY byte sequence.
    /// Returns an empty Vec for keys with no terminal mapping (modifier keys, F-keys, etc.).
    pub fn keysym_to_bytes(&self, sym: Keysym, utf8: Option<char>) -> Vec<u8> {
        // Special keys first
        if sym == Keysym::Return { return b"\r".to_vec(); }
        if sym == Keysym::BackSpace { return vec![0x7f]; }
        if sym == Keysym::Tab { return b"\t".to_vec(); }
        if sym == Keysym::Escape { return vec![0x1b]; }
        if sym == Keysym::Up { return b"\x1b[A".to_vec(); }
        if sym == Keysym::Down { return b"\x1b[B".to_vec(); }
        if sym == Keysym::Right { return b"\x1b[C".to_vec(); }
        if sym == Keysym::Left { return b"\x1b[D".to_vec(); }
        if sym == Keysym::Home { return b"\x1b[H".to_vec(); }
        if sym == Keysym::End { return b"\x1b[F".to_vec(); }
        if sym == Keysym::Page_Up { return b"\x1b[5~".to_vec(); }
        if sym == Keysym::Page_Down { return b"\x1b[6~".to_vec(); }
        if sym == Keysym::Delete { return b"\x1b[3~".to_vec(); }

        // Regular char with modifier handling
        if let Some(c) = utf8 {
            // Ctrl + letter → control byte
            if self.modifiers.ctrl && c.is_ascii_alphabetic() {
                let base = c.to_ascii_lowercase() as u8;
                return vec![base - b'a' + 1];
            }
            // Alt + char → ESC + char
            if self.modifiers.alt {
                let mut out = vec![0x1b];
                out.extend(c.to_string().into_bytes());
                return out;
            }
            return c.to_string().into_bytes();
        }
        Vec::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use xkbcommon::xkb::Keysym;

    fn ksym(c: char) -> Keysym {
        // Latin letters in xkbcommon are the unicode codepoint with the high bit set
        // for non-ASCII. ASCII letters have keysyms equal to their ASCII byte value.
        Keysym::new(c as u32)
    }

    #[test]
    fn input_arrow_up_emits_csi_a() {
        let h = InputHandler::new();
        assert_eq!(h.keysym_to_bytes(Keysym::Up, None), b"\x1b[A".to_vec());
    }

    #[test]
    fn input_enter_emits_cr() {
        let h = InputHandler::new();
        assert_eq!(h.keysym_to_bytes(Keysym::Return, None), b"\r".to_vec());
    }

    #[test]
    fn input_backspace_emits_del() {
        let h = InputHandler::new();
        assert_eq!(h.keysym_to_bytes(Keysym::BackSpace, None), vec![0x7f]);
    }

    #[test]
    fn input_ctrl_c_emits_etx() {
        let mut h = InputHandler::new();
        h.modifiers.ctrl = true;
        assert_eq!(h.keysym_to_bytes(ksym('c'), Some('c')), vec![0x03]);
    }

    #[test]
    fn input_alt_b_emits_esc_b() {
        let mut h = InputHandler::new();
        h.modifiers.alt = true;
        assert_eq!(h.keysym_to_bytes(ksym('b'), Some('b')), b"\x1bb".to_vec());
    }

    #[test]
    fn input_plain_letter_passes_through() {
        let h = InputHandler::new();
        assert_eq!(h.keysym_to_bytes(ksym('a'), Some('a')), b"a".to_vec());
    }
}
