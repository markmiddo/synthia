# Built-in Terminal Emulator — Design

**Date:** 2026-05-13
**Scope:** New "Terminal" sidebar tab in Synthia Tauri GUI. Generic shell + Claude Code shortcut. Replaces Wezterm for Synthia-driven workflows.
**Files affected:**
- New: `gui/src-tauri/src/commands/terminal.rs`
- New: `gui/src/components/TerminalPanel.tsx`, `TerminalTabs.tsx`, `TerminalView.tsx`
- New: `gui/src/components/terminal/theme.ts`, `useTerminalSession.ts`
- New: `gui/src/assets/fonts/CommitMono-{400,600}.woff2`
- Edits: `gui/src-tauri/Cargo.toml`, `gui/src-tauri/src/lib.rs` (register commands), `gui/src-tauri/src/state.rs`, `gui/package.json`, `gui/src/App.tsx` (add Terminal tab to sidebar), `gui/src/components/WorktreesPanel.tsx` (Open Terminal button)

## Problem

Synthia sidebar already hosts agents, worktrees, journal, knowledge, etc. Users still alt-tab to Wezterm for shell access and Claude Code sessions. Wezterm on Linux/COSMIC has issues (minimize bugs, dated UI). Embedding a terminal directly into Synthia gives a unified command center and lets us match Synthia's visual language.

## Goal

Built-in xterm.js-based terminal as a sidebar tab. Browser-style tabs for multiple sessions. One-click "+ Claude" tab for quick Claude Code sessions. Worktree-aware: clicking "Open Terminal" on a worktree spawns a tab cwd'd to that worktree. Glassmorphic theme matching modern dark UI direction.

## Non-goals

- Multi-theme support (glassmorphic only for v1; switcher deferred)
- Tmux-style splits (tabs only)
- Standalone Tauri window (sidebar tab only)
- Windows/macOS support (Linux-only, like rest of Synthia)
- IME composition fixes beyond xterm.js defaults
- Sixel / iTerm2 inline image protocols
- Shell integration (OSC 7 cwd, OSC 133 prompt marks) — possible v2
- Routing commands through `neuralguard` AI Security layer (user's terminal, not AI's)
- Persistent sessions across app restarts (sessions die with app)

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  React (xterm.js)                                   │
│  TerminalPanel → TerminalTabs + TerminalView[]      │
└────────────────────┬────────────────────────────────┘
        invoke()     │     event listen
                     ↓
┌────────────────────┴────────────────────────────────┐
│  Tauri commands (commands/terminal.rs)              │
│  spawn / write / resize / kill / list               │
└────────────────────┬────────────────────────────────┘
                     ↓
