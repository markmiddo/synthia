# Tab Rename + Shortcuts Panel + YouTube Feed

**Date:** 2026-05-14
**Branch:** `feat/terminal-emulator`
**Status:** Approved for implementation

Three independent enhancements bundled into one spec because they share no
dependencies and can ship in any order. Each gets its own commit.

---

## 1. Tab Rename

### Problem
Terminal tabs in the sidebar are labelled by sequential index only ("Terminal 1",
"Terminal 2"). With 3+ tabs open the user cannot tell which session is which
(opencode session vs build watcher vs SSH).

### Solution
Allow inline rename of tab name via double-click or right-click → Rename.

### Backend changes (`gui/src-tauri/src/native_term/`)

- `mod.rs`
  - Add `pub name: String` field to `NativeSession`.
  - Add `pub name: String` field to `PersistentNativeState`.
  - Default name: `"Terminal {n}"` where `n` is the position in `tab_order` at
    creation time.
- `commands.rs`
  - New Tauri command:
    ```rust
    #[tauri::command]
    pub async fn native_term_rename_tab(
        state: tauri::State<'_, NativeTermRegistry>,
        session_id: Uuid,
        name: String,
    ) -> Result<(), AppError>
    ```
    - Trims input, rejects empty (returns `AppError::Invalid("name cannot be empty")`).
    - Caps at 40 chars.
    - Mutates whichever map (`sessions` or `persistent`) holds the session.
    - Emits `terminal-tabs-changed` event so other windows see the rename.
  - Modify `native_term_list_tabs` to return `Vec<TabInfo>` instead of `Vec<Uuid>`:
    ```rust
    #[derive(Serialize)]
    pub struct TabInfo {
        pub id: Uuid,
        pub name: String,
        pub active: bool,
    }
    ```
  - Tab creation paths assign default name via `format!("Terminal {}", tab_order.lock().len() + 1)`.

### Frontend changes

- `App.tsx`
  - State shape: `terminalTabs: TabInfo[]` (was `Uuid[]`).
  - Render each tab as either label or `<input>` based on `renamingTabId` state.
- `App.css` — minor additions to `.terminal-tab-subitem-input`:
  - Inherits parent typography. Underline on focus. No box.
- New right-click handler on `.terminal-tab-subitem` opens a small popover
  (positioned at click x/y) with two items: "Rename", "Close".
  - Popover dismissed on outside click or Escape.
  - Implementation: pure React, no library.

### UX details
- Double-click tab text → switches that subitem to inline `<input>` with current
  name pre-filled and selected.
- Enter → call `native_term_rename_tab`, exit edit mode.
- Esc or blur → exit edit mode without saving.
- Right-click anywhere on subitem → popover. "Rename" triggers same edit flow.
  "Close" calls existing `native_term_close_tab`.
- Names persist across hide/show (already preserved via PersistentNativeState).
- Names DO NOT persist across app restart in v1. Cold start always begins with
  "Terminal 1". Acceptable: tabs are session-scoped; restart implies new work.

---

## 2. Shortcuts Sidebar Panel

### Problem
Two discoverability gaps:
1. User cannot recall their own shell aliases without `cat ~/.bashrc`.
2. Synthia hotkeys (Right Ctrl, Right Alt, Alt+T, Alt+W, etc.) live in
   docs/code only — no in-app reference.

### Solution
New nav item **Shortcuts** in the sidebar (inserted between **Terminal** and the
next existing item). Panel contains two sections.

### Section A: Synthia Hotkeys
Hardcoded in the React component as a static list. Each entry: `{keys, action, scope}`.

| Keys | Action | Scope |
|------|--------|-------|
| Right Ctrl | Voice dictation | Global |
| Right Alt | AI assistant | Global |
| Alt+T | New terminal tab | Terminal focused |
| Alt+W | Close active tab | Terminal focused |
| Ctrl+Shift+Tab | Cycle tabs | Terminal focused |
| Ctrl+C (with selection) | Copy selection | Terminal focused |
| Ctrl+V | Paste from clipboard | Terminal focused |
| Drag file in | Insert file path | Terminal focused |

(List lives in `ShortcutsPanel.tsx` as a const; updates require a code change —
acceptable, hotkeys change rarely.)

