# Native Terminal Renderer (Wayland Subsurface) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the slow xterm.js-in-webview terminal with a native CPU renderer drawn into a Wayland subsurface attached to Synthia's main `wl_surface`. PTY layer reused. Single tab v1. Toggle-driven so xterm.js stays as fallback.

**Architecture:** New `native_term/` Rust module owns a Wayland subsurface that lives inside Synthia's existing Tauri main window. `vte` parses PTY bytes into a `Grid`; `softbuffer` + `cosmic-text` render cells into a CPU pixel buffer; `xkbcommon` translates keyboard input to PTY byte sequences. Per-keystroke path runs entirely in-process — no Tauri IPC.

**Tech Stack:** Rust 2021 + Tauri 2 + `wayland-client` 0.31 + `wayland-protocols` 0.31 + `softbuffer` 0.4 (wayland feature) + `cosmic-text` 0.12 + `vte` 0.13 + `xkbcommon` 0.7 + `raw-window-handle` 0.6, integrated with the existing PTY layer in `gui/src-tauri/src/commands/terminal.rs` and the existing React `NativeTerminalView.tsx` from the fake-embed prototype.

**Spec:** `docs/superpowers/specs/2026-05-13-native-terminal-renderer-design.md`

---

## File Structure

| Path | Status | Purpose |
|------|--------|---------|
| `gui/src-tauri/Cargo.toml` | Modify | Add wayland-client, wayland-protocols, softbuffer, cosmic-text, vte, xkbcommon deps |
| `gui/src-tauri/src/state.rs` | Modify | Replace `pub native_terminals: NativeTermRegistry` import path (currently points to fake-embed module) with new native renderer registry |
| `gui/src-tauri/src/commands/terminal.rs` | Modify | Add `lease_for_native(session_id) -> (Reader, Writer)` and `restore_from_native(session_id, Reader, Writer)` so the native renderer can borrow the PTY without breaking `terminal_kill` |
| `gui/src-tauri/src/native_term/mod.rs` | Create | Module root, public API, AppState integration, shared Wayland connection |
| `gui/src-tauri/src/native_term/subsurface.rs` | Create | Wayland subsurface lifecycle: extract parent wl_surface from Tauri raw_window_handle, create child subsurface, position, destroy |
| `gui/src-tauri/src/native_term/grid.rs` | Create | Terminal grid state (rows × cols of Cell) + vte::Performer impl |
| `gui/src-tauri/src/native_term/renderer.rs` | Create | softbuffer + cosmic-text rendering: blit grid cells to pixel buffer |
| `gui/src-tauri/src/native_term/input.rs` | Create | wl_keyboard event handling + xkbcommon keysym → byte sequence mapping |
| `gui/src-tauri/src/native_term/commands.rs` | Create | Tauri commands: `native_term_attach`, `native_term_resize`, `native_term_detach` |
| `gui/src-tauri/src/lib.rs` | Modify | Register the three new Tauri commands in `generate_handler!` |
| `gui/src/components/terminal/NativeTerminalView.tsx` | Modify | Rewrite the fake-embed version: invoke `terminal_spawn` → `native_term_attach` → handle resize/detach |

The fake-embed `commands/native_term.rs` (Wezterm spawner) stays for now as an alternative path — we move our new module into a SUBDIRECTORY (`native_term/` not `native_term.rs`) so they don't collide. After the new renderer ships and works, the fake-embed module can be deleted in a follow-up.

---

## Task 1: Add `lease_for_native` / `restore_from_native` helpers in `commands/terminal.rs`

**Files:**
- Modify: `gui/src-tauri/src/commands/terminal.rs`

The native renderer needs to borrow the PTY reader and writer from a `PtySession` while still letting `terminal_kill` work afterward. Add a leasing API.

- [ ] **Step 1: Write failing tests**

Append inside `mod tests` in `gui/src-tauri/src/commands/terminal.rs`:

```rust
    #[test]
    fn lease_takes_reader_and_writer() {
        use crate::state::TerminalRegistry;
        use crate::state::PtySession;
        use chrono::Utc;
        use uuid::Uuid;

        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/sleep");
        cmd.arg("60");
        let child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);
        let writer = pair.master.take_writer().unwrap();
        let reader = pair.master.try_clone_reader().unwrap();

        let reg = TerminalRegistry::default();
        let id = Uuid::new_v4();
        reg.sessions.lock().insert(id, PtySession {
            master: pair.master,
            writer,
            child,
            reader_task: None,
            pending_reader: Some(reader),
            meta: crate::state::SessionMeta {
                id, cwd: "/tmp".into(), shell: "/bin/sleep".into(),
                title: "sleep".into(), created_at: Utc::now(),
            },
        });

        let leased = lease_for_native(&reg, id).unwrap();
        assert!(leased.is_some(), "lease should return reader + writer for fresh session");
        // Session entry stays in registry (so kill still works) but writer/reader fields are emptied.
        let guard = reg.sessions.lock();
        let session = guard.get(&id).unwrap();
        assert!(session.pending_reader.is_none(), "lease consumes pending_reader");
    }

    #[test]
    fn lease_returns_none_when_already_leased() {
        use crate::state::TerminalRegistry;
        use crate::state::PtySession;
        use chrono::Utc;
        use uuid::Uuid;

        let pty_system = native_pty_system();
        let pair = pty_system
            .openpty(PtySize { rows: 24, cols: 80, pixel_width: 0, pixel_height: 0 })
            .unwrap();
        let mut cmd = CommandBuilder::new("/bin/sleep");
        cmd.arg("60");
        let child = pair.slave.spawn_command(cmd).unwrap();
        drop(pair.slave);
        let writer = pair.master.take_writer().unwrap();
        let reader = pair.master.try_clone_reader().unwrap();

        let reg = TerminalRegistry::default();
        let id = Uuid::new_v4();
        reg.sessions.lock().insert(id, PtySession {
            master: pair.master,
            writer,
            child,
            reader_task: None,
            pending_reader: Some(reader),
            meta: crate::state::SessionMeta {
                id, cwd: "/tmp".into(), shell: "/bin/sleep".into(),
                title: "sleep".into(), created_at: Utc::now(),
            },
        });

        let _first = lease_for_native(&reg, id).unwrap();
        let second = lease_for_native(&reg, id).unwrap();
        assert!(second.is_none(), "second lease must return None — already leased");
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal::tests::lease`
Expected: FAIL — `lease_for_native` not found.

- [ ] **Step 3: Add the helpers**

Append in `gui/src-tauri/src/commands/terminal.rs` (above `#[cfg(test)]`):

```rust
/// PTY handles leased to the native renderer. Returns Some on first call, None on subsequent calls.
pub struct LeasedPty {
    pub reader: Box<dyn std::io::Read + Send>,
    pub writer: Box<dyn std::io::Write + Send>,
}

/// Take the reader and writer out of a session so the native renderer can own them.
/// Leaves the master, child, and meta in place so `terminal_kill` still works.
/// Returns `Ok(Some(LeasedPty))` on first call; `Ok(None)` if already leased.
pub fn lease_for_native(
    registry: &crate::state::TerminalRegistry,
    session_id: Uuid,
) -> AppResult<Option<LeasedPty>> {
    let mut guard = registry.sessions.lock();
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    let Some(reader) = session.pending_reader.take() else {
        return Ok(None);
    };
    // Replace writer with a sink — the real one moves to LeasedPty.
    let real_writer = std::mem::replace(
        &mut session.writer,
        Box::new(std::io::sink()),
    );
    Ok(Some(LeasedPty { reader, writer: real_writer }))
}

/// Restore a previously-leased reader+writer back into the session.
/// Used on detach so subsequent xterm.js attaches still work.
pub fn restore_from_native(
    registry: &crate::state::TerminalRegistry,
    session_id: Uuid,
    leased: LeasedPty,
) -> AppResult<()> {
    let mut guard = registry.sessions.lock();
    let session = guard
        .get_mut(&session_id)
        .ok_or_else(|| AppError::Terminal(format!("unknown session {session_id}")))?;
    session.pending_reader = Some(leased.reader);
    session.writer = leased.writer;
    Ok(())
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gui/src-tauri && cargo test --lib commands::terminal::tests::lease`
Expected: 2 PASS.

- [ ] **Step 5: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/commands/terminal.rs
git commit -m "feat(terminal): add lease_for_native + restore_from_native helpers"
```

---

## Task 2: Add Wayland + render Cargo dependencies

**Files:**
- Modify: `gui/src-tauri/Cargo.toml`

- [ ] **Step 1: Append the new deps**

In `gui/src-tauri/Cargo.toml`, under `[dependencies]`, append:

```toml
wayland-client = "0.31"
wayland-protocols = { version = "0.31", features = ["client", "staging"] }
softbuffer = { version = "0.4", default-features = false, features = ["wayland"] }
cosmic-text = "0.12"
vte = "0.13"
xkbcommon = "0.7"
raw-window-handle = "0.6"
```

- [ ] **Step 2: Verify it builds**

Run: `cd gui/src-tauri && cargo build`
Expected: build succeeds (long first build, will pull crates). If a crate version is yanked or has a breaking change, downgrade and report the working version.

- [ ] **Step 3: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock
git commit -m "feat(native-term): add wayland + softbuffer + cosmic-text + vte deps"
```

