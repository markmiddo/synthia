# Tab Rename + Shortcuts Panel + YouTube Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three independent UX enhancements to the Synthia GUI: inline tab rename, a Shortcuts sidebar panel (Synthia hotkeys + shell aliases), and replacement of the AI-news rotator with a curated YouTube channel feed.

**Architecture:** Three loosely-coupled feature slices. Tab rename adds a `custom_titles` map keyed by session id inside `NativeTermRegistry` and a Tauri command that mutates it; `native_term_list_tabs` reads the override before falling back to PTY meta title. Shortcuts panel adds a new sidebar section backed by a Tauri command that shells out to `bash -ic 'alias'` and parses output. YouTube feed renames `commands/news.rs` to `commands/youtube_feed.rs`, parses Atom from `youtube.com/feeds/videos.xml?channel_id=…` for each channel listed in `~/.config/synthia/config.yaml`, and seeds that config from the existing morning-skill JSON on first launch.

**Tech Stack:** Rust (Tauri 2, parking_lot, reqwest, feed-rs, serde_yaml, tokio), React 19 + TypeScript, plain CSS, `tauri-plugin-clipboard-manager`, `tauri-plugin-opener`.

**Spec:** `docs/superpowers/specs/2026-05-14-tab-rename-shortcuts-youtube-design.md`

---

## File Structure

### Created
- `gui/src-tauri/src/commands/shortcuts.rs` — `get_shell_aliases` command, `parse_alias_line` pure helper, in-memory cache.
- `gui/src-tauri/src/commands/youtube_feed.rs` — `get_youtube_videos` command, `read_channels_from_yaml`, `seed_youtube_channels`, `VideoItem`.
- `gui/src/components/ShortcutsPanel.tsx` — Shortcuts panel React component.
- `gui/src/components/ShortcutsPanel.css` — Panel styling.

### Modified
- `gui/src-tauri/src/native_term/mod.rs` — `NativeTermRegistry` gains `custom_titles: Mutex<HashMap<Uuid, String>>`.
- `gui/src-tauri/src/native_term/commands.rs` — `native_term_rename_tab` command; `native_term_list_tabs` reads `custom_titles` override; cleanup hook in `native_term_close_tab`.
- `gui/src-tauri/src/yaml_writer.rs` — `append_youtube_channels` helper.
- `gui/src-tauri/src/commands/mod.rs` — register `shortcuts`, `youtube_feed`; remove `news`.
- `gui/src-tauri/src/lib.rs` — register new commands in `invoke_handler`; call `seed_youtube_channels` in `setup`; drop `news::get_ai_news`.
- `gui/src/App.tsx` — `Section` adds `"shortcuts"`; `terminalTabs` uses backend `TabInfo` shape; rename input + right-click popover; rotator switches from `NewsItem` to `VideoItem`.
- `gui/src/App.css` — input styling for inline rename, popover styling.

### Deleted
- `gui/src-tauri/src/commands/news.rs` — replaced by `youtube_feed.rs`.

---

## Phase 1 — Tab Rename

### Task 1: Add `custom_titles` map + `native_term_rename_tab` command (with unit tests)

**Files:**
- Modify: `gui/src-tauri/src/native_term/mod.rs:120-131`
- Modify: `gui/src-tauri/src/native_term/commands.rs` (add command + tests at bottom)

- [ ] **Step 1: Add custom_titles field to NativeTermRegistry**

In `gui/src-tauri/src/native_term/mod.rs`, change the struct to:

```rust
#[derive(Default)]
pub struct NativeTermRegistry {
    #[allow(dead_code)] // wired up in commands.rs (D Task 13)
    pub sessions: Mutex<HashMap<Uuid, NativeSession>>,
    /// Hidden persistent state keyed by session id.  Each terminal tab
    /// that isn't currently the visible one lives here — PTY + grid +
    /// reader_task keep running so background output is preserved.
    pub persistent: Mutex<HashMap<Uuid, PersistentNativeState>>,
    /// Insertion order of tabs (active + persistent) for stable tab strip
    /// rendering across show/hide cycles.
    pub tab_order: Mutex<Vec<Uuid>>,
    /// User-supplied tab titles.  Overrides the PTY meta title in
    /// `native_term_list_tabs` when present.  Cleared when the tab is
    /// closed.
    pub custom_titles: Mutex<HashMap<Uuid, String>>,
}
```

- [ ] **Step 2: Write the failing rename test**

At the bottom of `gui/src-tauri/src/native_term/commands.rs`, append:

```rust
#[cfg(test)]
mod rename_tests {
    use super::*;

    #[test]
    fn sanitize_rejects_empty() {
        assert_eq!(sanitize_title("").as_deref(), None);
        assert_eq!(sanitize_title("   ").as_deref(), None);
    }

    #[test]
    fn sanitize_trims_and_caps() {
        assert_eq!(sanitize_title("  build  ").as_deref(), Some("build"));
        let long = "a".repeat(80);
        let out = sanitize_title(&long).unwrap();
        assert_eq!(out.chars().count(), 40);
    }

    #[test]
    fn sanitize_strips_control_chars() {
        assert_eq!(
            sanitize_title("hi\nworld\t!").as_deref(),
            Some("hi world !")
        );
    }
}
```

- [ ] **Step 3: Run the test to verify it fails (compile error: `sanitize_title` undefined)**

```bash
cd gui/src-tauri && cargo test --lib native_term::commands::rename_tests
```

Expected: `error[E0425]: cannot find function 'sanitize_title' in this scope`.

- [ ] **Step 4: Implement `sanitize_title` and the rename command**

Add to `gui/src-tauri/src/native_term/commands.rs` (above the `#[cfg(test)]` block):

```rust
/// Trim, collapse whitespace, drop control chars, cap to 40 chars.
/// Returns None when the cleaned result is empty.
fn sanitize_title(input: &str) -> Option<String> {
    let cleaned: String = input
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let trimmed = cleaned.trim();
    if trimmed.is_empty() {
        return None;
    }
    let capped: String = trimmed.chars().take(40).collect();
    Some(capped)
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn native_term_rename_tab(
    app: AppHandle,
    state: State<'_, AppState>,
    tab_id: Uuid,
    title: String,
) -> AppResult<()> {
    let title = sanitize_title(&title)
        .ok_or_else(|| AppError::Invalid("title cannot be empty".into()))?;

    // Confirm the tab actually exists in either map; otherwise return
    // Invalid so callers don't silently store orphan titles.
    let exists = state.native_terminals.sessions.lock().contains_key(&tab_id)
        || state
            .native_terminals
            .persistent
            .lock()
            .contains_key(&tab_id);
    if !exists {
        return Err(AppError::Invalid("unknown tab id".into()));
    }

    state
        .native_terminals
        .custom_titles
        .lock()
        .insert(tab_id, title);

    let _ = app.emit("terminal-tabs-changed", ());
    Ok(())
}
```