### Section B: Shell Aliases

**Backend** — new file `gui/src-tauri/src/commands/shortcuts.rs`:

```rust
#[derive(Serialize, Clone)]
pub struct AliasEntry {
    pub name: String,
    pub expansion: String,
}

#[tauri::command]
pub async fn get_shell_aliases() -> Vec<AliasEntry> { ... }
```

Implementation:
- Detect shell from `$SHELL`. Supported: bash, zsh. Fallback: bash.
- Run `<shell> -ic 'alias'` via `tokio::process::Command`. Interactive flag
  ensures rc files load.
- 5-second timeout. On timeout/error → return empty Vec (panel shows "No aliases
  found").
- Parse output line-by-line:
  - Strip optional leading `alias ` prefix (bash always emits it; zsh emits it
    when invoked non-interactively).
  - Split on first `=`. Left side = name. Right side = expansion.
  - Strip matched surrounding single or double quotes from expansion.
  - Skip lines that don't contain `=` or whose name contains spaces.
- Sort alphabetically by name.
- 60-second in-memory cache (alias edits are rare; user can switch panels to refresh).

### Frontend

New file `gui/src/components/ShortcutsPanel.tsx`:
- Sticky search box at top. Filters across both sections (case-insensitive
  substring match on name OR expansion OR action).
- Section A rendered first, then Section B.
- Each row clickable. Click action:
  - **Hotkey row**: no-op (informational only).
  - **Alias row**: copy `name` (the alias name, not expansion) to clipboard via
    `tauri-plugin-clipboard-manager`. Briefly flash row green to confirm.
- Empty state for aliases: "No aliases found in your shell rc files."

CSS (`gui/src/components/ShortcutsPanel.css`):
- Two-column row layout: keys/name left (monospace), action/expansion right (muted).
- Section headers: small uppercase, `rgba(255,255,255,0.40)`.
- Match existing panel padding/typography (use same vars as JournalPanel).

### Wiring
- `lib.rs` — register `get_shell_aliases` in `invoke_handler`.
- `App.tsx` — add `'shortcuts'` to the `Section` union; render `ShortcutsPanel`
  when active. Add nav item to sidebar list.

---

## 3. YouTube Feed Replaces News Rotator

### Problem
Current status bar rotator pulls https://the-decoder.com/feed/ — generic AI news
the user doesn't read. He already curates a YouTube channel list (in his morning
briefing skill) for the AI content he actually watches.

### Solution
Replace RSS news source with YouTube channels configured in
`~/.config/synthia/config.yaml`. Same status bar rotator UI; new content; click
opens video in browser.

### Config schema

`~/.config/synthia/config.yaml` gains:

```yaml
youtube:
  channels:
    - name: "Cole Medin"
      id: "UCMwVTLZIRRUyyVrkjDpn4pA"
    - name: "AI Code King"
      id: "UC0m81bQuthaQZmFbXEY9QSw"
    # ...
```

**First-launch seeding**: on GUI startup (in `lib.rs` `setup` callback), check
whether the `youtube` key is present in `~/.config/synthia/config.yaml`. If
absent, seed it with the 7 channels from `~/.claude/skills/morning/config.json`
IF that file exists. If neither exists, write an empty list. Seeding is
one-shot — never overwrites existing values.

Seeding writes to `~/.config/synthia/config.yaml` via the existing
`yaml_writer.rs` (preserves comments). New helper `seed_youtube_channels()` lives
in `commands/youtube_feed.rs`.

### Backend changes

Rename `gui/src-tauri/src/commands/news.rs` → `youtube_feed.rs`:

```rust
#[derive(Serialize, Clone)]
pub struct VideoItem {
    pub title: String,
    pub channel_name: String,
    pub video_url: String,
    pub thumbnail_url: Option<String>,
    pub published: Option<String>,
}

#[tauri::command]
pub async fn get_youtube_videos() -> Vec<VideoItem>
```

Implementation:
- Read channel list fresh from `~/.config/synthia/config.yaml` on each invocation
  (cheap — file is small; the request-level 30-minute cache makes this O(1) for
  the hot path). Matches the existing pattern of `claude_config.rs` etc.
