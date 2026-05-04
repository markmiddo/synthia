# Copy File Path Feature Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users copy a note's absolute file path from a right-click context menu (anywhere notes appear) and from a copy button in the note editor header.

**Architecture:** Add a lightweight custom context menu component (positioned at cursor, dismissed on click-away/Escape). Expose the existing `get_notes_base_path()` Rust function as a Tauri command so the frontend can resolve absolute paths. Use `navigator.clipboard.writeText()` (already used elsewhere in the app) for clipboard access.

**Tech Stack:** React (inline in App.tsx), Tauri commands (Rust), CSS, `navigator.clipboard`

---

### Task 1: Expose notes base path as Tauri command

**Files:**
- Modify: `gui/src-tauri/src/lib.rs:2408-2415` (add `#[tauri::command]` annotation)
- Modify: `gui/src-tauri/src/lib.rs` (register command in `.invoke_handler()`)

**Step 1: Add `#[tauri::command]` to `get_notes_base_path`**

The function already exists but is private. Change it to return a `String` and add the Tauri attribute:

```rust
#[tauri::command]
fn get_notes_base_path_cmd() -> String {
    get_notes_base_path().to_string_lossy().to_string()
}
```

Add this as a new function right after the existing `get_notes_base_path()` (line ~2415). Don't modify the existing function since other Rust code calls it returning `PathBuf`.

**Step 2: Register the command**

Find the `.invoke_handler(tauri::generate_handler![...])` call and add `get_notes_base_path_cmd` to the list.

**Step 3: Build and verify**

Run: `cd gui/src-tauri && cargo check`
Expected: Compiles with no errors.

**Step 4: Commit**

```
feat(gui): expose notes base path as Tauri command
```

---

### Task 2: Load base path in frontend and add copy helper

**Files:**
- Modify: `gui/src/App.tsx` (state, useEffect, helper function)

**Step 1: Add state for base path**

Near the other notes state variables (around line 340-370), add:

```typescript
const [notesBasePath, setNotesBasePath] = useState("");
```

**Step 2: Load base path on mount**

In the existing `useEffect` that runs on mount (or in the notes loading logic), add:

```typescript
invoke<string>("get_notes_base_path_cmd").then(setNotesBasePath).catch(() => {});
```

**Step 3: Add copy path helper function**

Near the other note handler functions, add:

```typescript
async function copyNotePath(relativePath: string) {
  const fullPath = notesBasePath
    ? `${notesBasePath}/${relativePath}`
    : relativePath;
  try {
    await navigator.clipboard.writeText(fullPath);
  } catch {
    // Fallback: some environments block clipboard API
  }
}
```

**Step 4: Verify it compiles**

Run: `cd gui && npm run build`
Expected: Builds with no errors.

**Step 5: Commit**

```
feat(gui): add notes base path state and copy path helper
```

---

### Task 3: Add context menu component and state

**Files:**
- Modify: `gui/src/App.tsx` (context menu state, component, dismiss logic)
- Modify: `gui/src/App.css` (context menu styles)

**Step 1: Add context menu state**

Near the notes state:

```typescript
const [contextMenu, setContextMenu] = useState<{
  x: number;
  y: number;
  notePath: string;
} | null>(null);
```

**Step 2: Add context menu open handler**

```typescript
function handleNoteContextMenu(e: React.MouseEvent, notePath: string) {
  e.preventDefault();
  setContextMenu({ x: e.clientX, y: e.clientY, notePath });
}
```

**Step 3: Add context menu dismiss**

```typescript
// Add click-away listener
useEffect(() => {
  if (!contextMenu) return;
  const dismiss = () => setContextMenu(null);
  document.addEventListener("click", dismiss);
  document.addEventListener("contextmenu", dismiss);
  return () => {
    document.removeEventListener("click", dismiss);
    document.removeEventListener("contextmenu", dismiss);
  };
}, [contextMenu]);
```

**Step 4: Add "Copied!" feedback state**

```typescript
const [copiedPath, setCopiedPath] = useState(false);
```

**Step 5: Add copy handler with feedback**

```typescript
async function handleCopyPath(relativePath: string) {
  await copyNotePath(relativePath);
  setCopiedPath(true);
  setTimeout(() => setCopiedPath(false), 1500);
}
```

**Step 6: Render context menu in renderKnowledgeSection**

At the top of `renderKnowledgeSection()`, before any return, add this JSX that will be included in both the editor and dashboard returns. Actually — render it at the very end of the function's JSX, as a portal-like overlay. Add it just before the closing `</div>` of both the editor view and dashboard view:

```tsx
{contextMenu && (
  <div
    className="note-context-menu"
    style={{ top: contextMenu.y, left: contextMenu.x }}
    onClick={(e) => e.stopPropagation()}
  >
    <button
      className="note-context-menu-item"
      onClick={() => {
        handleCopyPath(contextMenu.notePath);
        setContextMenu(null);
      }}
    >
      Copy file path
    </button>
  </div>
)}
```

**Step 7: Add CSS styles**

In `App.css`, add:

```css
.note-context-menu {
  position: fixed;
  z-index: 1000;
  background: #1e1e2e;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 4px 0;
  min-width: 160px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
}

.note-context-menu-item {
  display: block;
  width: 100%;
  padding: 8px 14px;
  background: none;
  border: none;
  color: #cdd6f4;
  font-size: 0.85em;
  text-align: left;
  cursor: pointer;
}

.note-context-menu-item:hover {
  background: rgba(137, 180, 250, 0.15);
}
```

**Step 8: Commit**

```
feat(gui): add context menu component for notes
```

---

### Task 4: Wire up right-click to all note items

**Files:**
- Modify: `gui/src/App.tsx` (add `onContextMenu` to all note clickable elements)

**Step 1: Folder tree file items**

In `renderFolderTree()`, on the file `<button>` (around line 3388):

```tsx
<button
  key={file.path}
  className="knowledge-tree-item knowledge-tree-file"
  style={{ paddingLeft: `${28 + depth * 16}px` }}
  onClick={() => handleOpenNote(file.path)}
  onContextMenu={(e) => handleNoteContextMenu(e, file.path)}
>
```

**Step 2: Pinned cards**

On the pinned card `<button>` (around line 3611):

```tsx
<button
  key={path}
  className="knowledge-card"
  onClick={() => handleOpenNote(path)}
  onContextMenu={(e) => handleNoteContextMenu(e, path)}
>
```

**Step 3: Recent notes items**

On the recent note `<button>` (around line 3637):

```tsx
<button
  key={path}
  className="knowledge-recent-item"
  onClick={() => handleOpenNote(path)}
  onContextMenu={(e) => handleNoteContextMenu(e, path)}
>
```

**Step 4: Search result items**

On the search result `<button>` (around line 3588):

```tsx
<button
  key={entry.path}
  className="knowledge-search-result-item"
  onClick={() => handleOpenNote(entry.path)}
  onContextMenu={(e) => handleNoteContextMenu(e, entry.path)}
>
```

**Step 5: Commit**

```
feat(gui): wire right-click context menu to all note items
```

---

### Task 5: Add copy button to editor header

**Files:**
- Modify: `gui/src/App.tsx` (editor header buttons)
- Modify: `gui/src/App.css` (copy button styles)

**Step 1: Add copy button in editor header**

In `renderKnowledgeSection()`, inside the editor header `<div className="notes-header-actions">`, add a copy button after the Preview button and before Save (around line 3458):

```tsx
<button
  className={`notes-copy-path-btn ${copiedPath ? "copied" : ""}`}
  onClick={() => handleCopyPath(selectedNote)}
  title="Copy file path"
>
  {copiedPath ? "Copied!" : "Copy Path"}
</button>
```

**Step 2: Add CSS**

```css
.notes-copy-path-btn {
  padding: 4px 10px;
  background: rgba(137, 180, 250, 0.1);
  border: 1px solid rgba(137, 180, 250, 0.2);
  border-radius: 4px;
  color: #89b4fa;
  font-size: 0.8em;
  cursor: pointer;
  transition: all 0.2s;
}

.notes-copy-path-btn:hover {
  background: rgba(137, 180, 250, 0.2);
}

.notes-copy-path-btn.copied {
  color: #a6e3a1;
  border-color: rgba(166, 227, 161, 0.3);
}
```

**Step 3: Commit**

```
feat(gui): add copy path button to note editor header
```

---

### Task 6: Build, install, and verify

**Step 1: Build the deb package**

Run: `cd gui && npm run tauri build`

**Step 2: Install**

Run: `sudo dpkg -i gui/src-tauri/target/release/bundle/deb/Synthia_0.1.0_amd64.deb`

**Step 3: Restart and test**

Run: `pkill -f synthia-gui && sleep 1 && nohup synthia-gui &>/dev/null &`

Test:
- Right-click a note in the sidebar tree → "Copy file path" appears → click it → paste elsewhere to verify absolute path
- Right-click a pinned card → same
- Right-click a recent note → same
- Right-click a search result → same
- Open a note → "Copy Path" button visible between Preview and Save → click → shows "Copied!"

**Step 4: Final commit**

```
feat(gui): implement copy file path for notes
```