If `AppError`, `AppResult`, `AppHandle`, `State`, `emit`, or `Uuid` are not already imported at the top of `commands.rs`, add the missing imports. (Existing tab commands use them, so most should be present — confirm with `cargo build` after Step 5.)

- [ ] **Step 5: Run the tests to verify they pass**

```bash
cd gui/src-tauri && cargo test --lib native_term::commands::rename_tests
```

Expected: `test result: ok. 3 passed`.

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/native_term/mod.rs gui/src-tauri/src/native_term/commands.rs
git commit -m "feat(native-term): add custom_titles map + rename_tab command"
```

---

### Task 2: `native_term_list_tabs` reads `custom_titles` override + cleanup on close

**Files:**
- Modify: `gui/src-tauri/src/native_term/commands.rs:370-389` (list_tabs body)
- Modify: `gui/src-tauri/src/native_term/commands.rs:304-365` (close_tab cleanup)

- [ ] **Step 1: Update `native_term_list_tabs` to prefer custom title**

Replace the body of `native_term_list_tabs` so the loop becomes:

```rust
let active_id = state.native_terminals.sessions.lock().keys().next().copied();
let order = state.native_terminals.tab_order.lock().clone();
let terms = state.terminals.sessions.lock();
let custom = state.native_terminals.custom_titles.lock();
let mut out = Vec::with_capacity(order.len());
for (idx, id) in order.iter().enumerate() {
    let title = custom.get(id).cloned().unwrap_or_else(|| {
        // Fall back to PTY meta title if it has been customised by the
        // shell (e.g. via OSC 0); otherwise use a stable "Terminal N"
        // label so the user always sees a sensible name.
        terms
            .get(id)
            .map(|s| s.meta.title.clone())
            .filter(|t| !t.is_empty() && t != "shell")
            .unwrap_or_else(|| format!("Terminal {}", idx + 1))
    });
    out.push(TabInfo {
        id: *id,
        title,
        is_active: Some(*id) == active_id,
    });
}
Ok(out)
```

- [ ] **Step 2: Drop the custom title when a tab is closed**

In `native_term_close_tab`, after the existing `tab_order` retain line, add:

```rust
state.native_terminals.custom_titles.lock().remove(&tab_id);
```

- [ ] **Step 3: Build to verify (no new tests; behaviour visible in manual smoke after Task 7)**

```bash
cd gui/src-tauri && cargo build --release
```

Expected: build succeeds with no new warnings. If clippy fires (`-D warnings`), fix inline.

```bash
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings
```

Expected: zero warnings.

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/native_term/commands.rs
git commit -m "feat(native-term): list_tabs prefers custom title; cleanup on close"
```

---

### Task 3: Register `native_term_rename_tab` in `lib.rs`

**Files:**
- Modify: `gui/src-tauri/src/lib.rs:422-510` (invoke_handler block)

- [ ] **Step 1: Locate the `invoke_handler` macro call**

Run:

```bash
grep -n "native_term_close_tab" gui/src-tauri/src/lib.rs
```

Expected: one line inside the `tauri::generate_handler!` macro list.

- [ ] **Step 2: Add the new command**

Insert immediately after the line registering `native_term_close_tab`:

```rust
            commands::native_term::native_term_rename_tab,
```

(If `native_term_close_tab` is not registered via `commands::native_term::...` but via the crate path, mirror the same path style. Use `grep` output from Step 1 as the source of truth.)

If the existing tab commands are registered via `crate::native_term::commands::native_term_close_tab`, use that prefix instead. The actual import path is whichever string appears in lib.rs alongside the other `native_term_*` entries.

- [ ] **Step 3: Build**

```bash
cd gui/src-tauri && cargo build --release
```

Expected: build succeeds.

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(native-term): register rename_tab in invoke_handler"
```

---

### Task 4: Frontend tab rename UI (inline input + state)

**Files:**
- Modify: `gui/src/App.tsx` (terminal tabs render block; add `renamingTabId` state)

- [ ] **Step 1: Locate the terminal tabs render block**

Run:

```bash
grep -n "terminal-tab-subitem\|terminalTabs\|setTerminalTabs" gui/src/App.tsx
```

Expected: a state declaration around line 660 (`useState<TabInfo[]>` or similar), a polling effect that calls `native_term_list_tabs`, and a JSX block rendering each tab as a `.terminal-tab-subitem`.

- [ ] **Step 2: Add rename state**

Near the existing `terminalTabs` state declaration, add:

```tsx
const [renamingTabId, setRenamingTabId] = useState<string | null>(null);
const [renameDraft, setRenameDraft] = useState<string>("");
```

- [ ] **Step 3: Add the rename submit helper**

Above the JSX render block (or alongside the other terminal handlers), add:

```tsx
async function commitRename() {
  if (!renamingTabId) return;
  const next = renameDraft.trim();
  if (!next) {
    setRenamingTabId(null);
    return;
  }
  try {
    await invoke("native_term_rename_tab", {
      tabId: renamingTabId,
      title: next,
    });
    // The terminal-tabs-changed event will refresh the list; force a
    // local refresh too so the UI updates immediately even if the event
    // listener hasn't fired yet.
    const tabs = await invoke<TabInfo[]>("native_term_list_tabs");
    setTerminalTabs(tabs);
  } catch (err) {
    console.error("rename failed", err);
  } finally {
    setRenamingTabId(null);
  }
}
```

- [ ] **Step 4: Replace the tab subitem render with rename-aware version**

Inside the `.terminal-tab-sublist` map, replace each tab subitem with:

```tsx
{terminalTabs.map((tab) => {
  const isRenaming = renamingTabId === tab.id;
  return (
    <div
      key={tab.id}
      className={`terminal-tab-subitem${tab.is_active ? " active" : ""}`}
      onClick={() => {
        if (isRenaming) return;
        handleTerminalSwitchTab(tab.id);
      }}
      onDoubleClick={(e) => {
        e.stopPropagation();
        setRenameDraft(tab.title);
        setRenamingTabId(tab.id);
      }}
      onContextMenu={(e) => {
        e.preventDefault();
        openTabContextMenu(tab.id, e.clientX, e.clientY);
      }}
    >
      {isRenaming ? (
        <input
          className="terminal-tab-subitem-input"
          autoFocus
          value={renameDraft}
          maxLength={40}
          onChange={(e) => setRenameDraft(e.target.value)}
          onClick={(e) => e.stopPropagation()}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") setRenamingTabId(null);
          }}
          onBlur={() => commitRename()}
        />
      ) : (
        <span className="terminal-tab-subitem-title">{tab.title}</span>
      )}
    </div>
  );
})}
```

`TabInfo` should already be a TS type matching `{ id: string; title: string; is_active: boolean }` from the polling effect — if not, add it adjacent to the state declaration.

- [ ] **Step 5: Build the GUI quickly to catch typos**

```bash
cd gui && npm run build
```

Expected: Vite build succeeds. If TS complains about `TabInfo` shape, update the type to match the JSON returned by `native_term_list_tabs`.

- [ ] **Step 6: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): inline tab rename via double-click"
```