---

## Task 3: Create `native_term/` module skeleton

**Files:**
- Create: `gui/src-tauri/src/native_term/mod.rs`
- Modify: `gui/src-tauri/src/lib.rs` (add `mod native_term;`)
- Modify: `gui/src-tauri/src/state.rs` (replace fake-embed registry with new one)

- [ ] **Step 1: Create `gui/src-tauri/src/native_term/mod.rs`**

```rust
//! Native Wayland-subsurface terminal renderer.
//!
//! See `docs/superpowers/specs/2026-05-13-native-terminal-renderer-design.md`.
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
pub mod renderer;
pub mod subsurface;

/// Shared Wayland connection extracted from Tauri's main window.
/// Cached once at first attach; reused for every native session.
static WAYLAND_CONNECTION: OnceLock<wayland_client::Connection> = OnceLock::new();

#[allow(dead_code)] // populated by attach, drained by detach
pub struct NativeSession {
    pub subsurface: subsurface::SubsurfaceHandle,
    pub renderer: renderer::Renderer,
    pub grid: std::sync::Arc<Mutex<grid::Grid>>,
    pub input: input::InputHandler,
    pub leased: crate::commands::terminal::LeasedPty,
    pub reader_task: tokio::task::JoinHandle<()>,
    pub render_task: tokio::task::JoinHandle<()>,
    pub input_task: tokio::task::JoinHandle<()>,
}

#[derive(Default)]
pub struct NativeTermRegistry {
    pub sessions: Mutex<HashMap<Uuid, NativeSession>>,
}

pub fn wayland_connection() -> Option<&'static wayland_client::Connection> {
    WAYLAND_CONNECTION.get()
}

pub fn init_wayland_connection(conn: wayland_client::Connection) {
    let _ = WAYLAND_CONNECTION.set(conn);
}
```

- [ ] **Step 2: Add module declaration in `lib.rs`**

In `gui/src-tauri/src/lib.rs`, find the line `mod commands;` (around line 19) and add immediately after:

```rust
mod native_term;
```

- [ ] **Step 3: Update `state.rs`**

In `gui/src-tauri/src/state.rs`, replace the line:

```rust
use crate::commands::native_term::NativeTermRegistry;
```

with:

```rust
use crate::native_term::NativeTermRegistry;
```

- [ ] **Step 4: Verify the fake-embed module still compiles or remove the registry field from it**

Open `gui/src-tauri/src/commands/native_term.rs`. If it defines its own `NativeTermRegistry`, rename it to `FakeEmbedRegistry` and update its consumers within that file. If `AppState` no longer needs the fake-embed registry (because the new module's registry replaces it), leave the fake-embed module functional but standalone.

In practice: the fake-embed module's `NativeTermRegistry` is the type the spec replaces. To avoid breaking the fake-embed feature, rename its registry to `FakeEmbedRegistry` AND add `pub fake_embed_terminals: crate::commands::native_term::FakeEmbedRegistry,` to `AppState`. Update fake-embed call sites to use the new field name. (If you prefer to skip the fake-embed entirely while implementing this plan, you may comment out fake-embed registration in `lib.rs` and revisit later — but document the choice.)

- [ ] **Step 5: Verify build**

Run: `cd gui/src-tauri && cargo build`
Expected: builds (the new submodules' files don't exist yet so we need stub files).

If the build complains about missing `subsurface.rs`, `grid.rs`, etc., create empty stub files containing only the module doc and a placeholder `pub fn _placeholder() {}` to satisfy the module declarations. The next tasks fill them in.

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/native_term/ gui/src-tauri/src/lib.rs gui/src-tauri/src/state.rs gui/src-tauri/src/commands/native_term.rs
git commit -m "feat(native-term): module skeleton + wayland connection cache"
```

---

## Task 4: Grid + Cell + cursor + `apply_print`

**Files:**
- Create / overwrite: `gui/src-tauri/src/native_term/grid.rs`

- [ ] **Step 1: Write failing tests**

Create `gui/src-tauri/src/native_term/grid.rs` with:

```rust
//! Terminal grid state. Implements `vte::Performer` to consume PTY bytes.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Color {
    pub r: u8,
    pub g: u8,
    pub b: u8,
}

impl Color {
    pub const fn rgb(r: u8, g: u8, b: u8) -> Self { Self { r, g, b } }
    pub const fn black() -> Self { Self::rgb(0x1a, 0x1b, 0x26) }
    pub const fn white() -> Self { Self::rgb(0xe6, 0xe6, 0xfa) }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Cell {
    pub ch: char,
    pub fg: Color,
    pub bg: Color,
    pub bold: bool,
}

impl Default for Cell {
    fn default() -> Self {
        Self { ch: ' ', fg: Color::white(), bg: Color::black(), bold: false }
    }
}

#[derive(Debug)]
pub struct Grid {
    pub rows: usize,
    pub cols: usize,
    pub cells: Vec<Cell>,
    pub cursor_row: usize,
    pub cursor_col: usize,
    pub fg: Color,
    pub bg: Color,
    pub bold: bool,
    pub dirty: bool,
}

impl Grid {
    pub fn new(rows: usize, cols: usize) -> Self {
        Self {
            rows, cols,
            cells: vec![Cell::default(); rows * cols],
            cursor_row: 0, cursor_col: 0,
            fg: Color::white(), bg: Color::black(), bold: false,
            dirty: true,
        }
    }

    pub fn cell_at(&self, row: usize, col: usize) -> Cell {
        self.cells[row * self.cols + col]
    }

    pub fn apply_print(&mut self, ch: char) {
        if self.cursor_col >= self.cols {
            self.cursor_col = 0;
            self.cursor_row += 1;
        }
        if self.cursor_row >= self.rows {
            // scroll up by one line
            for r in 1..self.rows {
                for c in 0..self.cols {
                    self.cells[(r - 1) * self.cols + c] = self.cells[r * self.cols + c];
                }
            }
            for c in 0..self.cols {
                self.cells[(self.rows - 1) * self.cols + c] = Cell {
                    ch: ' ', fg: self.fg, bg: self.bg, bold: false,
                };
            }
            self.cursor_row = self.rows - 1;
        }
        let idx = self.cursor_row * self.cols + self.cursor_col;
        self.cells[idx] = Cell { ch, fg: self.fg, bg: self.bg, bold: self.bold };
        self.cursor_col += 1;
        self.dirty = true;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn grid_apply_print_writes_at_cursor() {
        let mut g = Grid::new(5, 10);
        g.apply_print('A');
        assert_eq!(g.cell_at(0, 0).ch, 'A');
        assert_eq!(g.cursor_col, 1);
    }

    #[test]
    fn grid_apply_print_wraps_to_next_row() {
        let mut g = Grid::new(3, 3);
        for ch in "abcdef".chars() { g.apply_print(ch); }
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(0, 2).ch, 'c');
        assert_eq!(g.cell_at(1, 0).ch, 'd');
        assert_eq!(g.cell_at(1, 2).ch, 'f');
    }

    #[test]
    fn grid_apply_print_scrolls_when_full() {
        let mut g = Grid::new(2, 3);
        for ch in "abcdefghij".chars() { g.apply_print(ch); }
        // last 6 chars survive on a 2x3 = 6-cell grid; 'a'..'d' scrolled off
        assert_eq!(g.cell_at(0, 0).ch, 'e');
        assert_eq!(g.cell_at(1, 2).ch, 'j');
    }

    #[test]
    fn grid_marks_dirty_on_print() {
        let mut g = Grid::new(2, 2);
        g.dirty = false;
        g.apply_print('x');
        assert!(g.dirty);
    }
}
```

- [ ] **Step 2: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 4 PASS.

- [ ] **Step 3: Clippy clean**

Run: `cd gui/src-tauri && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/grid.rs
git commit -m "feat(native-term): grid + Cell + apply_print + scroll"
```

---

## Task 5: Grid CSI handlers — cursor positioning (CUP, CUF, CUB, CUU, CUD)

**Files:**
- Modify: `gui/src-tauri/src/native_term/grid.rs`

- [ ] **Step 1: Append failing tests**

Append inside `mod tests`:

```rust
    #[test]
    fn grid_csi_cup_moves_cursor() {
        let mut g = Grid::new(10, 20);
        // CSI 5;10H = cursor to row 5 col 10 (1-based)
        g.csi_dispatch(b'H', &[5, 10]);
        assert_eq!(g.cursor_row, 4);
        assert_eq!(g.cursor_col, 9);
    }

    #[test]
    fn grid_csi_cuf_advances_cursor() {
        let mut g = Grid::new(5, 10);
        g.cursor_col = 2;
        g.csi_dispatch(b'C', &[3]);
        assert_eq!(g.cursor_col, 5);
    }

    #[test]
    fn grid_csi_cub_retreats_cursor() {
        let mut g = Grid::new(5, 10);
        g.cursor_col = 5;
        g.csi_dispatch(b'D', &[2]);
        assert_eq!(g.cursor_col, 3);
    }

