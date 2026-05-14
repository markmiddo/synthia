# Native Terminal Renderer (Wayland Subsurface) — Design

**Date:** 2026-05-13
**Scope:** Replace xterm.js rendering with a native Rust CPU renderer drawn into a `wl_subsurface` of Synthia's main `wl_surface`. PTY layer reused. Single tab v1. Toggle-driven so users can fall back to xterm.js.
**Files affected:**
- New: `gui/src-tauri/src/native_term/{mod.rs, subsurface.rs, renderer.rs, grid.rs, input.rs, commands.rs}`
- Edits: `gui/src-tauri/Cargo.toml`, `gui/src-tauri/src/lib.rs`, `gui/src-tauri/src/state.rs`, `gui/src-tauri/src/commands/mod.rs`, `gui/src-tauri/src/commands/terminal.rs` (expose pending_reader for native consumer), `gui/src/components/terminal/NativeTerminalView.tsx` (rewrite from fake-embed prototype)

## Problem

The xterm.js terminal inside Tauri's webkit2gtk webview has a hard latency floor (~15-30 ms per keystroke) caused by webview rendering + IPC overhead. The fake-embed Wezterm prototype proved the visual concept of an integrated terminal pane but introduces window-stacking quirks on COSMIC. Native rendering inside Synthia's own Wayland surface avoids both problems and gives true sub-millisecond keystroke response.

## Goal

Render a fully-functional terminal directly into a Wayland subsurface attached to Synthia's main window. Reuse the existing PTY backend (`commands/terminal.rs`). Render via CPU (softbuffer + cosmic-text), not GPU, to keep dependencies and complexity manageable. Ship single-tab v1; multi-tab + splits in v2. User picks "Native (beta)" via existing terminal mode toggle to use this path; xterm.js stays as fallback.

## Non-goals