---

### Task 5: Right-click popover (Rename + Close)

**Files:**
- Modify: `gui/src/App.tsx` (add context menu state + render)

- [ ] **Step 1: Add popover state**

Near the rename state, add:

```tsx
const [tabMenu, setTabMenu] = useState<{
  tabId: string;
  x: number;
  y: number;
} | null>(null);
```

- [ ] **Step 2: Add openTabContextMenu helper and dismiss-on-outside-click effect**

```tsx
function openTabContextMenu(tabId: string, x: number, y: number) {
  setTabMenu({ tabId, x, y });
}

useEffect(() => {
  if (!tabMenu) return;
  const dismiss = () => setTabMenu(null);
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") setTabMenu(null);
  };
  window.addEventListener("click", dismiss);
  window.addEventListener("keydown", onKey);
  return () => {
    window.removeEventListener("click", dismiss);
    window.removeEventListener("keydown", onKey);
  };
}, [tabMenu]);
```

- [ ] **Step 3: Render the popover**

Place this once at the top level of the sidebar return (sibling of `.sidebar`):

```tsx
{tabMenu && (
  <div
    className="terminal-tab-context-menu"
    style={{ left: tabMenu.x, top: tabMenu.y }}
    onClick={(e) => e.stopPropagation()}
  >
    <button
      className="terminal-tab-context-item"
      onClick={() => {
        const tab = terminalTabs.find((t) => t.id === tabMenu.tabId);
        if (tab) {
          setRenameDraft(tab.title);
          setRenamingTabId(tab.id);
        }
        setTabMenu(null);
      }}
    >
      Rename
    </button>
    <button
      className="terminal-tab-context-item"
      onClick={() => {
        handleTerminalCloseTab(tabMenu.tabId);
        setTabMenu(null);
      }}
    >
      Close
    </button>
  </div>
)}
```

- [ ] **Step 4: Build**

```bash
cd gui && npm run build
```

Expected: success.

- [ ] **Step 5: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): right-click context menu for terminal tabs"
```

---

### Task 6: CSS for rename input + context menu

**Files:**
- Modify: `gui/src/App.css` (append styles)

- [ ] **Step 1: Append styles to App.css**

```css
.terminal-tab-subitem-input {
  width: 100%;
  background: transparent;
  border: none;
  border-bottom: 1px solid #22d3ee;
  color: #22d3ee;
  font-family: inherit;
  font-size: inherit;
  padding: 0;
  outline: none;
}

.terminal-tab-context-menu {
  position: fixed;
  z-index: 9999;
  min-width: 140px;
  background: #11151c;
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.45);
  padding: 4px 0;
  display: flex;
  flex-direction: column;
}

.terminal-tab-context-item {
  background: transparent;
  border: none;
  color: rgba(226, 232, 240, 0.85);
  padding: 6px 14px;
  text-align: left;
  font: inherit;
  cursor: pointer;
}

.terminal-tab-context-item:hover {
  background: rgba(34, 211, 238, 0.10);
  color: #22d3ee;
}
```

- [ ] **Step 2: Commit**

```bash
git add gui/src/App.css
git commit -m "style(gui): inline rename input + tab context menu"
```

---

### Task 7: Build, install, manual smoke for tab rename

- [ ] **Step 1: Build full deb**

```bash
cd gui && npm run tauri build -- --bundles deb
```

Expected: deb at `gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb`.

- [ ] **Step 2: Install + launch**

```bash
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb
pkill -f synthia-gui || true
nohup /usr/bin/synthia-gui >/tmp/synthia-gui.log 2>&1 &
```

- [ ] **Step 3: Verify in app**
  - Open Terminal panel.
  - Spawn 2 tabs.
  - Double-click "Terminal 1" → input appears, type "build", Enter → label updates.
  - Right-click "Terminal 2" → popover appears → click Rename → edit → Enter.
  - Right-click → Close → tab disappears.
  - Switch tabs; renamed labels persist.

- [ ] **Step 4: If anything broken, fix and re-run Step 1. Otherwise no commit (Phase 1 done).**

---

## Phase 2 — Shortcuts Sidebar Panel

### Task 8: `parse_alias_line` pure helper + tests

**Files:**
- Create: `gui/src-tauri/src/commands/shortcuts.rs`

- [ ] **Step 1: Create the file with failing tests**

```rust
//! Sidebar Shortcuts panel data source.
//!
//! Surfaces shell aliases (parsed from `bash -ic 'alias'` output) and a
//! static list of Synthia hotkeys to the Tauri frontend.

use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Serialize;
use tokio::process::Command;
use tokio::time::timeout;

const CACHE_TTL: Duration = Duration::from_secs(60);
const SHELL_TIMEOUT: Duration = Duration::from_secs(5);

static CACHE: Mutex<Option<(Vec<AliasEntry>, Instant)>> = Mutex::new(None);

#[derive(Serialize, Clone, Debug, PartialEq, Eq)]
pub struct AliasEntry {
    pub name: String,
    pub expansion: String,
}

