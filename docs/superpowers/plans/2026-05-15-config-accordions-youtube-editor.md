# Config Panel Accordions + YouTube Channel Editor

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]` for tracking.

**Goal:** Declutter the Config > Synthia tab by converting its four flat groups into collapsible accordions (multi-open, all collapsed by default), and add a new "YouTube Channels" accordion that lets the user add/remove channels feeding the status-bar rotator.

**Architecture:** Pure additive change. A reusable `<Accordion>` component wraps existing config-group markup. New backend commands `list_youtube_channels`, `add_youtube_channel`, `remove_youtube_channel` mutate `~/.config/synthia/config.yaml` via a new `write_youtube_channels` helper in `yaml_writer.rs` (replaces the entire `youtube.channels:` list block, preserves comments + other keys). Cache in `youtube_feed.rs` is invalidated after each write so the rotator picks up changes within ~30 seconds. URL handling: frontend regex extracts `UC...` id from `/channel/UCxxx` URLs OR accepts a bare `UC...` id — no HTTP scrape, no backend URL parsing.

**Tech Stack:** React 19, TypeScript, Rust, Tauri 2, parking_lot, serde_yaml.

**Branch:** `feat/terminal-emulator` (continues from previous plan).

---

## File Structure

### Created
- `gui/src/components/Accordion.tsx` — generic collapsible section component.
- `gui/src/components/Accordion.css` — styling.

### Modified
- `gui/src-tauri/src/yaml_writer.rs` — `write_youtube_channels(existing, channels) -> String` (replaces, not appends; preserves comments) + tests.
- `gui/src-tauri/src/commands/youtube_feed.rs` — `list_youtube_channels`, `add_youtube_channel`, `remove_youtube_channel` Tauri commands; `invalidate_cache` helper.
- `gui/src-tauri/src/lib.rs` — register three new commands in invoke_handler.
- `gui/src/App.tsx` — refactor synthia tab (sections become Accordions); add YouTube Channels accordion with name+URL inputs and channel list.
- `gui/src/App.css` — minor spacing adjustments to mesh with accordion borders.

### Deleted
None.

---

## Phase 1 — Backend (Rust)

### Task 1: `write_youtube_channels` yaml writer + tests

**File:** `gui/src-tauri/src/yaml_writer.rs`

- [ ] **Step 1: Add the writer above the `#[cfg(test)]` block**

```rust
/// Replace the `youtube.channels:` block in a Synthia config string with
/// the supplied channels. If `youtube:` doesn't exist, append a fresh
/// section (delegates to `append_youtube_channels`). Preserves all
/// comments and unrelated keys.
#[allow(dead_code)] // call site lands in Task 4
pub fn write_youtube_channels(existing: &str, channels: &[(String, String)]) -> String {
    // Find the top-level youtube: line.
    let mut lines: Vec<&str> = existing.lines().collect();
    let yt_idx = lines.iter().position(|line| {
        let is_top_level = !line.starts_with(|c: char| c.is_whitespace());
        is_top_level && line.trim_start().starts_with("youtube:")
    });

    let Some(yt_start) = yt_idx else {
        return append_youtube_channels(existing, channels);
    };

    // Find where the youtube block ends — first line at column 0 that isn't
    // a comment, blank, or a child of youtube:.
    let yt_end = lines[yt_start + 1..]
        .iter()
        .position(|line| {
            !line.is_empty()
                && !line.starts_with(|c: char| c.is_whitespace())
                && !line.trim_start().starts_with('#')
        })
        .map(|rel| yt_start + 1 + rel)
        .unwrap_or(lines.len());

    // Build the replacement block.
    let mut block: Vec<String> = vec!["youtube:".to_string(), "  channels:".to_string()];
    for (name, id) in channels {
        block.push(format!("    - name: \"{}\"", yaml_escape(name)));
        block.push(format!("      id: \"{}\"", yaml_escape(id)));
    }

    let mut out: Vec<String> = lines[..yt_start].iter().map(|s| s.to_string()).collect();
    out.extend(block);
    out.extend(lines[yt_end..].iter().map(|s| s.to_string()));

    let mut joined = out.join("\n");
    if existing.ends_with('\n') && !joined.ends_with('\n') {
        joined.push('\n');
    }
    joined
}
```