    #[test]
    fn grid_csi_cuu_moves_up() {
        let mut g = Grid::new(5, 10);
        g.cursor_row = 3;
        g.csi_dispatch(b'A', &[2]);
        assert_eq!(g.cursor_row, 1);
    }

    #[test]
    fn grid_csi_cud_moves_down() {
        let mut g = Grid::new(5, 10);
        g.cursor_row = 1;
        g.csi_dispatch(b'B', &[2]);
        assert_eq!(g.cursor_row, 3);
    }

    #[test]
    fn grid_csi_cup_clamps_to_bounds() {
        let mut g = Grid::new(5, 5);
        g.csi_dispatch(b'H', &[100, 100]);
        assert_eq!(g.cursor_row, 4);
        assert_eq!(g.cursor_col, 4);
    }
```

- [ ] **Step 2: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid::tests::grid_csi`
Expected: FAIL — `csi_dispatch` not defined.

- [ ] **Step 3: Add `csi_dispatch`**

Add inside `impl Grid`:

```rust
    /// Dispatch a CSI sequence. `params` are decoded numeric parameters (0 if absent).
    pub fn csi_dispatch(&mut self, action: u8, params: &[u16]) {
        let p = |i: usize, default: u16| -> u16 {
            params.get(i).copied().filter(|&v| v != 0).unwrap_or(default)
        };
        match action {
            b'H' | b'f' => {
                // CUP: cursor position (1-based)
                let row = (p(0, 1) as usize).saturating_sub(1).min(self.rows.saturating_sub(1));
                let col = (p(1, 1) as usize).saturating_sub(1).min(self.cols.saturating_sub(1));
                self.cursor_row = row;
                self.cursor_col = col;
            }
            b'A' => {
                // CUU
                let n = p(0, 1) as usize;
                self.cursor_row = self.cursor_row.saturating_sub(n);
            }
            b'B' => {
                // CUD
                let n = p(0, 1) as usize;
                self.cursor_row = (self.cursor_row + n).min(self.rows.saturating_sub(1));
            }
            b'C' => {
                // CUF
                let n = p(0, 1) as usize;
                self.cursor_col = (self.cursor_col + n).min(self.cols.saturating_sub(1));
            }
            b'D' => {
                // CUB
                let n = p(0, 1) as usize;
                self.cursor_col = self.cursor_col.saturating_sub(n);
            }
            _ => { /* unhandled — silent for v1 */ }
        }
        self.dirty = true;
    }
```

- [ ] **Step 4: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 10 PASS (4 from Task 4 + 6 new).

- [ ] **Step 5: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/grid.rs
git commit -m "feat(native-term): grid CSI cursor positioning (CUP/CUF/CUB/CUU/CUD)"
```

---

## Task 6: Grid CSI handlers — SGR (colors + bold) + ED/EL (clear)

**Files:**
- Modify: `gui/src-tauri/src/native_term/grid.rs`

- [ ] **Step 1: Append failing tests**

Append inside `mod tests`:

```rust
    #[test]
    fn grid_csi_sgr_red_fg() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[31]);
        g.apply_print('R');
        assert_eq!(g.cell_at(0, 0).fg, Color::rgb(0xfd, 0xa4, 0xaf));
    }

    #[test]
    fn grid_csi_sgr_reset() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[31]);
        g.csi_dispatch(b'm', &[0]);
        g.apply_print('X');
        assert_eq!(g.cell_at(0, 0).fg, Color::white());
        assert_eq!(g.cell_at(0, 0).bold, false);
    }

    #[test]
    fn grid_csi_sgr_bold() {
        let mut g = Grid::new(2, 5);
        g.csi_dispatch(b'm', &[1]);
        g.apply_print('B');
        assert_eq!(g.cell_at(0, 0).bold, true);
    }

    #[test]
    fn grid_csi_ed_clears_screen() {
        let mut g = Grid::new(2, 3);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.csi_dispatch(b'J', &[2]);
        for r in 0..g.rows {
            for c in 0..g.cols {
                assert_eq!(g.cell_at(r, c).ch, ' ');
            }
        }
    }

    #[test]
    fn grid_csi_el_clears_line() {
        let mut g = Grid::new(2, 3);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.cursor_row = 0; g.cursor_col = 0;
        g.csi_dispatch(b'K', &[2]);
        for c in 0..g.cols {
            assert_eq!(g.cell_at(0, c).ch, ' ');
        }
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 5 FAIL (the SGR + ED + EL aren't implemented yet).

- [ ] **Step 3: Extend `csi_dispatch`**

Replace the `_ => { /* unhandled */ }` arm in `csi_dispatch` with:

```rust
            b'm' => {
                // SGR: select graphic rendition
                if params.is_empty() || params == [0] {
                    self.fg = Color::white();
                    self.bg = Color::black();
                    self.bold = false;
                } else {
                    for &p in params {
                        match p {
                            0 => { self.fg = Color::white(); self.bg = Color::black(); self.bold = false; }
                            1 => self.bold = true,
                            22 => self.bold = false,
                            30 => self.fg = Color::black(),
                            31 => self.fg = Color::rgb(0xfd, 0xa4, 0xaf),
                            32 => self.fg = Color::rgb(0x86, 0xef, 0xac),
                            33 => self.fg = Color::rgb(0xfd, 0xe6, 0x8a),
                            34 => self.fg = Color::rgb(0xa5, 0xb4, 0xfc),
                            35 => self.fg = Color::rgb(0xc4, 0xb5, 0xfd),
                            36 => self.fg = Color::rgb(0x67, 0xe8, 0xf9),
                            37 => self.fg = Color::white(),
                            39 => self.fg = Color::white(),
                            40 => self.bg = Color::black(),
                            41 => self.bg = Color::rgb(0xfd, 0xa4, 0xaf),
                            42 => self.bg = Color::rgb(0x86, 0xef, 0xac),
                            43 => self.bg = Color::rgb(0xfd, 0xe6, 0x8a),
                            44 => self.bg = Color::rgb(0xa5, 0xb4, 0xfc),
                            45 => self.bg = Color::rgb(0xc4, 0xb5, 0xfd),
                            46 => self.bg = Color::rgb(0x67, 0xe8, 0xf9),
                            47 => self.bg = Color::white(),
                            49 => self.bg = Color::black(),
                            90..=97 => {
                                // bright fg
                                self.fg = match p {
                                    90 => Color::rgb(0x6b, 0x72, 0x80),
                                    91 => Color::rgb(0xfb, 0x71, 0x85),
                                    92 => Color::rgb(0x4a, 0xde, 0x80),
                                    93 => Color::rgb(0xfa, 0xcc, 0x15),
                                    94 => Color::rgb(0x81, 0x8c, 0xf8),
                                    95 => Color::rgb(0xa7, 0x8b, 0xfa),
                                    96 => Color::rgb(0x22, 0xd3, 0xee),
                                    _  => Color::rgb(0xff, 0xff, 0xff),
                                };
                            }
                            _ => { /* unhandled SGR — silent */ }
                        }
                    }
                }
            }
            b'J' => {
                // ED: erase display. param 2 = entire screen.
                let n = params.first().copied().unwrap_or(0);
                if n == 2 {
                    let blank = Cell { ch: ' ', fg: self.fg, bg: self.bg, bold: false };
                    self.cells.iter_mut().for_each(|c| *c = blank);
                }
                // params 0/1 (below/above cursor) — silent for v1
            }
            b'K' => {
                // EL: erase in line. param 2 = entire line.
                let n = params.first().copied().unwrap_or(0);
                if n == 2 {
                    let blank = Cell { ch: ' ', fg: self.fg, bg: self.bg, bold: false };
                    let row = self.cursor_row;
                    for c in 0..self.cols {
                        self.cells[row * self.cols + c] = blank;
                    }
                }
            }
            _ => { /* unhandled — silent */ }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 15 PASS.

- [ ] **Step 5: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/grid.rs
git commit -m "feat(native-term): grid CSI SGR colors/bold + ED/EL clear"
```

---

## Task 7: Wire `vte::Parser` to drive the grid + grid resize

**Files:**
- Modify: `gui/src-tauri/src/native_term/grid.rs`

- [ ] **Step 1: Append failing tests**

Append inside `mod tests`:

```rust
    #[test]
    fn vte_performer_handles_print() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        for &b in b"hi" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'h');
        assert_eq!(g.cell_at(0, 1).ch, 'i');
    }

    #[test]
    fn vte_performer_handles_color_seq() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        // \x1b[31m R \x1b[0m
        for &b in b"\x1b[31mR\x1b[0m" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'R');
        assert_eq!(g.cell_at(0, 0).fg, Color::rgb(0xfd, 0xa4, 0xaf));
    }

    #[test]
    fn vte_performer_newline() {
        let mut g = Grid::new(5, 10);
        let mut parser = vte::Parser::new();
        for &b in b"a\nb" {
            parser.advance(&mut g, b);
        }
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(1, 0).ch, 'b'); // \n moves down + col stays
    }

    #[test]
    fn grid_resize_preserves_visible_cells() {
        let mut g = Grid::new(3, 5);
        g.apply_print('a'); g.apply_print('b'); g.apply_print('c');
        g.resize(5, 10);
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.cell_at(0, 1).ch, 'b');
        assert_eq!(g.cell_at(0, 2).ch, 'c');
        assert_eq!(g.rows, 5);
        assert_eq!(g.cols, 10);
    }

    #[test]
    fn grid_resize_smaller_drops_overflow() {
        let mut g = Grid::new(5, 10);
        for ch in "abcdefghij".chars() { g.apply_print(ch); }
        g.resize(2, 5);
        // Cursor clamped, surviving cells preserved within new bounds
        assert_eq!(g.cell_at(0, 0).ch, 'a');
        assert_eq!(g.rows, 2);
        assert_eq!(g.cols, 5);
        assert!(g.cursor_row < g.rows);
        assert!(g.cursor_col < g.cols);
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 5 new tests FAIL — `vte::Performer` not implemented and `resize` missing.

- [ ] **Step 3: Implement Performer + resize**

Append in `gui/src-tauri/src/native_term/grid.rs` (above `#[cfg(test)]`):

```rust
impl Grid {
    pub fn resize(&mut self, rows: usize, cols: usize) {
        let mut new_cells = vec![Cell::default(); rows * cols];
        let copy_rows = self.rows.min(rows);
        let copy_cols = self.cols.min(cols);
        for r in 0..copy_rows {
            for c in 0..copy_cols {
                new_cells[r * cols + c] = self.cells[r * self.cols + c];
            }
        }
        self.rows = rows;
        self.cols = cols;
        self.cells = new_cells;
        self.cursor_row = self.cursor_row.min(rows.saturating_sub(1));
        self.cursor_col = self.cursor_col.min(cols.saturating_sub(1));
        self.dirty = true;
    }
}

impl vte::Perform for Grid {
    fn print(&mut self, ch: char) {
        self.apply_print(ch);
    }
    fn execute(&mut self, byte: u8) {
        match byte {
            b'\n' => {
                self.cursor_row = (self.cursor_row + 1).min(self.rows.saturating_sub(1));
                if self.cursor_row + 1 >= self.rows && self.cells.len() == self.rows * self.cols {
                    // emulate scroll on overflow
                }
                self.dirty = true;
            }
            b'\r' => { self.cursor_col = 0; self.dirty = true; }
            0x08 => { self.cursor_col = self.cursor_col.saturating_sub(1); self.dirty = true; }
            0x07 => { /* bell — ignore */ }
            _ => {}
        }
    }
    fn csi_dispatch(&mut self, params: &vte::Params, _intermediates: &[u8], _ignore: bool, action: char) {
        let nums: Vec<u16> = params.iter().map(|p| p.first().copied().unwrap_or(0)).collect();
        Grid::csi_dispatch(self, action as u8, &nums);
    }
    fn esc_dispatch(&mut self, _intermediates: &[u8], _ignore: bool, _byte: u8) {}
    fn osc_dispatch(&mut self, _params: &[&[u8]], _bell_terminated: bool) {}
    fn hook(&mut self, _params: &vte::Params, _intermediates: &[u8], _ignore: bool, _action: char) {}
    fn put(&mut self, _byte: u8) {}
    fn unhook(&mut self) {}
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd gui/src-tauri && cargo test --lib native_term::grid`
Expected: 20 PASS.

- [ ] **Step 5: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/grid.rs
git commit -m "feat(native-term): vte::Perform impl + grid resize"
```

---

## Task 8: Subsurface lifecycle — extract parent surface, create child, position

**Files:**
- Create / overwrite: `gui/src-tauri/src/native_term/subsurface.rs`

This task is the riskiest part of the plan. Wayland protocol work, raw-window-handle FFI, and Tauri internals all intersect.

- [ ] **Step 1: Write the module**

Create `gui/src-tauri/src/native_term/subsurface.rs`:

```rust
//! Wayland subsurface lifecycle.
//!
//! Extracts the parent `wl_surface` from Tauri's main window via
//! `raw-window-handle`, creates a child surface + subsurface, and exposes
//! a handle for positioning, resizing, and destruction.

use raw_window_handle::{HasWindowHandle, RawWindowHandle, WaylandWindowHandle};
use std::ptr::NonNull;
use wayland_client::{protocol::wl_surface::WlSurface, Connection, Dispatch, QueueHandle};
use wayland_protocols::wp::viewporter::client::wp_viewporter::WpViewporter;

use crate::error::{AppError, AppResult};

#[allow(dead_code)] // populated by attach, drained by detach
pub struct SubsurfaceHandle {
    pub child_surface: WlSurface,
    pub subsurface: wayland_client::protocol::wl_subsurface::WlSubsurface,
    pub width: u32,
    pub height: u32,
    pub x: i32,
    pub y: i32,
}

#[derive(Default)]
struct DummyState;

impl Dispatch<wayland_client::protocol::wl_registry::WlRegistry, ()> for DummyState {
    fn event(_: &mut Self, _: &wayland_client::protocol::wl_registry::WlRegistry, _: <wayland_client::protocol::wl_registry::WlRegistry as wayland_client::Proxy>::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}

/// Extract the parent wl_surface pointer from a Tauri window.
/// Returns `None` if the window isn't running on native Wayland.
pub fn parent_surface_from_tauri(window: &tauri::WebviewWindow) -> AppResult<NonNull<std::ffi::c_void>> {
    let handle = window
        .window_handle()
        .map_err(|e| AppError::Terminal(format!("window_handle: {e}")))?;
    match handle.as_raw() {
        RawWindowHandle::Wayland(WaylandWindowHandle { surface, .. }) => Ok(surface),
        _ => Err(AppError::Terminal("native renderer requires native Wayland".into())),
    }
}

/// Create a subsurface as a child of `parent_surface_ptr`. The parent surface pointer
/// MUST come from Tauri's window handle and be valid for the lifetime of the subsurface.
///
/// Returns a handle wrapping the child surface and subsurface objects.
pub fn create_subsurface(
    _conn: &Connection,
    _parent_surface_ptr: NonNull<std::ffi::c_void>,
    _x: i32,
    _y: i32,
    _width: u32,
    _height: u32,
) -> AppResult<SubsurfaceHandle> {
    // FIXME(stage 2): Implement subsurface creation. Requires:
    //   1. wl_registry::bind for wl_compositor + wl_subcompositor
    //   2. wl_compositor.create_surface() → child_surface
    //   3. wl_subcompositor.get_subsurface(child_surface, parent_surface_from_ptr)
    //   4. Wrap parent_surface_ptr as a wayland-client WlSurface via Proxy::from_id
    //
    // For Task 8 we only stub the API surface so dependent tasks compile.
    // Real implementation comes in Task 9 once we've validated the wayland-client
    // version's Proxy API.
    Err(AppError::Terminal("subsurface creation not yet implemented (task 9)".into()))
}

#[cfg(test)]
mod tests {
    #[test]
    fn placeholder_compiles() {
        // Sanity: module compiles. Real tests need a live Wayland compositor.
    }
}
```

- [ ] **Step 2: Build**

Run: `cd gui/src-tauri && cargo build`
Expected: builds. Some unused imports may fire — fix with `#[allow(unused_imports)]` at module scope OR remove the unused ones.

- [ ] **Step 3: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/subsurface.rs
git commit -m "feat(native-term): subsurface module skeleton + parent surface extraction"
```

---

## Task 9: Subsurface creation against live Wayland connection

**Files:**
- Modify: `gui/src-tauri/src/native_term/subsurface.rs`
- Modify: `gui/src-tauri/src/native_term/mod.rs` (init shared connection)

This task replaces the stub `create_subsurface` with a working implementation. It is the high-risk Wayland-protocol task — schedule extra time and be ready to escalate.

- [ ] **Step 1: Replace `create_subsurface` body**

Edit `gui/src-tauri/src/native_term/subsurface.rs`. The full algorithm:

```rust
use wayland_client::{
    globals::{registry_queue_init, GlobalListContents},
    protocol::{
        wl_compositor::WlCompositor,
        wl_subcompositor::WlSubcompositor,
        wl_subsurface::WlSubsurface,
        wl_surface::WlSurface,
    },
    Proxy,
};

struct AppData {
    compositor: Option<WlCompositor>,
    subcompositor: Option<WlSubcompositor>,
}

impl Dispatch<wayland_client::protocol::wl_registry::WlRegistry, GlobalListContents> for AppData {
    fn event(_: &mut Self, _: &wayland_client::protocol::wl_registry::WlRegistry, _: <wayland_client::protocol::wl_registry::WlRegistry as Proxy>::Event, _: &GlobalListContents, _: &Connection, _: &QueueHandle<Self>) {}
}
impl Dispatch<WlCompositor, ()> for AppData {
    fn event(_: &mut Self, _: &WlCompositor, _: <WlCompositor as Proxy>::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}
impl Dispatch<WlSubcompositor, ()> for AppData {
    fn event(_: &mut Self, _: &WlSubcompositor, _: <WlSubcompositor as Proxy>::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}
impl Dispatch<WlSurface, ()> for AppData {
    fn event(_: &mut Self, _: &WlSurface, _: <WlSurface as Proxy>::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}
impl Dispatch<WlSubsurface, ()> for AppData {
    fn event(_: &mut Self, _: &WlSubsurface, _: <WlSubsurface as Proxy>::Event, _: &(), _: &Connection, _: &QueueHandle<Self>) {}
}

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
    let qh = event_queue.handle();

    let mut data = AppData { compositor: None, subcompositor: None };
    let compositor: WlCompositor = globals
        .bind(&qh, 1..=4, ())
        .map_err(|e| AppError::Terminal(format!("bind compositor: {e}")))?;
    data.compositor = Some(compositor.clone());
    let subcompositor: WlSubcompositor = globals
        .bind(&qh, 1..=1, ())
        .map_err(|e| AppError::Terminal(format!("bind subcompositor: {e}")))?;
    data.subcompositor = Some(subcompositor.clone());

    event_queue.roundtrip(&mut data).map_err(|e| AppError::Terminal(format!("roundtrip: {e}")))?;

    // Reconstruct the parent WlSurface from its raw pointer. wayland-client doesn't
    // currently support this directly; we use the wayland-backend ObjectId API.
    let parent_id = unsafe {
        wayland_backend::sys::client::ObjectId::from_ptr(
            WlSurface::interface(),
            parent_surface_ptr.as_ptr() as *mut _,
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

    Ok(SubsurfaceHandle {
        child_surface,
        subsurface,
        width,
        height,
        x,
        y,
    })
}
```

- [ ] **Step 2: Add `wayland-backend` to Cargo.toml**

In `gui/src-tauri/Cargo.toml`:

```toml
wayland-backend = { version = "0.3", features = ["client_system"] }
```

- [ ] **Step 3: Build + test in unit context**

Run: `cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings`
Expected: builds clean. (Live Wayland test happens in Task 17 manual smoke.)

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/Cargo.toml gui/src-tauri/Cargo.lock gui/src-tauri/src/native_term/subsurface.rs
git commit -m "feat(native-term): subsurface creation via wayland-backend ObjectId"
```

**ESCALATION NOTE:** If the `ObjectId::from_ptr` API doesn't compile or panics at runtime against this Wayland version, REPORT BACK as BLOCKED. The fallback is to use a `tauri::Manager`-driven approach where Synthia's main thread proxies the surface object via a different mechanism (likely requires Tauri PR upstream). Do NOT proceed silently with broken code.

---

## Task 10: Renderer — softbuffer init + opaque background fill

**Files:**
- Create / overwrite: `gui/src-tauri/src/native_term/renderer.rs`

- [ ] **Step 1: Write the module**

```rust
//! Software rendering: softbuffer pixel buffer + cosmic-text glyph blit.

use crate::error::{AppError, AppResult};
use crate::native_term::grid::{Cell, Color, Grid};
use parking_lot::Mutex;
use std::sync::Arc;

#[allow(dead_code)] // populated in attach, drained in detach
pub struct Renderer {
    pub width: u32,
    pub height: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub buffer: Vec<u32>,
}

impl Renderer {
    pub fn new(width: u32, height: u32, cell_w: u32, cell_h: u32) -> AppResult<Self> {
        if width == 0 || height == 0 {
            return Err(AppError::Terminal("renderer: zero-dim surface".into()));
        }
        Ok(Self {
            width, height, cell_w, cell_h,
            buffer: vec![0u32; (width * height) as usize],
        })
    }

    pub fn fill_background(&mut self, bg: Color) {
        let pixel = pack_color(bg);
        self.buffer.iter_mut().for_each(|p| *p = pixel);
    }

    pub fn render_grid(&mut self, grid: &Grid) {
        // v1 minimal: fill background + draw cell backgrounds. Glyph rendering in Task 11.
        self.fill_background(Color::black());
        for r in 0..grid.rows {
            for c in 0..grid.cols {
                let cell = grid.cell_at(r, c);
                if cell.bg != Color::black() {
                    self.fill_cell_bg(r, c, cell.bg);
                }
            }
        }
    }

    fn fill_cell_bg(&mut self, row: usize, col: usize, color: Color) {
        let pixel = pack_color(color);
        let x0 = (col as u32) * self.cell_w;
        let y0 = (row as u32) * self.cell_h;
        for dy in 0..self.cell_h {
            let y = y0 + dy;
            if y >= self.height { break; }
            for dx in 0..self.cell_w {
                let x = x0 + dx;
                if x >= self.width { break; }
                self.buffer[(y * self.width + x) as usize] = pixel;
            }
        }
    }
}

pub type RendererRef = Arc<Mutex<Renderer>>;

fn pack_color(c: Color) -> u32 {
    // softbuffer expects 0xRRGGBB packed, alpha ignored.
    ((c.r as u32) << 16) | ((c.g as u32) << 8) | (c.b as u32)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn renderer_init_fails_on_zero_dim() {
        assert!(Renderer::new(0, 100, 8, 16).is_err());
        assert!(Renderer::new(100, 0, 8, 16).is_err());
    }

    #[test]
    fn renderer_fills_background() {
        let mut r = Renderer::new(4, 4, 2, 2).unwrap();
        r.fill_background(Color::rgb(0xff, 0, 0));
        let expected = pack_color(Color::rgb(0xff, 0, 0));
        assert!(r.buffer.iter().all(|&p| p == expected));
    }

    #[test]
    fn renderer_paints_cell_bg() {
        let mut r = Renderer::new(4, 4, 2, 2).unwrap();
        r.fill_background(Color::black());
        r.fill_cell_bg(0, 0, Color::rgb(0xff, 0, 0));
        let red = pack_color(Color::rgb(0xff, 0, 0));
        assert_eq!(r.buffer[0], red);
        assert_eq!(r.buffer[1], red);
        assert_eq!(r.buffer[4], red);
        assert_eq!(r.buffer[5], red);
        // outside cell still black
        assert_eq!(r.buffer[2], pack_color(Color::black()));
    }
}
```

- [ ] **Step 2: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::renderer`
Expected: 3 PASS.

- [ ] **Step 3: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/renderer.rs
git commit -m "feat(native-term): renderer base — softbuffer-shaped pixel buffer + cell bg fill"
```

---

## Task 11: Renderer — cosmic-text font load + glyph blit

**Files:**
- Modify: `gui/src-tauri/src/native_term/renderer.rs`

- [ ] **Step 1: Add font loading + glyph blit**

Insert at the top of `renderer.rs` (above the existing `pub struct Renderer`):

```rust
use cosmic_text::{Attrs, Buffer, FontSystem, Metrics, Shaping, SwashCache};

pub struct FontStack {
    pub system: FontSystem,
    pub cache: SwashCache,
    pub metrics: Metrics,
}

impl FontStack {
    pub fn new(font_size: f32) -> Self {
        let system = FontSystem::new();
        let cache = SwashCache::new();
        let metrics = Metrics::new(font_size, font_size * 1.4);
        Self { system, cache, metrics }
    }
}
```

Replace the existing `Renderer` struct + impls with:

```rust
pub struct Renderer {
    pub width: u32,
    pub height: u32,
    pub cell_w: u32,
    pub cell_h: u32,
    pub buffer: Vec<u32>,
    pub fonts: FontStack,
}

impl Renderer {
    pub fn new(width: u32, height: u32, cell_w: u32, cell_h: u32, font_size: f32) -> AppResult<Self> {
        if width == 0 || height == 0 {
            return Err(AppError::Terminal("renderer: zero-dim surface".into()));
        }
        Ok(Self {
            width, height, cell_w, cell_h,
            buffer: vec![0u32; (width * height) as usize],
            fonts: FontStack::new(font_size),
        })
    }

    pub fn fill_background(&mut self, bg: Color) {
        let pixel = pack_color(bg);
        self.buffer.iter_mut().for_each(|p| *p = pixel);
    }

    pub fn render_grid(&mut self, grid: &Grid) {
        self.fill_background(Color::black());
        for r in 0..grid.rows {
            for c in 0..grid.cols {
                let cell = grid.cell_at(r, c);
                if cell.bg != Color::black() {
                    self.fill_cell_bg(r, c, cell.bg);
                }
                if cell.ch != ' ' {
                    self.draw_glyph(r, c, cell);
                }
            }
        }
    }

    fn fill_cell_bg(&mut self, row: usize, col: usize, color: Color) {
        let pixel = pack_color(color);
        let x0 = (col as u32) * self.cell_w;
        let y0 = (row as u32) * self.cell_h;
        for dy in 0..self.cell_h {
            let y = y0 + dy;
            if y >= self.height { break; }
            for dx in 0..self.cell_w {
                let x = x0 + dx;
                if x >= self.width { break; }
                self.buffer[(y * self.width + x) as usize] = pixel;
            }
        }
    }

    fn draw_glyph(&mut self, row: usize, col: usize, cell: Cell) {
        let x0 = (col as u32) * self.cell_w;
        let y0 = (row as u32) * self.cell_h;
        let mut buffer = Buffer::new(&mut self.fonts.system, self.fonts.metrics);
        let attrs = Attrs::new();
        let s = cell.ch.to_string();
        buffer.set_size(&mut self.fonts.system, Some(self.cell_w as f32), Some(self.cell_h as f32));
        buffer.set_text(&mut self.fonts.system, &s, attrs, Shaping::Advanced);
        buffer.shape_until_scroll(&mut self.fonts.system, false);

        let fg = pack_color(cell.fg);
        let bg = pack_color(cell.bg);
        for run in buffer.layout_runs() {
            for glyph in run.glyphs.iter() {
                let physical = glyph.physical((0.0, 0.0), 1.0);
                self.fonts.cache.with_pixels(
                    &mut self.fonts.system,
                    physical.cache_key,
                    cosmic_text::Color::rgb(cell.fg.r, cell.fg.g, cell.fg.b),
                    |gx, gy, color| {
                        let alpha = color.a();
                        if alpha == 0 { return; }
                        let px = (x0 as i32 + physical.x + gx) as i64;
                        let py = (y0 as i32 + (run.line_y as i32) + gy) as i64;
                        if px < 0 || py < 0 { return; }
                        let (px, py) = (px as u32, py as u32);
                        if px >= self.width || py >= self.height { return; }
                        let blended = blend_alpha(bg, fg, alpha);
                        self.buffer[(py * self.width + px) as usize] = blended;
                    },
                );
            }
        }
    }
}

fn blend_alpha(bg: u32, fg: u32, alpha: u8) -> u32 {
    let a = alpha as u32;
    let inv = 255 - a;
    let br = ((bg >> 16) & 0xff) * inv / 255;
    let bg_g = ((bg >> 8) & 0xff) * inv / 255;
    let bb = (bg & 0xff) * inv / 255;
    let fr = ((fg >> 16) & 0xff) * a / 255;
    let fg_g = ((fg >> 8) & 0xff) * a / 255;
    let fb = (fg & 0xff) * a / 255;
    ((br + fr) << 16) | ((bg_g + fg_g) << 8) | (bb + fb)
}
```

- [ ] **Step 2: Update existing tests**

The `Renderer::new` signature changed (added `font_size`). Update the existing tests in `mod tests` to pass `13.0` as font_size:

```rust
    #[test]
    fn renderer_init_fails_on_zero_dim() {
        assert!(Renderer::new(0, 100, 8, 16, 13.0).is_err());
        assert!(Renderer::new(100, 0, 8, 16, 13.0).is_err());
    }

    #[test]
    fn renderer_fills_background() {
        let mut r = Renderer::new(4, 4, 2, 2, 13.0).unwrap();
        r.fill_background(Color::rgb(0xff, 0, 0));
        let expected = pack_color(Color::rgb(0xff, 0, 0));
        assert!(r.buffer.iter().all(|&p| p == expected));
    }

    #[test]
    fn renderer_paints_cell_bg() {
        let mut r = Renderer::new(4, 4, 2, 2, 13.0).unwrap();
        r.fill_background(Color::black());
        r.fill_cell_bg(0, 0, Color::rgb(0xff, 0, 0));
        let red = pack_color(Color::rgb(0xff, 0, 0));
        assert_eq!(r.buffer[0], red);
    }

    #[test]
    fn renderer_blend_alpha_zero_keeps_bg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 0), 0xffffff);
    }

    #[test]
    fn renderer_blend_alpha_full_uses_fg() {
        assert_eq!(blend_alpha(0xffffff, 0x000000, 255), 0x000000);
    }
```

- [ ] **Step 3: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::renderer`
Expected: 5 PASS.

- [ ] **Step 4: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/renderer.rs
git commit -m "feat(native-term): cosmic-text glyph rendering + alpha blend"
```

---

## Task 12: Input — wl_keyboard binding stubs + xkbcommon keysym mapping

**Files:**
- Create / overwrite: `gui/src-tauri/src/native_term/input.rs`

For v1, focus on the keysym → bytes mapping in pure logic (testable). Wayland keyboard binding is wired in Task 14's commands wrapper.

- [ ] **Step 1: Write the module + tests**

```rust
//! Keyboard input mapping. Pure logic for keysym → PTY byte sequence.
//!
//! Wayland event loop binding is in `subsurface.rs` and stitched together
//! by `commands.rs::native_term_attach`.

use xkbcommon::xkb::{self, Keysym};

pub struct InputHandler {
    pub modifiers: Modifiers,
}

#[derive(Clone, Copy, Debug, Default)]
pub struct Modifiers {
    pub shift: bool,
    pub ctrl: bool,
    pub alt: bool,
    pub logo: bool,
}

impl InputHandler {
    pub fn new() -> Self {
        Self { modifiers: Modifiers::default() }
    }

    /// Map a keysym + current modifier state to a PTY byte sequence.
    /// Returns an empty Vec for keys with no terminal mapping (modifier keys, F-keys, etc.).
    pub fn keysym_to_bytes(&self, sym: Keysym, utf8: Option<char>) -> Vec<u8> {
        // Special keys first
        match sym {
            xkb::Keysym::Return => return b"\r".to_vec(),
            xkb::Keysym::BackSpace => return vec![0x7f],
            xkb::Keysym::Tab => return b"\t".to_vec(),
            xkb::Keysym::Escape => return vec![0x1b],
            xkb::Keysym::Up => return b"\x1b[A".to_vec(),
            xkb::Keysym::Down => return b"\x1b[B".to_vec(),
            xkb::Keysym::Right => return b"\x1b[C".to_vec(),
            xkb::Keysym::Left => return b"\x1b[D".to_vec(),
            xkb::Keysym::Home => return b"\x1b[H".to_vec(),
            xkb::Keysym::End => return b"\x1b[F".to_vec(),
            xkb::Keysym::Page_Up => return b"\x1b[5~".to_vec(),
            xkb::Keysym::Page_Down => return b"\x1b[6~".to_vec(),
            xkb::Keysym::Delete => return b"\x1b[3~".to_vec(),
            _ => {}
        }
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
        assert_eq!(h.keysym_to_bytes(Keysym::c, Some('c')), vec![0x03]);
    }

    #[test]
    fn input_alt_b_emits_esc_b() {
        let mut h = InputHandler::new();
        h.modifiers.alt = true;
        assert_eq!(h.keysym_to_bytes(Keysym::b, Some('b')), b"\x1bb".to_vec());
    }

    #[test]
    fn input_plain_letter_passes_through() {
        let h = InputHandler::new();
        assert_eq!(h.keysym_to_bytes(Keysym::a, Some('a')), b"a".to_vec());
    }
}
```

Note: `xkb::Keysym::c` and `xkb::Keysym::a` are constants; if the `xkbcommon` crate exposes them differently, use the numeric form (`Keysym::new(0x0061)` for `'a'`).

- [ ] **Step 2: Run tests**

Run: `cd gui/src-tauri && cargo test --lib native_term::input`
Expected: 6 PASS.

If `xkb::Keysym::c` doesn't compile, look at the xkbcommon docs for the actual constant name (might be `KEY_c` or `XK_c`); adjust the test imports accordingly.

- [ ] **Step 3: Clippy + commit**

```bash
cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/input.rs
git commit -m "feat(native-term): keyboard input mapping (keysym → PTY bytes)"
```

---

## Task 13: Tauri command — `native_term_attach`

**Files:**
- Create / overwrite: `gui/src-tauri/src/native_term/commands.rs`

- [ ] **Step 1: Write the command**

```rust
//! Tauri commands for the native renderer.

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, State};
use uuid::Uuid;

use crate::error::{AppError, AppResult};
use crate::state::AppState;

#[derive(Deserialize, Serialize, Clone, Copy)]
pub struct TermGeom {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
}

#[tauri::command]
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

    // Create subsurface
    let _handle = crate::native_term::subsurface::create_subsurface(
        &conn, parent_ptr, geom.x, geom.y, geom.width, geom.height,
    )?;

    // Lease PTY from the existing terminal session
    let leased = crate::commands::terminal::lease_for_native(&state.terminals, session_id)?
        .ok_or_else(|| AppError::Terminal("session already leased or not spawned".into()))?;

    // FIXME(stage 2): wire reader → vte parser → grid mutation,
    // wire grid dirty → renderer → softbuffer present,
    // wire wl_keyboard events → input handler → leased.writer.
    // Stage 1 of this task only proves attach succeeds end-to-end.
    drop(leased);

    Ok(())
}
```

- [ ] **Step 2: Build**

Run: `cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings`
Expected: builds clean.

- [ ] **Step 3: Commit**

```bash
git add gui/src-tauri/src/native_term/commands.rs
git commit -m "feat(native-term): native_term_attach command (stage 1, no rendering yet)"
```

---

## Task 14: Wire reader/render/input tasks in `native_term_attach`

**Files:**
- Modify: `gui/src-tauri/src/native_term/commands.rs`
- Modify: `gui/src-tauri/src/native_term/mod.rs`

This task glues all the pieces together. It is large.

- [ ] **Step 1: Replace the body of `native_term_attach` with the full pipeline**

```rust
#[tauri::command]
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

    let mut leased = crate::commands::terminal::lease_for_native(&state.terminals, session_id)?
        .ok_or_else(|| AppError::Terminal("session already leased or not spawned".into()))?;

    // Compute cell dims from font metrics (8x16 placeholder; Task 15 calibrates from cosmic-text).
    let cell_w = 8u32;
    let cell_h = 16u32;
    let cols = (geom.width / cell_w).max(1) as usize;
    let rows = (geom.height / cell_h).max(1) as usize;

    let renderer = crate::native_term::renderer::Renderer::new(geom.width, geom.height, cell_w, cell_h, 13.0)?;
    let renderer_arc = std::sync::Arc::new(parking_lot::Mutex::new(renderer));
    let grid = std::sync::Arc::new(parking_lot::Mutex::new(crate::native_term::grid::Grid::new(rows, cols)));
    let input = crate::native_term::input::InputHandler::new();

    // Reader task: PTY bytes → vte parser → grid mutation
    let grid_for_reader = grid.clone();
    let mut reader = std::mem::replace(
        &mut leased.reader,
        Box::new(std::io::empty()) as Box<dyn std::io::Read + Send>,
    );
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

    // Render task: 60fps poll on dirty flag, blit to softbuffer.
    // Stage 1: just drain dirty flag and re-render to internal buffer.
    // Stage 3 (Task 15) presents to wl_surface via softbuffer.
    let grid_for_render = grid.clone();
    let renderer_for_render = renderer_arc.clone();
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
                r.render_grid(&*g);
            }
        }
    });

    // Input task: placeholder until Task 15's Wayland keyboard binding lands.
    let input_task = tokio::spawn(async move {
        let _ = input;
        // Stage 1: idle. Stage 3: wire wl_keyboard events here.
        loop { tokio::time::sleep(std::time::Duration::from_secs(60)).await; }
    });

    let session = crate::native_term::NativeSession {
        subsurface,
        renderer: std::sync::Arc::try_unwrap(renderer_arc)
            .map_err(|_| AppError::Terminal("renderer arc still has refs".into()))?
            .into_inner(),
        grid,
        input: crate::native_term::input::InputHandler::new(),
        leased,
        reader_task,
        render_task,
        input_task,
    };

    state.native_terminals.sessions.lock().insert(session_id, session);
    Ok(())
}
```

- [ ] **Step 2: Build**

Run: `cd gui/src-tauri && cargo build`

The compiler will complain about `try_unwrap` on Arc that was clone()d. Fix: keep the Arc, change `NativeSession.renderer` to `Arc<Mutex<Renderer>>`. Update `mod.rs` to match:

In `gui/src-tauri/src/native_term/mod.rs`, change:

```rust
pub renderer: renderer::Renderer,
```

to:

```rust
pub renderer: std::sync::Arc<parking_lot::Mutex<renderer::Renderer>>,
```

Then in `native_term_attach`, replace the `try_unwrap` line with:

```rust
        renderer: renderer_arc,
```

- [ ] **Step 3: Build + clippy clean**

```bash
cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings
```

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/
git commit -m "feat(native-term): wire reader + render + input task pipeline (stage 2)"
```

---

## Task 15: Stage 3 — wire softbuffer presentation + wl_keyboard input

**Files:**
- Modify: `gui/src-tauri/src/native_term/commands.rs`
- Modify: `gui/src-tauri/src/native_term/subsurface.rs`

This is the biggest single task. Wires actual screen present + keyboard to PTY.

- [ ] **Step 1: Add softbuffer presentation in render task**

In the render task closure inside `native_term_attach`, replace the inner block with:

```rust
            if dirty {
                let g = grid_for_render.lock();
                let mut r = renderer_for_render.lock();
                r.render_grid(&*g);
                // Stage 3: copy r.buffer to softbuffer surface and present.
                // For now, log success — actual softbuffer present requires
                // creating Softbuffer Context + Surface from the subsurface's
                // child wl_surface. Fill in via a helper in subsurface.rs.
                let _ = crate::native_term::subsurface::present_buffer(
                    &subsurface_ref,
                    &r.buffer,
                    r.width, r.height,
                );
            }
```

You will need to capture a reference to the subsurface for the render task. Wrap `SubsurfaceHandle` in `Arc<Mutex<>>` and clone for the render task before moving the original into `NativeSession`.

Add `present_buffer` to `subsurface.rs`:

```rust
pub fn present_buffer(
    handle: &std::sync::Arc<parking_lot::Mutex<SubsurfaceHandle>>,
    buffer: &[u32],
    width: u32,
    height: u32,
) -> AppResult<()> {
    // FIXME(stage 3): integrate softbuffer here. Requires:
    //   - softbuffer::Context::new() against shared Wayland connection
    //   - softbuffer::Surface::new() against the child WlSurface
    //   - surface.resize() to (width, height)
    //   - surface.buffer_mut() → copy buffer slice → present()
    // Until softbuffer is wired, mark surface damaged so compositor knows.
    let h = handle.lock();
    h.child_surface.damage_buffer(0, 0, width as i32, height as i32);
    h.child_surface.commit();
    let _ = buffer;
    Ok(())
}
```

- [ ] **Step 2: Add Wayland keyboard input task**

This is the trickiest piece. Replace the placeholder input_task with a Wayland event-loop task that listens for `wl_keyboard` events on the child surface and dispatches them to the input handler.

The shape:

```rust
let input_task = {
    let conn = conn.clone();
    let writer_for_input = std::sync::Arc::new(parking_lot::Mutex::new(
        std::mem::replace(
            &mut leased.writer,
            Box::new(std::io::sink()) as Box<dyn std::io::Write + Send>,
        ),
    ));
    let writer_clone = writer_for_input.clone();
    tokio::task::spawn_blocking(move || {
        // FIXME(stage 3): bind wl_seat, get_keyboard, listen for key events,
        // translate via input.keysym_to_bytes(), write to writer_clone.
        // Until wired: sleep forever.
        let _ = (conn, writer_clone);
        loop { std::thread::sleep(std::time::Duration::from_secs(60)); }
    })
};
```

Implementing the actual keyboard binding requires non-trivial wayland-client Dispatch impls. For Task 15, leave the FIXME and report DONE_WITH_CONCERNS so the controller can plan a follow-up task focused only on input wiring.

- [ ] **Step 3: Build + clippy clean**

```bash
cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings
```

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/
git commit -m "feat(native-term): stage 3 scaffold — present helper + input task placeholder"
```

ESCALATION NOTE: After this task the build compiles but the terminal will not yet render or accept input — only the subsurface is created and damaged. Tasks 16-17 close the loop by wiring softbuffer present and wl_keyboard input.

---

## Task 16: Wire softbuffer presentation against child surface

**Files:**
- Modify: `gui/src-tauri/src/native_term/subsurface.rs`
- Modify: `gui/src-tauri/src/native_term/commands.rs`

- [ ] **Step 1: Implement `present_buffer` for real**

```rust
use softbuffer::{Context, Surface};
use raw_window_handle::{
    DisplayHandle, RawDisplayHandle, RawWindowHandle, WaylandDisplayHandle,
    WaylandWindowHandle, WindowHandle,
};

pub struct SoftbufferState {
    pub context: Context<DummyDisplay>,
    pub surface: Surface<DummyDisplay, DummyWindow>,
}

pub struct DummyDisplay {
    raw: RawDisplayHandle,
}
unsafe impl raw_window_handle::HasRawDisplayHandle for DummyDisplay {
    fn raw_display_handle(&self) -> RawDisplayHandle { self.raw }
}

pub struct DummyWindow {
    raw: RawWindowHandle,
}
unsafe impl raw_window_handle::HasRawWindowHandle for DummyWindow {
    fn raw_window_handle(&self) -> RawWindowHandle { self.raw }
}

pub fn init_softbuffer(
    display_ptr: NonNull<std::ffi::c_void>,
    surface_ptr: NonNull<std::ffi::c_void>,
    width: u32,
    height: u32,
) -> AppResult<SoftbufferState> {
    let display_raw = RawDisplayHandle::Wayland(WaylandDisplayHandle::new(display_ptr));
    let window_raw = RawWindowHandle::Wayland(WaylandWindowHandle::new(surface_ptr));
    let display = DummyDisplay { raw: display_raw };
    let window = DummyWindow { raw: window_raw };
    let context = unsafe { Context::new(display) }
        .map_err(|e| AppError::Terminal(format!("softbuffer ctx: {e}")))?;
    let mut surface = unsafe { Surface::new(&context, window) }
        .map_err(|e| AppError::Terminal(format!("softbuffer surface: {e}")))?;
    surface.resize(
        std::num::NonZeroU32::new(width).ok_or_else(|| AppError::Terminal("zero width".into()))?,
        std::num::NonZeroU32::new(height).ok_or_else(|| AppError::Terminal("zero height".into()))?,
    ).map_err(|e| AppError::Terminal(format!("softbuffer resize: {e}")))?;
    Ok(SoftbufferState { context, surface })
}

pub fn present_buffer(
    sb: &mut SoftbufferState,
    pixels: &[u32],
) -> AppResult<()> {
    let mut buf = sb.surface.buffer_mut()
        .map_err(|e| AppError::Terminal(format!("softbuffer buffer_mut: {e}")))?;
    buf.copy_from_slice(pixels);
    buf.present().map_err(|e| AppError::Terminal(format!("softbuffer present: {e}")))?;
    Ok(())
}
```

If softbuffer's API requires different lifetimes or the `unsafe { Context::new(...) }` call differs in 0.4.x, adjust per the actual API. The crate doc is at <https://docs.rs/softbuffer/0.4>.

- [ ] **Step 2: Wire init_softbuffer in `native_term_attach`**

Right after `create_subsurface` returns, also call `init_softbuffer` and store the resulting state in `NativeSession`. Update `mod.rs` `NativeSession` to include `pub softbuffer: parking_lot::Mutex<crate::native_term::subsurface::SoftbufferState>`.

In the render task, change the `present_buffer` call to use the real softbuffer:

```rust
                let _ = crate::native_term::subsurface::present_buffer(
                    &mut *softbuffer_for_render.lock(),
                    &r.buffer,
                );
```

- [ ] **Step 3: Build + clippy**

```bash
cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings
```

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/
git commit -m "feat(native-term): real softbuffer presentation against child surface"
```

ESCALATION NOTE: If softbuffer can't bind to a wl_subsurface (some implementations require an xdg_surface), this will fail at runtime even if it compiles. Report BLOCKED and we'll switch to manual `wl_shm` buffer pool.

---

## Task 17: Wire wl_keyboard input → PTY writer

**Files:**
- Modify: `gui/src-tauri/src/native_term/subsurface.rs`
- Modify: `gui/src-tauri/src/native_term/commands.rs`

- [ ] **Step 1: Add Wayland keyboard binding in subsurface.rs**

Implement a function that:
1. Binds `wl_seat` from the registry
2. Calls `wl_seat.get_keyboard()` to get a `wl_keyboard`
3. Stores the keyboard with a Dispatch impl that:
   - Receives `wl_keyboard.key` events (keycode + state)
   - Translates keycode → keysym via xkbcommon::xkb::State
   - Updates modifiers on `wl_keyboard.modifiers` events
   - Calls back into `InputHandler.keysym_to_bytes` and writes to PTY

The full impl is ~200 lines of Wayland boilerplate. Consult <https://docs.rs/wayland-client/latest/wayland_client/> for current Dispatch patterns.

- [ ] **Step 2: Integrate the keyboard task into `native_term_attach`**

Replace the placeholder input_task with the real keyboard event loop spawned via `tokio::task::spawn_blocking`.

- [ ] **Step 3: Build, clippy, commit**

```bash
cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings
git add gui/src-tauri/src/native_term/
git commit -m "feat(native-term): wl_keyboard binding → InputHandler → PTY writer"
```

ESCALATION NOTE: This task is the largest single piece of Wayland protocol work in the plan. If it takes more than a day or hits ObjectId/Proxy issues, BLOCK and revisit — we may need to embed `smithay-client-toolkit` (a higher-level Wayland helper crate) instead of raw wayland-client.

---

## Task 18: `native_term_resize` + `native_term_detach` commands

**Files:**
- Modify: `gui/src-tauri/src/native_term/commands.rs`

- [ ] **Step 1: Add resize**

```rust
#[tauri::command]
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
        // child surface size is dictated by buffer, not subsurface — softbuffer.resize handles it.
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
```

- [ ] **Step 2: Add detach**

```rust
#[tauri::command]
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
    // Restore PTY handles to the session so terminal_kill works.
    let leased = session.leased;
    crate::commands::terminal::restore_from_native(&state.terminals, session_id, leased)?;
    Ok(())
}
```

- [ ] **Step 3: Build + clippy**

```bash
cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings
```

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/commands.rs
git commit -m "feat(native-term): native_term_resize + native_term_detach commands"
```

---

## Task 19: Register commands in `lib.rs`

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Add to `generate_handler!`**

In `gui/src-tauri/src/lib.rs`, find the `tauri::generate_handler![...]` macro. After the existing `native_term_*` (fake-embed) entries, append:

```rust
            crate::native_term::commands::native_term_attach,
            crate::native_term::commands::native_term_resize,
            crate::native_term::commands::native_term_detach,
```

(NOTE: the fake-embed module is `commands::native_term::native_term_spawn` — the new path is `crate::native_term::commands::native_term_attach`. They have different names so no conflict.)

- [ ] **Step 2: Build**

Run: `cd gui/src-tauri && cargo build && cargo clippy --all-targets -- -D warnings`

- [ ] **Step 3: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(native-term): register attach/resize/detach commands"
```

---

## Task 20: Rewrite `NativeTerminalView.tsx` to use the new commands

**Files:**
- Modify: `gui/src/components/terminal/NativeTerminalView.tsx`

- [ ] **Step 1: Replace component body**

```tsx
import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface SessionMeta {
  id: string;
  cwd: string;
  shell: string;
  title: string;
  created_at: string;
}

interface NativeTerminalViewProps {
  visible: boolean;
}

interface TermGeom {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function NativeTerminalView({ visible }: NativeTerminalViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const computeGeom = useCallback((): TermGeom | null => {
    if (!containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    return {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      width: Math.max(1, Math.round(rect.width)),
      height: Math.max(1, Math.round(rect.height)),
    };
  }, []);

  // Spawn + attach on mount when visible
  useEffect(() => {
    if (!visible || !containerRef.current || sessionRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const meta = await invoke<SessionMeta>("terminal_spawn", {});
        if (cancelled) {
          await invoke("terminal_kill", { sessionId: meta.id }).catch(() => {});
          return;
        }
        const geom = computeGeom();
        if (!geom) throw new Error("no geom");
        await invoke("native_term_attach", { sessionId: meta.id, geom });
        sessionRef.current = meta.id;
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (sessionRef.current) {
        const id = sessionRef.current;
        sessionRef.current = null;
        invoke("native_term_detach", { sessionId: id })
          .catch(() => {})
          .then(() => invoke("terminal_kill", { sessionId: id }).catch(() => {}));
      }
    };
  }, [visible, computeGeom]);

  // Reposition on resize / move
  useEffect(() => {
    if (!visible) return;
    const reposition = () => {
      if (!sessionRef.current) return;
      const geom = computeGeom();
      if (geom) {
        invoke("native_term_resize", { sessionId: sessionRef.current, geom }).catch(() => {});
      }
    };
    const observer = new ResizeObserver(reposition);
    if (containerRef.current) observer.observe(containerRef.current);
    window.addEventListener("resize", reposition);
    const interval = window.setInterval(reposition, 250);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", reposition);
      window.clearInterval(interval);
    };
  }, [visible, computeGeom]);

  return (
    <div
      ref={containerRef}
      className="native-terminal-pane"
      style={{ width: "100%", height: "100%", background: "#0d1117" }}
    >
      {error && (
        <div style={{ color: "#fda4af", fontFamily: "monospace", padding: 12 }}>
          Native terminal failed: {error}. Toggle back to xterm.js.
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Build frontend**

Run: `cd gui && npm run build`
Expected: clean compile.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/terminal/NativeTerminalView.tsx
git commit -m "feat(native-term): React view talks to new attach/resize/detach commands"
```

---

## Task 21: Manual smoke + deb build

**Files:** none (validation task)

- [ ] **Step 1: Build deb**

```bash
cd gui && npm run tauri build
```

- [ ] **Step 2: Install + launch**

```bash
pkill synthia-gui || true
sleep 1
rm -rf ~/.local/share/com.synthia.gui ~/.cache/com.synthia.gui
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/Synthia_0.1.0_amd64.deb
nohup synthia-gui > /tmp/synthia-test.log 2>&1 & disown
```

- [ ] **Step 3: Walk through smoke checklist**

1. Open Terminal sidebar
2. Toggle to "Native (beta)"
3. Verify subsurface appears (may show only background fill at first depending on which tasks landed)
4. If reader/render wired: verify bash prompt appears
5. If input wired: type — verify echoes
6. Run `htop` — verify TUI renders
7. Resize Synthia window — subsurface should follow
8. Switch to Worktrees, then back to Terminal — subsurface should reattach cleanly
9. Toggle back to xterm.js — native subsurface destroyed
10. Quit Synthia — verify no orphan PTY children: `pgrep -af 'bash|zsh|claude' | grep -v wezterm`

- [ ] **Step 4: Document known gaps**

If Tasks 15-17 left FIXMEs, document them in a follow-up plan or TODO comments. Update `docs/superpowers/specs/2026-05-13-native-terminal-renderer-design.md` with status notes.

- [ ] **Step 5: Final commit (if any tweaks needed)**

```bash
# only if smoke uncovered fixes
git add ...
git commit -m "fix(native-term): ..."
```

---

## Done

Working v1: Wayland subsurface created inside Synthia main window, PTY bytes flow into vte parser, grid mutates, renderer paints cells, softbuffer presents. Keyboard input lands in PTY writer. Single tab, opaque dark bg, no GPU. Toggleable from React. xterm.js stays as fallback.

Stretch / known-gap items (post-v1):
- Multi-tab support
- Translucent / glass background
- Selection drag + clipboard copy
- Mouse events (TUI apps that use mouse like htop's columns)
- Cosmic-text font calibration for accurate cell dims
- HiDPI scaling
- Fall back to manual wl_shm pool if softbuffer can't bind to subsurface