- Channel list extraction: parse YAML with `serde_yaml`, navigate to `youtube.channels`,
  extract `[{name, id}]`. Missing/malformed → empty list (no panic).
- For each channel, fetch `https://www.youtube.com/feeds/videos.xml?channel_id={id}`
  in parallel via `tokio::join!` (or `futures::stream::FuturesUnordered`).
  Per-request timeout: 8s.
- Parse Atom with `feed_rs` (already a dep; same parser handles RSS + Atom).
- Extract per entry: `title.content`, `links[0].href` (video URL),
  `media.thumbnails[0].image.uri` if present (Atom YouTube includes
  `<media:thumbnail>`), `published`.
- Merge all videos, sort by `published` descending, take top 12.
- Cache: 30 minutes in-memory (was 15 for news).

### Frontend changes

- `App.tsx` (status bar rotator):
  - Replace `get_ai_news` invoke → `get_youtube_videos`.
  - Replace state type and rendering string format:
    - Was: `"{source} — {title}"`
    - Now: `"{channel_name} — {title} ({age})"`
  - Click handler unchanged — opens `video_url` in browser via existing opener.
- Remove "The Decoder" branding text wherever hardcoded.
- No design changes to rotator container/animation.

### Cleanup
- Delete old NewsItem struct.
- Update `lib.rs` invoke_handler: `get_ai_news` → `get_youtube_videos`.
- No other call sites — verified during exploration.

---

## Architecture summary

| File | Change | LOC est. |
|------|--------|----------|
| `native_term/mod.rs` | Add name fields | +5 |
| `native_term/commands.rs` | rename_tab + TabInfo | +60 |
| `commands/shortcuts.rs` | new file | +90 |
| `commands/youtube_feed.rs` | rename + rewrite news.rs | +120 |
| `lib.rs` | Register commands | +5 |
| `state.rs` / `paths.rs` | Config seeding helper | +30 |
| `App.tsx` | Tab rename UI + Shortcuts nav + rotator switch | +120 |
| `App.css` | Tab edit input + popover | +40 |
| `components/ShortcutsPanel.tsx` | new file | +130 |
| `components/ShortcutsPanel.css` | new file | +60 |

Total: ~660 lines. Three commits:
1. `feat(native-term): rename tabs via double-click or right-click`
2. `feat(gui): shortcuts panel with synthia hotkeys + shell aliases`
3. `feat(gui): replace news rotator with youtube channel feed`

---

## Testing

### Rust (unit tests in `cargo test --lib`)
- `parse_alias_line` — handles bash + zsh formats, quoted/unquoted expansions, edge cases (empty expansion, equals in expansion).
- `seed_youtube_channels` — when key absent: writes seed; when key present: no-op; when morning config missing: writes empty list.
- `tab_info_serialization` — TabInfo → JSON wire format unchanged for `id` field.

### Manual
- Tab rename:
  - Double-click "Terminal 1" → input appears with text selected.
  - Type "build", Enter → label updates, persists across switching tabs.
  - Right-click → popover appears; Rename works; Close works.
  - Empty name rejected (label stays unchanged, no crash).
- Shortcuts:
  - Open panel → both sections visible.
  - Aliases section populated from `~/.bashrc` content.
  - Search "ll" filters to alias `ll` and any hotkey containing "ll".
  - Click alias name → clipboard contains alias name; row flashes green.
- YouTube:
  - Fresh `~/.config/synthia/config.yaml` with no `youtube:` key → after launch, file gains youtube section seeded from morning config.
  - Status bar rotator shows channel name + title.
  - Click → opens YouTube in default browser.
  - Bad channel ID → errors logged, other channels still appear.

### Quality gates
- `cargo clippy --all-targets -- -D warnings` (zero-warning policy).
- `cargo build --release` succeeds.
- Existing 35 cargo tests still pass.

---

## Out of scope (deferred to v2)
- Tab name persistence across app restart.
- Config-panel CRUD UI for YouTube channels (yaml edit only in v1).
- Synthia-defined custom snippet shortcuts (paste-on-click code blocks).
- Per-channel filters (e.g. "only videos < 30min").
- Thumbnail rendering in rotator (rotator stays text-only).
- Drag-to-reorder tabs.