Note: `yaml_escape` and `append_youtube_channels` already exist in this file (added in the previous plan, Task 15) — reuse them. Drop the `#[allow(dead_code)]` from `yaml_escape` if it's still there (it's now used by both functions).

- [ ] **Step 2: Add tests inside the existing `mod tests`**

```rust
    #[test]
    fn write_youtube_channels_replaces_existing_list() {
        let existing = "stt_engine: cloud\nyoutube:\n  channels:\n    - name: \"Old\"\n      id: \"UC0\"\nother_key: value\n";
        let updated = write_youtube_channels(
            existing,
            &[("New".into(), "UC1".into()), ("Other".into(), "UC2".into())],
        );
        assert!(updated.contains("- name: \"New\""));
        assert!(updated.contains("id: \"UC2\""));
        assert!(!updated.contains("\"Old\""));
        assert!(updated.contains("stt_engine: cloud"));
        assert!(updated.contains("other_key: value"));
    }

    #[test]
    fn write_youtube_channels_appends_when_absent() {
        let existing = "stt_engine: cloud\n";
        let updated = write_youtube_channels(existing, &[("Cole".into(), "UC1".into())]);
        assert!(updated.contains("youtube:"));
        assert!(updated.contains("- name: \"Cole\""));
    }

    #[test]
    fn write_youtube_channels_handles_empty_list() {
        let existing = "youtube:\n  channels:\n    - name: \"Foo\"\n      id: \"UC0\"\n";
        let updated = write_youtube_channels(existing, &[]);
        assert!(updated.contains("youtube:"));
        assert!(updated.contains("channels:"));
        assert!(!updated.contains("UC0"));
    }
```

- [ ] **Step 3: Run tests + clippy**

```bash
cd gui/src-tauri && cargo test --lib yaml_writer::tests::write_youtube_channels 2>&1 | tail -10
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -10
```

Expected: 3 passed, zero clippy warnings.

- [ ] **Step 4: Commit**

```bash
git -C $WORKTREE add gui/src-tauri/src/yaml_writer.rs
git -C $WORKTREE commit -m "feat(gui): write_youtube_channels yaml replacer with tests"
```

---

### Task 2: youtube_feed.rs CRUD commands + cache invalidation

**File:** `gui/src-tauri/src/commands/youtube_feed.rs`

- [ ] **Step 1: Make the channel id regex available**

Add to the top of the file:

```rust
fn config_path() -> std::path::PathBuf {
    synthia_config_path()
}
```

(Just reuses the existing private `synthia_config_path` so test code can override later if desired. Optional — skip if you prefer the existing path helper.)

- [ ] **Step 2: Add `list_youtube_channels` command**

```rust
#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task 3)
pub async fn list_youtube_channels() -> Vec<ChannelEntry> {
    read_channels_from_yaml(&synthia_config_path())
}
```

- [ ] **Step 3: Add `add_youtube_channel` and `remove_youtube_channel`**