┌────────────────────┴────────────────────────────────┐
│  TerminalRegistry in AppState                       │
│  HashMap<Uuid, PtySession>                          │
│  PtySession = portable-pty master + child + reader  │
└─────────────────────────────────────────────────────┘
```

PTY layer uses `portable-pty` (the same crate Wezterm uses). Pure Rust, no extra runtime. Slots into existing `commands/*.rs` module pattern.

## Components

### Rust

**`gui/src-tauri/src/commands/terminal.rs`** (new module)

```rust
#[tauri::command]
async fn terminal_spawn(state: State<'_, AppState>, app: AppHandle,
    cwd: Option<String>, shell: Option<String>) -> Result<SessionMeta, AppError>;

#[tauri::command]
async fn terminal_write(state: State<'_, AppState>,
    session_id: Uuid, data: String) -> Result<(), AppError>;

#[tauri::command]
async fn terminal_resize(state: State<'_, AppState>,
    session_id: Uuid, cols: u16, rows: u16) -> Result<(), AppError>;

#[tauri::command]
async fn terminal_kill(state: State<'_, AppState>,
    session_id: Uuid) -> Result<(), AppError>;

#[tauri::command]
async fn terminal_list(state: State<'_, AppState>) -> Vec<SessionMeta>;
```

`SessionMeta`: `{ id: Uuid, cwd: String, shell: String, title: String, created_at: DateTime }`.

**`gui/src-tauri/src/state.rs`** (edit)

```rust
pub struct TerminalRegistry {
    sessions: Mutex<HashMap<Uuid, PtySession>>,
}
struct PtySession {
    master: Box<dyn MasterPty + Send>,
    writer: Box<dyn Write + Send>,
    child: Box<dyn Child + Send + Sync>,
    reader_task: JoinHandle<()>,
    meta: SessionMeta,
}
impl Drop for TerminalRegistry { /* SIGTERM all + 500ms grace + SIGKILL */ }
```

Added to `AppState`.

**`gui/src-tauri/src/lib.rs`** registers all 5 commands in the existing `tauri::generate_handler!` macro.

**`gui/src-tauri/Cargo.toml`** adds:
```toml
portable-pty = "0.8"
base64 = "0.22"
```

**`gui/src-tauri/src/error.rs`** adds `Terminal(String)` variant to `AppError`.

### React

| Component | Responsibility |
|---|---|
| `TerminalPanel.tsx` | Top-level sidebar tab. Manages `tabs: TabState[]`, active index. |
| `TerminalTabs.tsx` | Tab strip: tabs, `+`, `+ Claude`, close-x. Middle-click closes. |
| `TerminalView.tsx` | One xterm.js instance per tab. Mounts on focus, kept alive when other tab active (DOM moves, not destroyed). |
| `terminal/theme.ts` | Glassmorphic palette + xterm theme config + font config. |
| `useTerminalSession.ts` | Hook: invokes spawn, listens to `terminal-output-{id}`, forwards keystrokes via `terminal_write`. Cleanup invokes `terminal_kill`. |

Frontend deps added to `gui/package.json`:
```
"@xterm/xterm": "^5.5",
"@xterm/addon-fit": "^0.10",
"@xterm/addon-webgl": "^0.18",
"@xterm/addon-web-links": "^0.11",
"@xterm/addon-search": "^0.15"
```

**Font:** Commit Mono 400/600 shipped as woff2 in `gui/src/assets/fonts/`, loaded via `@font-face` in App stylesheet.

**Sidebar integration:** `App.tsx` adds Terminal entry directly after Worktrees in sidebar order.

**Worktree integration:** `WorktreesPanel.tsx` adds "Open Terminal" button per worktree row → sets a Zustand-or-context store flag `{ requestSpawn: { cwd } }` → `App.tsx` watches, switches active tab to Terminal, `TerminalPanel` consumes flag and spawns.

## Data Flow

**Spawn:**
```
React: invoke('terminal_spawn', {cwd, shell: null})
  → Rust: portable-pty opens pair, spawns shell (auto $SHELL) as child
  →       sets PR_SET_PDEATHSIG (SIGTERM) so orphan dies with parent
  →       spawns tokio task: loop read 4KB → base64 → emit 'terminal-output-{id}'
  →       on EOF: emit 'terminal-exit-{id}' with exit code
  → returns SessionMeta