- Multi-tab / split panes in v1
- GPU-accelerated rendering (wgpu) — softbuffer CPU is sufficient and simpler
- Translucent / glass background — opaque dark bg in v1
- Cross-platform support — Linux/Wayland only (matches Synthia's target)
- X11 / Xwayland support — pure Wayland subsurface only; falls back to xterm.js when not Wayland-native
- Image protocols (sixel, iTerm2) — not in v1
- Shell integration (OSC 7, OSC 133) — not in v1
- Custom shaders / themes beyond palette colours
- Replacing xterm.js entirely — both paths coexist, user toggles

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ Tauri main window                                            │
│ wl_surface = parent (owned by webkit2gtk webview)            │
│  ┌─ React UI ────────────────────────────────────────────┐   │
│  │  Terminal section: <NativeTerminalView/>              │   │
│  │  ┌─────────────────────────────────────────────┐      │   │
│  │  │ wl_subsurface (terminal pane)               │      │   │
│  │  │   = child of parent wl_surface              │      │   │
│  │  │   = softbuffer-backed pixel buffer          │      │   │
│  │  │   = vte parser → grid → cosmic-text → blit  │      │   │
│  │  └─────────────────────────────────────────────┘      │   │
│  └───────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

The webview keeps owning the parent surface for the React UI. Our subsurface lives on top of it, positioned by `wl_subsurface.set_position(x, y)` to match where the Terminal pane appears in the React layout. React drives position updates via Tauri IPC.

PTY ownership stays in `commands/terminal.rs`. The native renderer hooks into the existing `PtySession.pending_reader` instead of creating a new PTY.

## Components

### Rust (new module `gui/src-tauri/src/native_term/`)

| File | Responsibility |
|---|---|
| `mod.rs` | Public API + AppState integration. Holds the wayland-client `Connection` and `EventQueue` shared by all native sessions. |
| `subsurface.rs` | Wayland subsurface lifecycle: create/destroy, `set_position`, `set_sync` mode. Wraps the parent `wl_surface` extracted from Tauri's raw_window_handle. |
| `renderer.rs` | softbuffer context per subsurface + cosmic-text font cache + cell→pixel blit. Schedules redraws on grid dirty. |
| `grid.rs` | `Grid { rows, cols, cells: Vec<Cell> }`. Implements `vte::Performer` to consume PTY bytes and mutate cells. |
| `input.rs` | Wayland keyboard/pointer handlers. Maps keysyms to byte sequences (arrow keys → CSI, modifiers → control bytes). Writes to PTY via existing writer. |
| `commands.rs` | Tauri commands: `native_term_attach(session_id, geom)`, `native_term_resize(session_id, geom)`, `native_term_detach(session_id)`. |

`NativeTermRegistry` lives in `AppState`:
```rust
pub struct NativeTermRegistry {
    pub connection: OnceCell<wayland_client::Connection>,
    pub sessions: parking_lot::Mutex<HashMap<Uuid, NativeSession>>,
}

pub struct NativeSession {
    pub subsurface: WlSubsurface,
    pub child_surface: WlSurface,
    pub renderer: Renderer,
    pub grid: Arc<Mutex<Grid>>,
    pub input: InputHandler,
    pub pty_writer: Box<dyn Write + Send>,    // taken from PtySession
    pub reader_task: JoinHandle<()>,
    pub focus: bool,
}
```

### React

`gui/src/components/terminal/NativeTerminalView.tsx` (rewrite of fake-embed version):
- On mount + visible: `terminal_spawn` (existing) → sessionId → `native_term_attach(sessionId, geom)`
- On `ResizeObserver` / window resize / 250ms poll: `native_term_resize(sessionId, geom)`
- On unmount or visibility=false: `native_term_detach(sessionId)` then `terminal_kill(sessionId)`
- Renders an empty styled `<div>` as the visual placeholder; the subsurface renders ON TOP of this div area at the OS level

### Cargo dependencies

```toml
wayland-client = "0.31"
wayland-protocols = "0.31"
softbuffer = { version = "0.4", features = ["wayland"] }
cosmic-text = "0.12"
vte = "0.13"
raw-window-handle = "0.6"
xkbcommon = "0.7"  # for keyboard keysym translation
```

`raw-window-handle` already a transitive dep via Tauri — pin to the same version Tauri uses to avoid version conflicts.

## Data Flow

### Spawn / attach

```
React: invoke('terminal_spawn', {})  →  Rust spawns PTY (existing)  →  returns SessionMeta
React: invoke('native_term_attach', { sessionId, geom })
  Rust:
    1. Get parent wl_surface from Tauri main window's raw_window_handle
    2. Bind wl_subcompositor (cached on AppState.connection)
    3. Create child wl_surface
    4. wl_subcompositor.get_subsurface(child, parent) → WlSubsurface
    5. wl_subsurface.set_position(geom.x, geom.y)
    6. wl_subsurface.set_desync()  (independent commits, lower latency)
    7. Init softbuffer context targeting child_surface
    8. Take PtySession.pending_reader and pty_writer (consume them — native owns them now)
    9. Spawn reader task: PTY bytes → vte parser → grid mutate → mark dirty
    10. Spawn render task: on dirty + frame callback, redraw via softbuffer
    11. Spawn input task: wl_keyboard events → byte sequences → pty_writer.write
    12. Insert NativeSession into registry, return Ok
```

### Per-keystroke (the critical path — zero IPC)

```
Wayland keyboard event (in input task)
  → xkbcommon translates keycode → keysym + modifiers
  → input.rs maps to byte sequence (e.g. Enter → "\r", Ctrl+C → "\x03")
  → pty_writer.write_all(bytes)
  → bash echoes
  → reader task gets bytes → vte::Parser::advance → grid mutate
  → grid marks dirty (atomic flag)
  → on next wl_callback frame: render task blits cells via cosmic-text
  → softbuffer present → wl_surface.commit
  → compositor displays
```

No Tauri IPC at all on this path. All in-process Rust.

### Resize

```
React: ResizeObserver fires
  → invoke('native_term_resize', { sessionId, geom })
  Rust:
    1. wl_subsurface.set_position(geom.x, geom.y)
    2. softbuffer surface.resize(geom.width, geom.height)
    3. grid.resize(rows, cols) — preserve cells where possible
    4. ioctl(pty_fd, TIOCSWINSZ, &winsize{ rows, cols, ... })
    5. child_surface.commit
```

### Detach / kill

```
React: invoke('native_term_detach', { sessionId })
  Rust:
    1. Stop reader/render/input tasks
    2. Drop subsurface → compositor removes from parent
    3. Drop softbuffer context
    4. Restore pty_writer back to PtySession (so terminal_kill still works)
React: invoke('terminal_kill', { sessionId })
  → existing path kills child + reader_task
```

## Visual Design

- Background: solid `#0d1117` (matches xterm.js theme background opaque)
- Foreground: `#e6e6fa` (matches xterm.js)
- Palette: same 16 ANSI colours as `gui/src/components/terminal/theme.ts` glassTheme
- Font: Commit Mono 13.5pt loaded via cosmic-text from `gui/src-tauri/icons/../assets/fonts/CommitMono-400-Regular.woff2` — fall back to system mono if not loadable
- Cursor: solid block, no blink
- Padding: 14px inside subsurface
- Selection: light indigo highlight `rgba(165, 180, 252, 0.25)` — drawn as alpha-blended rect in softbuffer

No tab strip in the subsurface (single tab v1). The React side may render a header above the subsurface area, which the subsurface respects via `geom.y` offset.

## Error Handling

| Case | Handling |
|---|---|
| raw_window_handle returns non-Wayland (X11) | `native_term_attach` returns `AppError::Terminal("native renderer requires native Wayland — falling back")`, React catches and reverts toggle to xterm.js |
| `wl_subcompositor` not bound (compositor lacks support) | Same fallback |
| Subsurface position out of parent bounds | Clamp to parent dims, log warning |
| `softbuffer` init fails | Same fallback |
| Font missing | cosmic-text falls back to system mono, log warning |
| PTY EOF (process exited) | grid renders dim "[Process exited]" line at bottom, subsurface stays for review until detach |
| Input focus loss (user clicks elsewhere) | Wayland routes events to webview as normal — no handling needed |
| Window resize | React-driven via `native_term_resize`; clamp to >= 1×1 |
| `wl_callback` frame never fires | Fallback 60fps poll-redraw timer |
| PTY writer poisoned during native ownership | Mark session as dead, surface error to React |

## Testing

### Unit (Rust, in `native_term/grid.rs` and `native_term/input.rs`)

| Test | Assertion |
|---|---|
| `grid_apply_print_writes_at_cursor` | After `grid.apply_print('A')`, cell at cursor = 'A', cursor advances |
| `grid_apply_csi_cup_moves_cursor` | `\x1b[5;10H` moves cursor to row 5 col 10 |
| `grid_resize_preserves_visible_rows` | Resize 80x24 → 100x30, existing cells in bounds preserved |
| `grid_csi_sgr_color` | `\x1b[31m` sets fg to red for subsequent prints |
| `grid_csi_ed_clears_screen` | `\x1b[2J` blanks all cells |
| `input_arrow_keys_emit_csi` | Up arrow → `"\x1b[A"`, Down → `"\x1b[B"` |
| `input_ctrl_c_emits_etx` | Ctrl+C → `"\x03"` |
| `input_alt_b_emits_esc_b` | Alt+b → `"\x1bb"` |
| `input_text_passes_through` | Typing 'a' → `"a"` |

Target: 66 → 75 Rust lib tests.

### Manual smoke

1. Build deb, install, launch GUI
2. Click Terminal sidebar
3. Toggle to "Native (beta)"
4. Verify bash prompt appears in subsurface area
5. Type — should feel instant (< 5 ms perceived latency)
6. Run `htop` — TUI renders correctly, mouse + arrow keys work
7. Run `vim test.txt` — type, save, exit
8. Resize Synthia window — subsurface follows, content reflows
9. Switch to Worktrees tab — subsurface hides
10. Switch back to Terminal — subsurface returns with state preserved
11. Run `exit` — "[Process exited]" banner appears
12. Toggle back to xterm.js — native subsurface destroyed cleanly

### Quality gates

- `cargo clippy --all-targets -- -D warnings` clean
- `cargo test --lib` passes (target ~75)
- `cd gui && npm run build` clean
- Manual: side-by-side keystroke perf vs xterm.js — native should feel ≥ 10× more responsive

## Risks

| Risk | Mitigation |
|---|---|
| softbuffer wayland feature requires `wl_surface` ownership — must wrap subsurface's child surface, not parent | Construct synthetic raw_window_handle pointing to child surface; verify softbuffer 0.4 accepts it. If not, fall back to manual `wl_shm` buffer pool. |
| wayland-client + Tauri share `wl_display` connection — must NOT create a new connection | Extract existing display via raw_display_handle. Reuse Tauri's connection. Cache in `OnceCell<Connection>`. |
| Cosmic-text glyph atlas growth | Cap atlas at 512 glyphs, evict LRU. Cells reuse heavily so cache hit rate near 100%. |
| Input focus dance — webview may grab keyboard | Explicit `wl_seat.get_keyboard()` claim on subsurface enter. Pointer button click on subsurface area triggers focus. |
| Wayland event loop integration | Dedicated tokio task calling `event_queue.blocking_dispatch()` in loop. |
| Tauri's `RawWindowHandle` exposure changes between Tauri 2.x minors | Pin Tauri version, gate behind feature check, fall back to xterm.js if API mismatch. |
| Rendering across HiDPI scales | Read `wl_output.scale` from compositor, multiply pixel dims. cosmic-text supports DPI scaling natively. |
| Subsurface positioning lags React's layout (visible drift during scroll) | Set subsurface to sync mode (`wl_subsurface.set_sync()`) so position updates atomic with parent commits. Trade-off: parent must commit for child to update. v1: ship desync, monitor for drift. |

## Out of Scope (Future)

- Multi-tab support — requires multiple subsurfaces and tab strip rendering
- Split panes
- Image protocols (sixel, iTerm2 inline images)
- Shell integration markers (OSC 7 cwd, OSC 133 prompts)
- Theme switcher (custom palettes)
- GPU rendering (wgpu) — only if CPU softbuffer hits its ceiling
- Translucent / glass background — Wayland alpha + subsurface compositing has caveats
- Cross-platform (X11, macOS, Windows) — Linux/Wayland only by design