```rust
fn invalidate_cache() {
    if let Ok(mut guard) = CACHE.lock() {
        *guard = None;
    }
}

fn rewrite_channels(channels: &[ChannelEntry]) -> Result<(), String> {
    let path = synthia_config_path();
    let existing = std::fs::read_to_string(&path).unwrap_or_default();
    let pairs: Vec<(String, String)> = channels
        .iter()
        .map(|c| (c.name.clone(), c.id.clone()))
        .collect();
    let updated = crate::yaml_writer::write_youtube_channels(&existing, &pairs);
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    std::fs::write(&path, updated).map_err(|e| e.to_string())?;
    invalidate_cache();
    Ok(())
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task 3)
pub async fn add_youtube_channel(name: String, id: String) -> Result<Vec<ChannelEntry>, String> {
    let name = name.trim().to_string();
    let id = id.trim().to_string();
    if name.is_empty() {
        return Err("name cannot be empty".into());
    }
    if !id.starts_with("UC") || id.len() < 20 {
        return Err("id must be a YouTube channel id starting with UC".into());
    }
    let mut current = read_channels_from_yaml(&synthia_config_path());
    if current.iter().any(|c| c.id == id) {
        return Err("channel already in list".into());
    }
    current.push(ChannelEntry { name, id });
    rewrite_channels(&current)?;
    Ok(current)
}

#[tauri::command]
#[allow(dead_code)] // registered in lib.rs (Task 3)
pub async fn remove_youtube_channel(id: String) -> Result<Vec<ChannelEntry>, String> {
    let mut current = read_channels_from_yaml(&synthia_config_path());
    let before = current.len();
    current.retain(|c| c.id != id);
    if current.len() == before {
        return Err("channel id not found".into());
    }
    rewrite_channels(&current)?;
    Ok(current)
}
```

Note: `ChannelEntry` derives `Deserialize` only — add `Serialize` to the derive list so it can be returned to the frontend:

```rust
#[derive(Serialize, Deserialize, Debug, Clone)]
pub struct ChannelEntry {
    pub name: String,
    pub id: String,
}
```

- [ ] **Step 4: Build + clippy + tests**

```bash
cd gui/src-tauri && cargo build --release 2>&1 | tail -5
cd gui/src-tauri && cargo clippy --all-targets -- -D warnings 2>&1 | tail -10
cd gui/src-tauri && cargo test --lib commands::youtube_feed::tests 2>&1 | tail -10
```

Expected: build success, zero warnings, 3 existing tests still pass.

- [ ] **Step 5: Commit**

```bash
git -C $WORKTREE add gui/src-tauri/src/commands/youtube_feed.rs
git -C $WORKTREE commit -m "feat(gui): list/add/remove youtube channel commands"
```

---

### Task 3: Register the three new commands in lib.rs

**File:** `gui/src-tauri/src/lib.rs`

- [ ] **Step 1: Add to invoke_handler immediately after `commands::youtube_feed::get_youtube_videos`**

```rust
            commands::youtube_feed::get_youtube_videos,
            commands::youtube_feed::list_youtube_channels,
            commands::youtube_feed::add_youtube_channel,
            commands::youtube_feed::remove_youtube_channel,
```

- [ ] **Step 2: Build + commit**

```bash
cd gui/src-tauri && cargo build --release 2>&1 | tail -5
git -C $WORKTREE add gui/src-tauri/src/lib.rs
git -C $WORKTREE commit -m "feat(gui): register youtube channel CRUD commands"
```

---

## Phase 2 — Frontend (React)

### Task 4: Generic Accordion component + CSS

**Files:**
- Create: `gui/src/components/Accordion.tsx`
- Create: `gui/src/components/Accordion.css`

- [ ] **Step 1: Create Accordion.tsx**

```tsx
import { useState, type ReactNode } from "react";
import "./Accordion.css";

type AccordionProps = {
  title: string;
  defaultOpen?: boolean;
  badge?: string;
  children: ReactNode;
};

export function Accordion({ title, defaultOpen = false, badge, children }: AccordionProps) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className={`accordion${open ? " open" : ""}`}>
      <button
        type="button"
        className="accordion-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="accordion-chevron">{open ? "▾" : "▸"}</span>
        <span className="accordion-title">{title}</span>
        {badge && <span className="accordion-badge">{badge}</span>}
      </button>
      {open && <div className="accordion-body">{children}</div>}
    </div>
  );
}
```

- [ ] **Step 2: Create Accordion.css**