React: term.open(div), load addons (fit, webgl, web-links, search)
React: listen('terminal-output-{id}', chunk => term.write(atob(chunk)))
React: listen('terminal-exit-{id}', code => showExitBanner(code))
```

**User types:** `xterm.onData(s) → invoke('terminal_write', {sessionId, data: s}) → writer.write_all(s.as_bytes())`

**Resize:** `ResizeObserver (100ms debounce) → fitAddon.fit() → invoke('terminal_resize', {sessionId, cols, rows}) → master.resize(PtySize)`

**Tab close:** `invoke('terminal_kill', {sessionId}) → child.kill() → reader task aborts → registry removes entry → React: term.dispose()`

**`+ Claude` shortcut (button or Ctrl+Shift+C):** Spawn shell normally, immediately `invoke('terminal_write', {data: 'claude\n'})`.

**Encoding:** PTY raw bytes → base64 (Tauri events choke on raw `Vec<u8>` for cross-platform consistency). React `atob → string` → `term.write`. UTF-8 preserved.

## Visual Design

**Theme (xterm.js):**
```ts
background: 'rgba(15, 17, 28, 0.65)',  // translucent
foreground: '#e6e6fa',
cursor: '#e6e6fa',
selectionBackground: 'rgba(165, 180, 252, 0.25)',
black: '#1a1b26',   red: '#fda4af',   green: '#86efac',
yellow: '#fde68a',  blue: '#a5b4fc',  magenta: '#c4b5fd',
cyan: '#67e8f9',    white: '#e6e6fa',
brightBlack: '#6b7280', brightRed: '#fb7185',
brightGreen: '#4ade80', brightYellow: '#facc15',
brightBlue: '#818cf8',  brightMagenta: '#a78bfa',
brightCyan: '#22d3ee',  brightWhite: '#ffffff'
```

**Font:** Commit Mono 400/600, 13.5px, 1.5 line-height, ligatures off.

**Chrome (CSS):**
- Panel: linear-gradient(135deg, #1c1f2b 0%, #0d1117 100%), 12px padding
- Tab strip: rgba(255,255,255,0.03) bg, blur(8px), 1px bottom border rgba(255,255,255,0.06)
- Tab: 6px 14px padding, 6px 6px 0 0 radius, Commit Mono 12px, #6b7280 inactive
- Active tab: rgba(255,255,255,0.07) bg, #a5b4fc text, blur(8px)
- Tab close-x: opacity 0 default, 0.6 on hover
- View container: rgba(15,17,28,0.65) bg, blur(20px), 1px rgba(255,255,255,0.08) border, 0 8px 8px 8px radius, 14px 16px padding

**Tab UX:**
- Title auto: `${shell-basename} · ${cwd-basename}` (e.g. `zsh · synthia`)
- Drag-reorder (HTML5 DnD, xterm.js indifferent)
- Middle-click closes
- Ctrl+Shift+T new tab, Ctrl+Shift+W close tab, Ctrl+Tab cycle next, Ctrl+Shift+Tab cycle prev
- Ctrl+Shift+C: new Claude tab

**Empty state:** centered glass card "No terminals" with two CTAs: `+ New` `+ Claude`.

## Error Handling

| Case | Behavior |
|---|---|
| Shell binary missing | `AppError::Terminal("shell not found: {path}")`, toast in React, tab not created |
| cwd missing | Fallback to `$HOME`, log warning |
| Child exits | Emit `terminal-exit-{id}` with code → React shows dim banner "Process exited (code N) · Enter to close · Ctrl+R restart". Tab persists until user closes (preserves scrollback). |
| Spawn cap exceeded | Hard cap 16 sessions. Beyond → error, toast "Max 16 terminals" |
| App quit | `Drop` on `TerminalRegistry` sends SIGTERM to all children, waits 500ms, SIGKILL stragglers |
| Window close (not quit) | Sessions persist in registry, restored on reopen via `terminal_list()` |
| Crash recovery | `PR_SET_PDEATHSIG(SIGTERM)` on spawn ensures kernel reaps orphans |
| Worktree deleted while tab open | Shell stays alive in (now-detached) cwd. No special handling. |
| High output backpressure | xterm.js internal write queue handles. No app-level debounce. |

## Testing

### Rust (`cargo test --lib`, new tests in `commands/terminal.rs`)

| Test | Assertion |
|---|---|
| `spawn_creates_session` | Spawn `/bin/echo hi`, session in registry, output received, child exits cleanly |
| `write_forwards_bytes` | Spawn `cat`, write `"hello\n"`, output event fires with `"hello"` |
| `resize_no_panic` | Resize to (1,1) and (1000,1000), no panic |
| `kill_terminates_child` | Spawn long-running `sleep 100`, kill, child reaped within 1s |
| `spawn_invalid_shell_returns_err` | Bogus shell path → `AppError::Terminal` |
| `session_limit_enforced` | Spawn 17, 17th returns error |
| `registry_drop_kills_all` | Drop registry, no orphan PIDs |

Target test count: 35 → 42 in Rust suite.

### React (Vitest)

- `TerminalTabs` — render N tabs, `+` invokes spawn, close-x invokes kill, middle-click closes
- `useTerminalSession` — mock `invoke` + `listen`, keystrokes call `terminal_write`, output events call `term.write`
- Snapshot empty state + 3-tab populated state

### Manual smoke (per CLAUDE.md UI verification rule)

1. Build deb, install, launch GUI, open Terminal tab
2. Glass theme renders, Commit Mono loads (network panel: woff2 200)
3. Spawn 3 tabs, run `htop`, `vim`, `claude` — all interactive TUIs work
4. Resize window, terminal reflows without garbling
5. Open Worktrees tab, click "Open Terminal" on a worktree, confirm correct cwd
6. `Ctrl+Shift+C` opens Claude tab and `claude` runs
7. Kill tab mid-Claude session, confirm `pgrep claude` returns empty
8. Quit app, `pgrep -f synthia` empty (no orphan PTY children)

### Quality gates

- `cargo clippy --all-targets -- -D warnings` clean
- `cargo test --lib` passes
- `cargo build --release` succeeds, deb builds
- `tsc && vite build` clean
- Python suite untouched

## Risks

| Risk | Mitigation |
|---|---|
| xterm.js WebGL addon flaky on some GPUs | Fallback path: if `loadAddon(webglAddon)` throws, log and continue without — canvas renderer still works |
| portable-pty MSRV bump breaks build | Pin to `0.8.x`, CI catches |
| 4KB chunk size causes choppy output on fast streams | xterm.js buffers internally; revisit only if user reports |
| Sidebar tab takes Ctrl+Shift+C keybind from other panels | Only listen when Terminal tab active and pane focused |
| Commit Mono license | Commit Mono is free for personal + commercial use under the SIL Open Font License. Bundle the OFL license file at `gui/src/assets/fonts/CommitMono-LICENSE.txt` alongside the woff2 files. |

## Out of Scope (Future)

- Theme switcher (4 themes designed in brainstorm, only glass shipped v1)
- Tmux-style splits
- Shell integration (OSC 7 cwd report, OSC 133 prompt marks for "jump to prev command")
- Standalone window mode
- Session persistence across app restarts (would need on-disk state + reattach to dead PTY — significant scope)
- Inline image protocols (sixel, iTerm2)
- Profile system (different shells/cwds/envs per tab type)