/// Parse a single line of `alias` builtin output.
///
/// Accepts both bash's `alias name='expansion'` and zsh's `name='expansion'`
/// styles. Returns None for lines that don't match (blank lines,
/// continuations, garbage).
pub fn parse_alias_line(line: &str) -> Option<AliasEntry> {
    let stripped = line.trim().strip_prefix("alias ").unwrap_or_else(|| line.trim());
    let (name, raw_expansion) = stripped.split_once('=')?;
    let name = name.trim();
    if name.is_empty() || name.contains(char::is_whitespace) {
        return None;
    }
    let expansion = raw_expansion.trim();
    let unquoted = if (expansion.starts_with('\'') && expansion.ends_with('\''))
        || (expansion.starts_with('"') && expansion.ends_with('"'))
    {
        if expansion.len() >= 2 {
            &expansion[1..expansion.len() - 1]
        } else {
            expansion
        }
    } else {
        expansion
    };
    Some(AliasEntry {
        name: name.to_string(),
        expansion: unquoted.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bash_format() {
        assert_eq!(
            parse_alias_line("alias ll='ls -la'"),
            Some(AliasEntry {
                name: "ll".into(),
                expansion: "ls -la".into(),
            })
        );
    }

    #[test]
    fn zsh_format() {
        assert_eq!(
            parse_alias_line("ll='ls -la'"),
            Some(AliasEntry {
                name: "ll".into(),
                expansion: "ls -la".into(),
            })
        );
    }

    #[test]
    fn double_quoted_expansion() {
        assert_eq!(
            parse_alias_line(r#"alias gp="git push""#),
            Some(AliasEntry {
                name: "gp".into(),
                expansion: "git push".into(),
            })
        );
    }

    #[test]
    fn unquoted_expansion() {
        assert_eq!(
            parse_alias_line("alias here=pwd"),
            Some(AliasEntry {
                name: "here".into(),
                expansion: "pwd".into(),
            })
        );
    }

    #[test]
    fn equals_in_expansion() {
        assert_eq!(
            parse_alias_line("alias kubectl='kubectl --context=prod'"),
            Some(AliasEntry {
                name: "kubectl".into(),
                expansion: "kubectl --context=prod".into(),
            })
        );
    }

    #[test]
    fn rejects_blank_and_garbage() {
        assert_eq!(parse_alias_line(""), None);
        assert_eq!(parse_alias_line("   "), None);
        assert_eq!(parse_alias_line("nope no equals here"), None);
        assert_eq!(parse_alias_line("=bare"), None);
        assert_eq!(parse_alias_line("name with space='x'"), None);
    }
}
```

- [ ] **Step 2: Add the module declaration**

In `gui/src-tauri/src/commands/mod.rs`, add:

```rust
pub mod shortcuts;
```

- [ ] **Step 3: Run the tests**

```bash
cd gui/src-tauri && cargo test --lib commands::shortcuts::tests
```

Expected: `test result: ok. 6 passed`.

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/commands/shortcuts.rs gui/src-tauri/src/commands/mod.rs
git commit -m "feat(gui): parse_alias_line helper for shortcuts panel"
```

---

### Task 9: `get_shell_aliases` Tauri command

**Files:**
- Modify: `gui/src-tauri/src/commands/shortcuts.rs`

- [ ] **Step 1: Append the command + cache lookup**

```rust
fn detect_shell() -> String {
    std::env::var("SHELL")
        .ok()
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "/bin/bash".into())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs
pub async fn get_shell_aliases() -> Vec<AliasEntry> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, fetched_at)) = guard.as_ref() {
            if fetched_at.elapsed() < CACHE_TTL {
                return items.clone();
            }
        }
    }

    let shell = detect_shell();
    let result = timeout(
        SHELL_TIMEOUT,
        Command::new(&shell).args(["-ic", "alias"]).output(),
    )
    .await;

    let output = match result {
        Ok(Ok(out)) => out,
        _ => return cached_or_empty(),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut entries: Vec<AliasEntry> = stdout.lines().filter_map(parse_alias_line).collect();
    entries.sort_by(|a, b| a.name.cmp(&b.name));
    entries.dedup_by(|a, b| a.name == b.name);

    if let Ok(mut guard) = CACHE.lock() {
        *guard = Some((entries.clone(), Instant::now()));
    }
    entries
}

fn cached_or_empty() -> Vec<AliasEntry> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, _)) = guard.as_ref() {
            return items.clone();
        }
    }
    Vec::new()
}
```

- [ ] **Step 2: Build**

```bash
cd gui/src-tauri && cargo build --release
```

Expected: success. If `tokio::process::Command` or `tokio::time::timeout` is missing from Cargo.toml feature flags, add `process` and `time` to the existing `tokio` features list (likely already enabled — confirm by reading `gui/src-tauri/Cargo.toml`).

- [ ] **Step 3: Clippy gate**

```bash
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings
```

Expected: zero warnings.

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/commands/shortcuts.rs
git commit -m "feat(gui): get_shell_aliases tauri command with 60s cache"
```

---

### Task 10: Register `get_shell_aliases` in `lib.rs`

**Files:**
- Modify: `gui/src-tauri/src/lib.rs` (invoke_handler)

- [ ] **Step 1: Add to invoke_handler**

Inside the `tauri::generate_handler!` block, append:

```rust
            commands::shortcuts::get_shell_aliases,
```

- [ ] **Step 2: Build**

```bash
cd gui/src-tauri && cargo build --release
```

Expected: success.

- [ ] **Step 3: Commit**

```bash
git add gui/src-tauri/src/lib.rs
git commit -m "feat(gui): register get_shell_aliases in invoke_handler"
```

---

### Task 11: `ShortcutsPanel.tsx` component

**Files:**
- Create: `gui/src/components/ShortcutsPanel.tsx`

- [ ] **Step 1: Create the component**

```tsx
import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import "./ShortcutsPanel.css";

type AliasEntry = { name: string; expansion: string };

type Hotkey = { keys: string; action: string; scope: string };

const SYNTHIA_HOTKEYS: Hotkey[] = [
  { keys: "Right Ctrl", action: "Voice dictation", scope: "Global" },
  { keys: "Right Alt", action: "AI assistant", scope: "Global" },
  { keys: "Alt+T", action: "New terminal tab", scope: "Terminal focused" },
  { keys: "Alt+W", action: "Close active tab", scope: "Terminal focused" },
  { keys: "Ctrl+Shift+Tab", action: "Cycle tabs", scope: "Terminal focused" },
  { keys: "Ctrl+C", action: "Copy selection", scope: "Terminal focused" },
  { keys: "Ctrl+V", action: "Paste from clipboard", scope: "Terminal focused" },
  { keys: "Drag file in", action: "Insert file path", scope: "Terminal focused" },
];

export function ShortcutsPanel() {
  const [aliases, setAliases] = useState<AliasEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [flashName, setFlashName] = useState<string | null>(null);

  useEffect(() => {
    invoke<AliasEntry[]>("get_shell_aliases")
      .then(setAliases)
      .catch((err) => console.error("get_shell_aliases failed", err));
  }, []);

  const needle = filter.trim().toLowerCase();
  const filteredHotkeys = useMemo(
    () =>
      SYNTHIA_HOTKEYS.filter(
        (h) =>
          !needle ||
          h.keys.toLowerCase().includes(needle) ||
          h.action.toLowerCase().includes(needle),
      ),
    [needle],
  );
  const filteredAliases = useMemo(
    () =>
      aliases.filter(
        (a) =>
          !needle ||
          a.name.toLowerCase().includes(needle) ||
          a.expansion.toLowerCase().includes(needle),
      ),
    [aliases, needle],
  );

  async function copyAlias(name: string) {
    try {
      await writeText(name);
      setFlashName(name);
      window.setTimeout(() => setFlashName(null), 600);
    } catch (err) {
      console.error("clipboard write failed", err);
    }
  }

  return (
    <div className="shortcuts-panel">
      <input
        className="shortcuts-search"
        placeholder="Search shortcuts and aliases…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="shortcuts-section-header">Synthia hotkeys</div>
      <div className="shortcuts-table">
        {filteredHotkeys.length === 0 ? (
          <div className="shortcuts-empty">No matches.</div>
        ) : (
          filteredHotkeys.map((h) => (
            <div className="shortcuts-row" key={h.keys}>
              <span className="shortcuts-keys">{h.keys}</span>
              <span className="shortcuts-action">
                {h.action}
                <span className="shortcuts-scope"> · {h.scope}</span>
              </span>
            </div>
          ))
        )}
      </div>

      <div className="shortcuts-section-header">Shell aliases</div>
      <div className="shortcuts-table">
        {aliases.length === 0 ? (
          <div className="shortcuts-empty">
            No aliases found in your shell rc files.
          </div>
        ) : filteredAliases.length === 0 ? (
          <div className="shortcuts-empty">No matches.</div>
        ) : (
          filteredAliases.map((a) => (
            <button
              type="button"
              className={`shortcuts-row clickable${
                flashName === a.name ? " flash" : ""
              }`}
              key={a.name}
              onClick={() => copyAlias(a.name)}
              title="Click to copy alias name"
            >
              <span className="shortcuts-keys">{a.name}</span>
              <span className="shortcuts-action">{a.expansion}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build (typecheck only)**

```bash
cd gui && npm run build
```

Expected: success. If `@tauri-apps/plugin-clipboard-manager` is missing from `package.json`, install it (`npm i @tauri-apps/plugin-clipboard-manager`) — but the spec assumes it's already present from prior terminal copy/paste work.

- [ ] **Step 3: Commit**

```bash
git add gui/src/components/ShortcutsPanel.tsx
git commit -m "feat(gui): ShortcutsPanel component with hotkeys + aliases"
```

---

### Task 12: ShortcutsPanel CSS

**Files:**
- Create: `gui/src/components/ShortcutsPanel.css`

- [ ] **Step 1: Create the file**

```css
.shortcuts-panel {
  padding: 24px 32px;
  color: rgba(226, 232, 240, 0.85);
  font-size: 13px;
}

.shortcuts-search {
  width: 100%;
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  color: #e2e8f0;
  padding: 8px 12px;
  font: inherit;
  outline: none;
  margin-bottom: 18px;
}

.shortcuts-search:focus {
  border-color: #22d3ee;
}

.shortcuts-section-header {
  font-size: 11px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.40);
  margin: 18px 0 6px;
}

.shortcuts-table {
  display: flex;
  flex-direction: column;
}

.shortcuts-row {
  display: grid;
  grid-template-columns: 180px 1fr;
  gap: 16px;
  padding: 6px 8px;
  align-items: baseline;
  background: transparent;
  border: none;
  text-align: left;
  font: inherit;
  color: inherit;
  border-radius: 3px;
}

.shortcuts-row.clickable {
  cursor: pointer;
}

.shortcuts-row.clickable:hover {
  background: rgba(34, 211, 238, 0.06);
}

.shortcuts-row.flash {
  background: rgba(34, 197, 94, 0.18);
  transition: background 0.6s ease-out;
}

.shortcuts-keys {
  font-family: ui-monospace, "JetBrains Mono", monospace;
  color: #22d3ee;
  font-size: 12px;
}

.shortcuts-action {
  color: rgba(226, 232, 240, 0.65);
  word-break: break-word;
}

.shortcuts-scope {
  color: rgba(255, 255, 255, 0.30);
  font-size: 11px;
}

.shortcuts-empty {
  color: rgba(255, 255, 255, 0.30);
  padding: 6px 8px;
  font-style: italic;
}
```

- [ ] **Step 2: Commit**

```bash
git add gui/src/components/ShortcutsPanel.css
git commit -m "style(gui): ShortcutsPanel layout"
```

---

### Task 13: Wire `Shortcuts` into the sidebar nav

**Files:**
- Modify: `gui/src/App.tsx`

- [ ] **Step 1: Extend the `Section` union**

Locate `type Section = ...` (line ~400) and add `"shortcuts"`:

```tsx
type Section =
  | "worktrees"
  | "terminal"
  | "shortcuts"
  | "knowledge"
  | "agents"
  | "security"
  | "voice"
  | "memory"
  | "config"
  | "github";
```

- [ ] **Step 2: Add the import**

Near the other component imports at the top of `App.tsx`:

```tsx
import { ShortcutsPanel } from "./components/ShortcutsPanel";
```

- [ ] **Step 3: Add a sidebar nav item**

Find where Terminal nav item is rendered in the sidebar (search for `"terminal"` and the surrounding nav button JSX). Add an analogous button immediately below the Terminal one:

```tsx
<button
  type="button"
  className={`nav-item${currentSection === "shortcuts" ? " active" : ""}`}
  onClick={() => setCurrentSection("shortcuts")}
>
  <span className="nav-item-label">Shortcuts</span>
</button>
```

(Use the exact class names + structure of the adjacent nav buttons. The snippet above is illustrative — match the existing pattern.)

- [ ] **Step 4: Render the panel when section is active**

Find the section-router area (where other sections render `<JournalPanel />`, etc.) and add:

```tsx
{currentSection === "shortcuts" && <ShortcutsPanel />}
```

- [ ] **Step 5: Build**

```bash
cd gui && npm run build
```

Expected: success.

- [ ] **Step 6: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): Shortcuts nav item + render"
```

---

### Task 14: Build, install, smoke for Shortcuts panel

- [ ] **Step 1: Build deb + install + relaunch**

```bash
cd gui && npm run tauri build -- --bundles deb
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb
pkill -f synthia-gui || true
nohup /usr/bin/synthia-gui >/tmp/synthia-gui.log 2>&1 &
```

- [ ] **Step 2: Verify**
  - Click Shortcuts in sidebar.
  - Two sections render: Synthia hotkeys (8 rows) and Shell aliases (populated from your `~/.bashrc`).
  - Type "ll" in search → both lists filter.
  - Click an alias row → row briefly flashes green; pasting elsewhere yields the alias name.
  - Empty input is handled gracefully.

- [ ] **Step 3: If broken, fix and rebuild. Otherwise no commit (Phase 2 done).**

---

## Phase 3 — YouTube Feed Replaces News Rotator

### Task 15: `append_youtube_channels` yaml writer + tests

**Files:**
- Modify: `gui/src-tauri/src/yaml_writer.rs`

- [ ] **Step 1: Append the helper to the file**

```rust
/// Append a `youtube:` section (with nested `channels:` list) to a Synthia
/// config file IF no `youtube:` top-level key already exists. Returns the
/// input unchanged when the section is already present — this is one-shot
/// seeding, never an overwrite.
pub fn append_youtube_channels(existing: &str, channels: &[(String, String)]) -> String {
    // Detect existing top-level `youtube:` key.
    let already_present = existing.lines().any(|line| {
        let is_top_level = !line.starts_with(|c: char| c.is_whitespace());
        is_top_level && line.trim_start().starts_with("youtube:")
    });
    if already_present {
        return existing.to_string();
    }

    let ends_newline = existing.ends_with('\n');
    let mut out = String::from(existing);
    if !out.is_empty() && !out.ends_with("\n\n") {
        if !out.ends_with('\n') {
            out.push('\n');
        }
        out.push('\n');
    }
    out.push_str("# YouTube channels for the status-bar video feed.\n");
    out.push_str("# Find a channel id by visiting the channel page and viewing source for `channelId`.\n");
    out.push_str("youtube:\n");
    out.push_str("  channels:\n");
    for (name, id) in channels {
        out.push_str(&format!("    - name: \"{}\"\n      id: \"{}\"\n", escape(name), escape(id)));
    }

    if !ends_newline && out.ends_with('\n') {
        out.pop();
    }
    out
}

fn escape(s: &str) -> String {
    s.replace('\\', "\\\\").replace('"', "\\\"")
}
```

- [ ] **Step 2: Add tests at the bottom of the file (or in the existing `#[cfg(test)]` module)**

```rust
#[cfg(test)]
mod youtube_seed_tests {
    use super::*;

    #[test]
    fn appends_when_absent() {
        let existing = "stt_engine: cloud\ntts_engine: piper\n";
        let channels = vec![
            ("Cole".into(), "UC1".into()),
            ("AI Code King".into(), "UC2".into()),
        ];
        let out = append_youtube_channels(existing, &channels);
        assert!(out.contains("youtube:"));
        assert!(out.contains("- name: \"Cole\""));
        assert!(out.contains("id: \"UC2\""));
        // Original keys preserved
        assert!(out.contains("stt_engine: cloud"));
    }

    #[test]
    fn no_op_when_present() {
        let existing = "youtube:\n  channels: []\n";
        let channels = vec![("Cole".into(), "UC1".into())];
        let out = append_youtube_channels(existing, &channels);
        assert_eq!(out, existing);
    }

    #[test]
    fn escapes_quotes_in_name() {
        let out = append_youtube_channels(
            "",
            &[(r#"My "favourite" channel"#.into(), "UC".into())],
        );
        assert!(out.contains(r#"name: "My \"favourite\" channel""#));
    }
}
```

- [ ] **Step 3: Run the tests**

```bash
cd gui/src-tauri && cargo test --lib yaml_writer::youtube_seed_tests
```

Expected: `test result: ok. 3 passed`.

- [ ] **Step 4: Commit**

```bash
git add gui/src-tauri/src/yaml_writer.rs
git commit -m "feat(gui): append_youtube_channels yaml seed helper"
```

---

### Task 16: Replace `commands/news.rs` with `commands/youtube_feed.rs`

**Files:**
- Delete: `gui/src-tauri/src/commands/news.rs`
- Create: `gui/src-tauri/src/commands/youtube_feed.rs`
- Modify: `gui/src-tauri/src/commands/mod.rs`

- [ ] **Step 1: Create youtube_feed.rs**

```rust
//! YouTube channel feed for the status-bar rotator.
//!
//! Reads channel ids from `~/.config/synthia/config.yaml`'s `youtube.channels`
//! key, fetches each channel's Atom feed in parallel, merges + sorts by
//! published timestamp, and returns the top 12 most recent videos. The
//! request-level cache (30 minutes) keeps the rotator cheap to poll.

use std::path::PathBuf;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

use futures::future::join_all;
use serde::{Deserialize, Serialize};
use serde_yaml::Value;

const CACHE_TTL: Duration = Duration::from_secs(30 * 60);
const MAX_ITEMS: usize = 12;
const PER_REQUEST_TIMEOUT: Duration = Duration::from_secs(8);

static HTTP: OnceLock<reqwest::Client> = OnceLock::new();
static CACHE: Mutex<Option<(Vec<VideoItem>, Instant)>> = Mutex::new(None);

fn http_client() -> &'static reqwest::Client {
    HTTP.get_or_init(|| {
        reqwest::Client::builder()
            .timeout(PER_REQUEST_TIMEOUT)
            .user_agent("synthia-gui/0.1.0 (+https://synthia-ai.com)")
            .build()
            .expect("reqwest client builds")
    })
}

#[derive(Serialize, Clone, Debug)]
pub struct VideoItem {
    pub title: String,
    pub channel_name: String,
    pub video_url: String,
    pub thumbnail_url: Option<String>,
    pub published: Option<String>,
}

#[derive(Deserialize, Debug, Clone)]
pub struct ChannelEntry {
    pub name: String,
    pub id: String,
}

fn synthia_config_path() -> PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| "/".into());
    PathBuf::from(home).join(".config/synthia/config.yaml")
}

/// Read the YouTube channel list from `~/.config/synthia/config.yaml`.
/// Missing file, missing key, or malformed YAML all yield an empty Vec —
/// the rotator just shows nothing rather than crashing.
pub fn read_channels_from_yaml(path: &std::path::Path) -> Vec<ChannelEntry> {
    let body = match std::fs::read_to_string(path) {
        Ok(s) => s,
        Err(_) => return Vec::new(),
    };
    let root: Value = match serde_yaml::from_str(&body) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };
    let channels = match root.get("youtube").and_then(|y| y.get("channels")) {
        Some(c) => c,
        None => return Vec::new(),
    };
    serde_yaml::from_value::<Vec<ChannelEntry>>(channels.clone()).unwrap_or_default()
}

#[tauri::command]
pub async fn get_youtube_videos() -> Vec<VideoItem> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, fetched_at)) = guard.as_ref() {
            if fetched_at.elapsed() < CACHE_TTL {
                return items.clone();
            }
        }
    }

    let channels = read_channels_from_yaml(&synthia_config_path());
    if channels.is_empty() {
        return cached_or_empty();
    }

    let client = http_client();
    let fetches = channels
        .iter()
        .map(|ch| fetch_channel(client, ch.clone()));
    let results = join_all(fetches).await;

    let mut all: Vec<VideoItem> = results.into_iter().flatten().collect();
    all.sort_by(|a, b| b.published.cmp(&a.published));
    all.truncate(MAX_ITEMS);

    if let Ok(mut guard) = CACHE.lock() {
        *guard = Some((all.clone(), Instant::now()));
    }
    all
}

async fn fetch_channel(client: &reqwest::Client, ch: ChannelEntry) -> Vec<VideoItem> {
    let url = format!(
        "https://www.youtube.com/feeds/videos.xml?channel_id={}",
        ch.id
    );
    let body = match client.get(&url).send().await {
        Ok(r) => match r.bytes().await {
            Ok(b) => b,
            Err(_) => return Vec::new(),
        },
        Err(_) => return Vec::new(),
    };
    let parsed = match feed_rs::parser::parse(body.as_ref()) {
        Ok(f) => f,
        Err(_) => return Vec::new(),
    };

    parsed
        .entries
        .into_iter()
        .filter_map(|entry| {
            let title = entry.title.map(|t| t.content)?;
            let video_url = entry.links.first().map(|l| l.href.clone())?;
            let published = entry.published.map(|d| d.to_rfc3339());
            let thumbnail_url = entry
                .media
                .iter()
                .flat_map(|m| m.thumbnails.iter())
                .next()
                .map(|t| t.image.uri.clone());
            Some(VideoItem {
                title,
                channel_name: ch.name.clone(),
                video_url,
                thumbnail_url,
                published,
            })
        })
        .collect()
}

fn cached_or_empty() -> Vec<VideoItem> {
    if let Ok(guard) = CACHE.lock() {
        if let Some((items, _)) = guard.as_ref() {
            return items.clone();
        }
    }
    Vec::new()
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn read_channels_missing_file() {
        let p = std::path::Path::new("/tmp/synthia-test-nonexistent.yaml");
        let _ = std::fs::remove_file(p);
        assert!(read_channels_from_yaml(p).is_empty());
    }

    #[test]
    fn read_channels_missing_key() {
        let p = std::env::temp_dir().join("synthia-test-no-yt.yaml");
        let mut f = std::fs::File::create(&p).unwrap();
        writeln!(f, "stt_engine: cloud").unwrap();
        assert!(read_channels_from_yaml(&p).is_empty());
        let _ = std::fs::remove_file(&p);
    }

    #[test]
    fn read_channels_full_section() {
        let p = std::env::temp_dir().join("synthia-test-yt.yaml");
        let mut f = std::fs::File::create(&p).unwrap();
        writeln!(
            f,
            "youtube:\n  channels:\n    - name: \"Cole\"\n      id: \"UC1\"\n    - name: \"AI King\"\n      id: \"UC2\"\n"
        )
        .unwrap();
        let chans = read_channels_from_yaml(&p);
        assert_eq!(chans.len(), 2);
        assert_eq!(chans[0].name, "Cole");
        assert_eq!(chans[1].id, "UC2");
        let _ = std::fs::remove_file(&p);
    }
}
```

- [ ] **Step 2: Confirm `futures` and `serde_yaml` are in `Cargo.toml`**

```bash
grep -E "^futures|^serde_yaml|^feed-rs|^reqwest" gui/src-tauri/Cargo.toml
```

Expected: `feed-rs`, `reqwest`, `serde_yaml` already present (used by news.rs and yaml_writer.rs). If `futures` is missing, add `futures = "0.3"` to `[dependencies]`.

- [ ] **Step 3: Update commands/mod.rs**

```bash
grep -n "pub mod news;" gui/src-tauri/src/commands/mod.rs
```

Replace that line with:

```rust
pub mod youtube_feed;
```

- [ ] **Step 4: Delete the old news.rs**

```bash
git rm gui/src-tauri/src/commands/news.rs
```

- [ ] **Step 5: Run tests**

```bash
cd gui/src-tauri && cargo test --lib commands::youtube_feed::tests
```

Expected: `test result: ok. 3 passed`.

- [ ] **Step 6: Build (will fail at lib.rs handler register, fix in next task)**

```bash
cd gui/src-tauri && cargo build --release 2>&1 | tail -30
```

Expected: error referencing `commands::news::get_ai_news` in `lib.rs`. That's OK — fixed in Task 17.

- [ ] **Step 7: Commit (with note that lib.rs follow-up is Task 17)**

```bash
git add gui/src-tauri/src/commands/youtube_feed.rs gui/src-tauri/src/commands/mod.rs
# news.rs already staged for deletion via git rm
git commit -m "feat(gui): replace news.rs with youtube_feed.rs"
```

---

### Task 17: Update `lib.rs` — register `get_youtube_videos`, add seeding

**Files:**
- Modify: `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Replace the news handler line**

Locate `commands::news::get_ai_news` and replace with:

```rust
            commands::youtube_feed::get_youtube_videos,
```

- [ ] **Step 2: Add `seed_youtube_channels` helper above the builder**

Place this function near the top of `lib.rs` (above the `pub fn run()` or wherever other helpers live):

```rust
/// One-shot seeding: when the Synthia config has no `youtube:` key, copy the
/// channel list from the morning skill's config.json (if it exists). Skipped
/// silently on any I/O error.
fn seed_youtube_channels() {
    let cfg_path = get_config_path();
    let existing = std::fs::read_to_string(&cfg_path).unwrap_or_default();
    if existing.lines().any(|l| {
        !l.starts_with(|c: char| c.is_whitespace()) && l.trim_start().starts_with("youtube:")
    }) {
        return;
    }

    let home = std::env::var("HOME").unwrap_or_default();
    let morning_path = std::path::PathBuf::from(home)
        .join(".claude/skills/morning/config.json");
    let raw = std::fs::read_to_string(&morning_path).unwrap_or_default();
    let parsed: serde_json::Value = match serde_json::from_str(&raw) {
        Ok(v) => v,
        Err(_) => return,
    };
    let channels: Vec<(String, String)> = parsed
        .get("youtube")
        .and_then(|y| y.get("channels"))
        .and_then(|c| c.as_array())
        .map(|arr| {
            arr.iter()
                .filter_map(|item| {
                    let name = item.get("name")?.as_str()?.to_string();
                    let id = item.get("id")?.as_str()?.to_string();
                    Some((name, id))
                })
                .collect()
        })
        .unwrap_or_default();

    let updated = crate::yaml_writer::append_youtube_channels(&existing, &channels);
    if updated != existing {
        if let Some(parent) = cfg_path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&cfg_path, updated);
    }
}
```

If `serde_json` is not currently a direct dep of the GUI crate, check `Cargo.toml` — it's almost certainly transitive via Tauri. Add `serde_json = "1"` to `[dependencies]` if needed.

- [ ] **Step 3: Call the seed in the Tauri `setup` callback**

Find the `.setup(|app| { ... })` block in the builder. Inside the closure body, near the top:

```rust
seed_youtube_channels();
```

- [ ] **Step 4: Build**

```bash
cd gui/src-tauri && cargo build --release
```

Expected: build succeeds.

- [ ] **Step 5: Clippy**

```bash
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings
```

Expected: zero warnings.

- [ ] **Step 6: Commit**

```bash
git add gui/src-tauri/src/lib.rs gui/src-tauri/Cargo.toml 2>/dev/null
git commit -m "feat(gui): register youtube_videos handler + first-launch seeding"
```

---

### Task 18: Frontend — switch rotator from `NewsItem` to `VideoItem`

**Files:**
- Modify: `gui/src/App.tsx` (NewsItem interface, fetch, render)

- [ ] **Step 1: Replace the `NewsItem` interface**

Locate the `interface NewsItem { ... }` block (~line 78) and replace with:

```tsx
interface VideoItem {
  title: string;
  channel_name: string;
  video_url: string;
  thumbnail_url: string | null;
  published: string | null;
}
```

- [ ] **Step 2: Rename state**

Replace:

```tsx
const [news, setNews] = useState<NewsItem[]>([]);
```

with:

```tsx
const [videos, setVideos] = useState<VideoItem[]>([]);
const [videoIndex, setVideoIndex] = useState(0);
```

(Drop the existing `setNewsIndex` declaration if present — `setVideoIndex` replaces it. Also remove the existing `newsIndex` state line.)

- [ ] **Step 3: Update fetch + rotation**

Replace the existing news fetch effect:

```tsx
useEffect(() => {
  let cancelled = false;
  (async () => {
    try {
      const items = await invoke<VideoItem[]>("get_youtube_videos");
      if (!cancelled) setVideos(items);
    } catch (err) {
      console.error("get_youtube_videos failed", err);
    }
  })();
  const interval = window.setInterval(async () => {
    try {
      const items = await invoke<VideoItem[]>("get_youtube_videos");
      if (!cancelled) setVideos(items);
    } catch (err) {
      console.error("get_youtube_videos refresh failed", err);
    }
  }, 30 * 60 * 1000);
  return () => {
    cancelled = true;
    window.clearInterval(interval);
  };
}, []);

useEffect(() => {
  if (videos.length <= 1) return;
  const t = window.setInterval(() => {
    setVideoIndex((i) => (i + 1) % videos.length);
  }, 6000);
  return () => window.clearInterval(t);
}, [videos.length]);
```

(Reuse the rotation cadence the news rotator already used; the snippet above uses 6 s — match the existing value.)

- [ ] **Step 4: Update the rotator render**

Locate the JSX block guarded by `news.length > 0` and replace with:

```tsx
{videos.length > 0 && (
  <button
    type="button"
    className="status-bar-rotator"
    onClick={() => {
      const v = videos[videoIndex];
      if (v) invoke("opener_open_url", { url: v.video_url }).catch(() => {});
    }}
  >
    <span className="status-bar-rotator-source">
      {videos[videoIndex]?.channel_name ?? ""}
    </span>
    <span className="status-bar-rotator-title">
      {videos[videoIndex]?.title ?? ""}
    </span>
  </button>
)}
```

If the existing rotator opens URLs via the opener plugin's TS API rather than a Tauri command, mirror that. Confirm with:

```bash
grep -n "opener\|shell.open\|open_url" gui/src/App.tsx
```

Use whatever pattern is already in the file — don't introduce a second open-URL approach.

- [ ] **Step 5: Build**

```bash
cd gui && npm run build
```

Expected: success. Fix any leftover `news`/`NewsItem` references.

- [ ] **Step 6: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(gui): rotator shows youtube videos instead of RSS news"
```

---

### Task 19: Build, install, smoke for YouTube feed

- [ ] **Step 1: Verify config seeding logic**

If `~/.config/synthia/config.yaml` already has a `youtube:` key, temporarily move it aside to test seeding:

```bash
grep -q "^youtube:" ~/.config/synthia/config.yaml && echo "already seeded — skip remove" || echo "ready for seeding"
```

If "ready for seeding": leave as-is. Otherwise, skip the seeding verification step below.

- [ ] **Step 2: Build deb + install + relaunch**

```bash
cd gui && npm run tauri build -- --bundles deb
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/synthia-gui_*.deb
pkill -f synthia-gui || true
nohup /usr/bin/synthia-gui >/tmp/synthia-gui.log 2>&1 &
```

- [ ] **Step 3: Verify**
  - Status bar rotator shows `Channel Name` + video title.
  - Click → opens video in default browser.
  - `~/.config/synthia/config.yaml` now contains a `youtube:` block (run `grep -A5 youtube ~/.config/synthia/config.yaml`) seeded with morning-skill channels.
  - Edit a channel id to garbage → restart GUI → other channels still appear, garbage one silently skipped.
  - Check `/tmp/synthia-gui.log` for any panics/errors.

- [ ] **Step 4: If anything broken, fix and rebuild. Otherwise no commit (Phase 3 done).**

---

## Self-Review

Spec coverage:
- Tab rename: Task 1–7 (custom_titles map, sanitize, list_tabs override, frontend, popover, CSS, smoke). ✅
- Shortcuts panel both sections + search + alias copy: Task 8–14. ✅
- YouTube feed config schema, seeding, parallel fetch, atom parsing, cache, frontend rotator: Task 15–19. ✅
- Out-of-scope items (tab name persist across restart, config-panel CRUD, snippet shortcuts, thumbnail in rotator) intentionally omitted. ✅

Type consistency:
- `TabInfo { id, title, is_active }` used uniformly (matches existing struct in commands.rs:206-211).
- `AliasEntry { name, expansion }` used in both backend and ShortcutsPanel.tsx.
- `VideoItem { title, channel_name, video_url, thumbnail_url, published }` used in backend + App.tsx.
- `ChannelEntry { name, id }` only in backend, derived from yaml.

Placeholder scan: none found.

Quality gates referenced after each phase: `cargo build --release`, `cargo clippy --all-targets -- -D warnings`, `cargo test --lib`, `npm run build`.

---

## Final Commit Strategy

Phase 1 ends with no dangling commits — the smoke task is verification only.
Phase 2 same.
Phase 3 same.

Total commits: ~14 small, conventional-style. Branch is `feat/terminal-emulator`. Push when all three phases pass smoke.