```css
.accordion {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  margin-bottom: 10px;
  overflow: hidden;
}

.accordion-header {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  background: transparent;
  border: none;
  color: rgba(226, 232, 240, 0.85);
  font: inherit;
  font-size: 13px;
  padding: 12px 16px;
  cursor: pointer;
  text-align: left;
}

.accordion-header:hover {
  background: rgba(255, 255, 255, 0.03);
  color: #e2e8f0;
}

.accordion.open .accordion-header {
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.accordion-chevron {
  color: rgba(34, 211, 238, 0.85);
  font-size: 11px;
  width: 12px;
  display: inline-block;
}

.accordion-title {
  flex: 1;
  font-weight: 500;
}

.accordion-badge {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.40);
  background: rgba(34, 211, 238, 0.10);
  padding: 2px 8px;
  border-radius: 999px;
}

.accordion-body {
  padding: 14px 16px 18px;
}
```

- [ ] **Step 3: Build typecheck**

```bash
cd gui && npm run build 2>&1 | tail -5
```

- [ ] **Step 4: Commit**

```bash
git -C $WORKTREE add gui/src/components/Accordion.tsx gui/src/components/Accordion.css
git -C $WORKTREE commit -m "feat(gui): generic Accordion component"
```

---

### Task 5: Refactor synthia config tab to use accordions

**File:** `gui/src/App.tsx`

- [ ] **Step 1: Add Accordion import**

Near the other component imports:

```tsx
import { Accordion } from "./components/Accordion";
```

- [ ] **Step 2: Wrap each existing config-group in an Accordion**

Inside `{configTab === "synthia" && (` (the synthia tab render), replace each `<div className="config-group">…</div>` with:

```tsx
<Accordion title="Processing Mode">
  <div className="config-toggle-row">…STT toggle…</div>
  <div className="config-toggle-row">…LLM toggle…</div>
  <div className="config-toggle-row">…TTS toggle…</div>
</Accordion>

<Accordion title="Models">
  …existing field markup…
</Accordion>

<Accordion title="Other Settings">
  …existing field markup…
</Accordion>
```

The `config-group-title` divs go away (the Accordion title replaces them). Inner `config-field`/`config-toggle-row` markup stays unchanged.

The "Save Settings" button stays where it is — outside the accordions, at the end of the synthiaConfig block.

- [ ] **Step 3: Move Worktree Repositories into its own Accordion**

The current `<div className="config-panel"><div className="config-panel-title">Worktree Repositories</div>…</div>` (the second sibling panel) becomes:

```tsx
<Accordion title="Worktree Repositories" badge={`${worktreeRepos.length}`}>
  <p className="config-description">
    Git repositories to scan for worktrees in the Worktrees tab.
  </p>
  <div className="config-repo-add">…input + Add button…</div>
  <div className="config-repo-list">…list with × buttons…</div>
</Accordion>
```

Drop the surrounding `<div className="config-panel">` since the Accordion now provides the framing. Also drop `<div className="config-panel-title">…</div>`.

If the layout was previously a horizontal `config-layout` flex with two side-by-side panels, change it to a single column container — accordions stack vertically.

- [ ] **Step 4: Build typecheck**

```bash
cd gui && npm run build 2>&1 | tail -5
```

Expected: success.

- [ ] **Step 5: Commit**

```bash
git -C $WORKTREE add gui/src/App.tsx
git -C $WORKTREE commit -m "refactor(gui): config synthia tab uses accordions"
```

---

### Task 6: Add YouTube Channels accordion + CRUD UI

**File:** `gui/src/App.tsx`

- [ ] **Step 1: Add state + load effect**

Near other config state:

```tsx
const [youtubeChannels, setYoutubeChannels] = useState<{ name: string; id: string }[]>([]);
const [newChannelName, setNewChannelName] = useState("");
const [newChannelUrl, setNewChannelUrl] = useState("");
const [channelError, setChannelError] = useState<string | null>(null);
```

Inside the `if (currentSection === "config")` effect (line ~604), add:

```tsx
invoke<{ name: string; id: string }[]>("list_youtube_channels")
  .then(setYoutubeChannels)
  .catch(() => setYoutubeChannels([]));
```

- [ ] **Step 2: Add helper to extract channel id**

Above `renderConfigSection`:

```tsx
function extractChannelId(input: string): string | null {
  const trimmed = input.trim();
  // Plain id: UC followed by 20+ url-safe chars
  if (/^UC[\w-]{20,}$/.test(trimmed)) return trimmed;
  // /channel/UCxxx URL form
  const match = trimmed.match(/\/channel\/(UC[\w-]{20,})/);
  return match ? match[1] : null;
}
```

- [ ] **Step 3: Add the YouTube Channels accordion to synthia tab**

Inside the synthia tab JSX, after the "Other Settings" accordion (and after Worktree Repositories — pick whichever order reads better):

```tsx
<Accordion title="YouTube Channels" badge={`${youtubeChannels.length}`}>
  <p className="config-description">
    Channels feeding the status-bar video rotator. Paste a channel URL like{" "}
    <code>youtube.com/channel/UCxxx</code> or just the <code>UC…</code> id.
  </p>

  <div className="config-channel-add">
    <input
      type="text"
      placeholder="Channel name (e.g. Cole Medin)"
      value={newChannelName}
      onChange={(e) => setNewChannelName(e.target.value)}
    />
    <input
      type="text"
      placeholder="Channel URL or UC… id"
      value={newChannelUrl}
      onChange={(e) => setNewChannelUrl(e.target.value)}
    />
    <button
      type="button"
      onClick={async () => {
        setChannelError(null);
        const id = extractChannelId(newChannelUrl);
        if (!id) {
          setChannelError("Could not find a UC… id in that URL.");
          return;
        }
        try {
          const updated = await invoke<{ name: string; id: string }[]>("add_youtube_channel", {
            name: newChannelName.trim(),
            id,
          });
          setYoutubeChannels(updated);
          setNewChannelName("");
          setNewChannelUrl("");
        } catch (err) {
          setChannelError(String(err));
        }
      }}
    >
      Add
    </button>
  </div>
  {channelError && <div className="config-channel-error">{channelError}</div>}

  <div className="config-channel-list">
    {youtubeChannels.length === 0 ? (
      <div className="config-channel-empty">No channels configured.</div>
    ) : (
      youtubeChannels.map((c) => (
        <div key={c.id} className="config-channel-item">
          <span className="config-channel-name">{c.name}</span>
          <span className="config-channel-id">{c.id}</span>
          <button
            type="button"
            className="config-channel-remove"
            title="Remove channel"
            onClick={async () => {
              try {
                const updated = await invoke<{ name: string; id: string }[]>(
                  "remove_youtube_channel",
                  { id: c.id },
                );
                setYoutubeChannels(updated);
              } catch (err) {
                console.error("remove channel failed", err);
              }
            }}
          >
            ×
          </button>
        </div>
      ))
    )}
  </div>
</Accordion>
```

- [ ] **Step 4: Build typecheck**

```bash
cd gui && npm run build 2>&1 | tail -5
```

Expected: success.

- [ ] **Step 5: Commit**

```bash
git -C $WORKTREE add gui/src/App.tsx
git -C $WORKTREE commit -m "feat(gui): YouTube channels CRUD accordion in config"
```

---

### Task 7: CSS for channel CRUD UI

**File:** `gui/src/App.css`

- [ ] **Step 1: Append styles**

```css
.config-channel-add {
  display: grid;
  grid-template-columns: 1fr 1.5fr auto;
  gap: 8px;
  margin: 8px 0 12px;
}

.config-channel-add input {
  background: rgba(255, 255, 255, 0.04);
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 4px;
  color: #e2e8f0;
  padding: 6px 10px;
  font: inherit;
}

.config-channel-add input:focus {
  border-color: #22d3ee;
  outline: none;
}

.config-channel-add button {
  background: #22d3ee;
  color: #11151c;
  border: none;
  border-radius: 4px;
  padding: 6px 14px;
  font: inherit;
  font-weight: 500;
  cursor: pointer;
}

.config-channel-add button:hover {
  background: #67e8f9;
}

.config-channel-error {
  color: #f87171;
  font-size: 12px;
  margin-bottom: 8px;
}

.config-channel-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-channel-item {
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 12px;
  padding: 8px 10px;
  background: rgba(255, 255, 255, 0.02);
  border-radius: 4px;
  align-items: center;
}

.config-channel-name {
  color: rgba(226, 232, 240, 0.85);
}

.config-channel-id {
  font-family: ui-monospace, "JetBrains Mono", monospace;
  color: rgba(255, 255, 255, 0.40);
  font-size: 11px;
}

.config-channel-remove {
  background: transparent;
  border: none;
  color: rgba(255, 255, 255, 0.40);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 4px;
}

.config-channel-remove:hover {
  color: #f87171;
}

.config-channel-empty {
  color: rgba(255, 255, 255, 0.30);
  font-style: italic;
  padding: 8px 10px;
}
```

- [ ] **Step 2: Commit**

```bash
git -C $WORKTREE add gui/src/App.css
git -C $WORKTREE commit -m "style(gui): channel CRUD layout"
```

---

### Task 8: Build deb + install + manual smoke

- [ ] **Step 1: Build**

```bash
cd gui && npm run tauri build -- --bundles deb 2>&1 | tail -10
```

- [ ] **Step 2: Install + relaunch**

```bash
sudo dpkg -i gui/src-tauri/target/release/bundle/deb/Synthia_0.1.0_amd64.deb
pkill -f synthia-gui ; nohup /usr/bin/synthia-gui >/tmp/synthia-gui.log 2>&1 & disown
```

- [ ] **Step 3: Verify**
  - Open Config → Synthia tab.
  - All four prior groups render as collapsed accordions.
  - Click Processing Mode → expands.
  - YouTube Channels accordion renders with seeded channels (~7).
  - Add channel: paste `https://www.youtube.com/channel/UCabcdef…` → Add → row appears.
  - Bad URL → red error message.
  - Remove × → row disappears, `~/.config/synthia/config.yaml` updated.
  - Within ~30s the status-bar rotator reflects the new channel set (cache invalidates on write).

- [ ] **Step 4: Fix anything broken; otherwise no commit (smoke is verification only).**

---

## Self-Review

- All four sections accordion-ised: Processing Mode, Models, Other Settings, Worktree Repositories. ✅
- New YouTube Channels accordion with name + URL/id input, list, remove. ✅
- Multi-open accordion behaviour, all collapsed by default — `defaultOpen={false}` is the default. ✅
- URL handling client-side: regex extracts `UC…` from `/channel/…` URL or accepts bare id. ✅
- Backend writes preserve comments via surgical `write_youtube_channels`. ✅
- Cache invalidated on every add/remove → rotator picks up changes on next 30-min cycle (or immediately on next manual refresh). ✅
- No HTTP scrape required (URL form is self-describing). ✅

## Out of scope (deferred to v3)

- `/@handle` URL support (requires HTTP fetch + scrape).
- Channel name auto-fetch from URL (requires HTTP fetch).
- Drag-to-reorder channel list.
- Per-channel filters (max video age, keyword filter).
- Bulk import from clipboard / file.

---

## Final Commit Strategy

8 commits total, all on `feat/terminal-emulator`:
1. `feat(gui): write_youtube_channels yaml replacer with tests`
2. `feat(gui): list/add/remove youtube channel commands`
3. `feat(gui): register youtube channel CRUD commands`
4. `feat(gui): generic Accordion component`
5. `refactor(gui): config synthia tab uses accordions`
6. `feat(gui): YouTube channels CRUD accordion in config`
7. `style(gui): channel CRUD layout`
8. (no commit; smoke verification)
