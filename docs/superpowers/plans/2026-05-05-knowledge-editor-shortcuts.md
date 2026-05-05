# Knowledge Editor Keyboard Shortcuts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire 9 keyboard shortcuts to the Synthia GUI knowledge note editor (Save, Close-with-autosave, Edit/Preview/Split, Pin, Copy-path, Delete, Rename) so users can operate the editor without the mouse.

**Architecture:** Single `useEffect` in `gui/src/App.tsx` scoped to `noteEditing && selectedNote && !editingNoteName`. Window-level `keydown` listener dispatches to existing handler functions. New `noteSavedContent` state tracks the last-persisted content so `Esc` can auto-save before closing if dirty.

**Tech Stack:** React 18 + TypeScript inside Tauri 2.x. Synthia is Linux-only (per CLAUDE.md), so only `e.ctrlKey` is checked.

**Spec:** `docs/superpowers/specs/2026-05-05-knowledge-editor-shortcuts-design.md`

---

## File Structure

**Modified files only — no new files.**

| File | Responsibility | Changes |
|---|---|---|
| `gui/src/App.tsx` | GUI shell, all section state, knowledge editor render | Add `noteSavedContent` state; set it in `handleOpenNote` and `handleSaveNote`; add `handleSmartClose`; add new `useEffect` keyboard handler; update 8 button `title` attrs |

Why one file: existing pattern. App.tsx already owns all knowledge state (`selectedNote`, `noteContent`, `noteEditing`, `editingNoteName`, `notePreview`, `pinnedNotes`) and all handler functions (`handleSaveNote`, `handleCloseNote`, `handleDeleteNote`, `togglePinNote`, `handleCopyPath`). Extracting a hook would require threading 7+ values + 5+ setters as args. Inline `useEffect` matches the existing scoped keyboard pattern at App.tsx:1292.

---

## Task 1: Add `noteSavedContent` state to track persisted content

**Files:**
- Modify: `gui/src/App.tsx:487-488` (state declarations near `selectedNote` / `noteContent`)
- Modify: `gui/src/App.tsx:1097-1108` (`handleOpenNote`)
- Modify: `gui/src/App.tsx:1110-1122` (`handleSaveNote`)

- [ ] **Step 1: Add state declaration**

In `App.tsx` immediately after the existing `noteContent` state (line ~488), add:

```typescript
const [noteSavedContent, setNoteSavedContent] = useState("");
```

- [ ] **Step 2: Set on note open**

In `handleOpenNote` (line ~1097), after `setNoteContent(content);`:

```typescript
async function handleOpenNote(path: string) {
  try {
    const content = await invoke<string>("read_note", { path });
    setSelectedNote(path);
    setNoteContent(content);
    setNoteSavedContent(content);  // NEW
    setNoteEditing(true);
    setNotePreview(null);
    trackRecentNote(path);
  } catch (e) {
    setError(String(e));
  }
}
```

- [ ] **Step 3: Set on save success**

In `handleSaveNote` (line ~1110), inside the `try` after the successful `invoke`:

```typescript
async function handleSaveNote() {
  if (!selectedNote) return;
  setNoteSaving(true);
  try {
    await invoke("save_note", { path: selectedNote, content: noteContent });
    setNoteSavedContent(noteContent);  // NEW
    setNoteSaving(false);
    setNoteSaved(true);
    setTimeout(() => setNoteSaved(false), 2000);
  } catch (e) {
    setError(String(e));
    setNoteSaving(false);
  }
}
```

- [ ] **Step 4: Verify build**

```bash
cd gui && npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(knowledge): track last-saved content for dirty detection"
```

---

## Task 2: Add `handleSmartClose` for auto-save-on-close

**Files:**
- Modify: `gui/src/App.tsx:1124-1132` (immediately after `handleCloseNote`)

- [ ] **Step 1: Add `handleSmartClose` function**

Add this function directly below the existing `handleCloseNote` (line ~1132):

```typescript
async function handleSmartClose() {
  if (!selectedNote) return;
  if (noteContent !== noteSavedContent) {
    await handleSaveNote();
  }
  handleCloseNote();
}
```

- [ ] **Step 2: Verify build**

```bash
cd gui && npm run build
```

Expected: build succeeds, no TypeScript errors.

- [ ] **Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(knowledge): add smart-close that auto-saves dirty notes"
```

---

## Task 3: Wire keyboard shortcuts via `useEffect`

**Files:**
- Modify: `gui/src/App.tsx` (add new `useEffect` block immediately below the existing context-menu `useEffect` at line ~1292)

- [ ] **Step 1: Add the keyboard `useEffect`**

Insert this `useEffect` block immediately after the closing `}, [contextMenu]);` on line ~1307:

```typescript
useEffect(() => {
  if (!noteEditing || !selectedNote) return;
  if (editingNoteName) return; // filename input owns its own keys

  const handleKeyDown = (e: KeyboardEvent) => {
    // Ignore modifier-only keypresses
    if (e.key === "Control" || e.key === "Shift" || e.key === "Alt" || e.key === "Meta") return;

    // Esc: auto-save if dirty, then close
    if (e.key === "Escape") {
      e.preventDefault();
      handleSmartClose();
      return;
    }

    if (!e.ctrlKey) return;

    // Ctrl+Shift combos first (more specific)
    if (e.shiftKey) {
      if (e.key === "P" || e.key === "p") {
        e.preventDefault();
        togglePinNote(selectedNote);
        return;
      }
      if (e.key === "C" || e.key === "c") {
        e.preventDefault();
        handleCopyPath(selectedNote);
        return;
      }
      return;
    }

    // Ctrl-only combos
    switch (e.key) {
      case "s":
      case "S":
        e.preventDefault();
        handleSaveNote();
        break;
      case "e":
      case "E":
        e.preventDefault();
        setNotePreview(false);
        break;
      case "p":
      case "P":
        e.preventDefault();
        setNotePreview(true);
        break;
      case "\\":
        e.preventDefault();
        setNotePreview(null);
        break;
      case "r":
      case "R":
        e.preventDefault();
        if (selectedNote) {
          const fileName = selectedNote.split("/").pop() || selectedNote;
          setNoteNameInput(fileName.replace(/\.md$/, ""));
          setEditingNoteName(true);
        }
        break;
      case "Delete":
        e.preventDefault();
        if (confirm("Delete this note?")) {
          handleDeleteNote(selectedNote);
        }
        break;
    }
  };

  window.addEventListener("keydown", handleKeyDown);
  return () => window.removeEventListener("keydown", handleKeyDown);
}, [
  noteEditing,
  selectedNote,
  editingNoteName,
  noteContent,
  noteSavedContent,
  pinnedNotes,
  notePreview,
]);
```

- [ ] **Step 2: Verify build**

```bash
cd gui && npm run build
```

Expected: build succeeds. No TypeScript errors. No ESLint warnings about missing dependencies (the dep array lists every captured value).

- [ ] **Step 3: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(knowledge): wire keyboard shortcuts in note editor"
```

---

## Task 4: Update button `title` attrs for discoverability

**Files:**
- Modify: `gui/src/App.tsx:3857-3927` (button block in `renderKnowledgeSection`)
- Modify: `gui/src/App.tsx:3876-3886` (filename clickable div)

- [ ] **Step 1: Update Back button title**

Find (line ~3857):
```tsx
<button className="back-btn" onClick={handleCloseNote}>
  ← Back
</button>
```

Replace with:
```tsx
<button className="back-btn" onClick={handleSmartClose} title="Close (Esc) — auto-saves changes">
  ← Back
</button>
```

Note: switches `onClick` to `handleSmartClose` so the button matches the shortcut behavior.

- [ ] **Step 2: Update filename rename hint**

Find (line ~3876):
```tsx
<div
  className="notes-filename"
  onClick={() => {
    setNoteNameInput(fileName.replace(/\.md$/, ""));
    setEditingNoteName(true);
  }}
  title="Click to rename"
>
```

Replace `title="Click to rename"` with `title="Click to rename (Ctrl+R)"`.

- [ ] **Step 3: Update Pin button title**

Find (line ~3888):
```tsx
<button
  className={`notes-pin-btn ${isPinned ? "active" : ""}`}
  onClick={() => togglePinNote(selectedNote)}
  title={isPinned ? "Unpin" : "Pin"}
>
```

Replace `title={isPinned ? "Unpin" : "Pin"}` with `title={`${isPinned ? "Unpin" : "Pin"} (Ctrl+Shift+P)`}`.

- [ ] **Step 4: Update Edit button**

Find (line ~3895):
```tsx
<button
  className={`notes-preview-btn ${notePreview === false ? "active" : ""}`}
  onClick={() => setNotePreview(notePreview === false ? null : false)}
>
  Edit
</button>
```

Add `title="Edit only (Ctrl+E)"` attribute on the button.

- [ ] **Step 5: Update Preview button**

Find (line ~3901):
```tsx
<button
  className={`notes-preview-btn ${notePreview === true ? "active" : ""}`}
  onClick={() => setNotePreview(notePreview === true ? null : true)}
>
  Preview
</button>
```

Add `title="Preview only (Ctrl+P) — Ctrl+\\ for split"` attribute.

- [ ] **Step 6: Update Copy Path button**

Find (line ~3907):
```tsx
<button
  className={`notes-copy-path-btn ${copiedPath ? "copied" : ""}`}
  onClick={() => handleCopyPath(selectedNote)}
  title="Copy file path"
>
```

Replace `title="Copy file path"` with `title="Copy file path (Ctrl+Shift+C)"`.

- [ ] **Step 7: Update Save button**

Find (line ~3914):
```tsx
<button
  className={`notes-save-btn ${noteSaving ? "saving" : ""} ${noteSaved ? "saved" : ""}`}
  onClick={handleSaveNote}
  disabled={noteSaving}
>
```

Add `title="Save (Ctrl+S)"` attribute.

- [ ] **Step 8: Update Delete button**

Find (line ~3921):
```tsx
<button
  className="notes-delete-btn"
  onClick={() => { if (confirm("Delete this note?")) handleDeleteNote(selectedNote); }}
>
```

Add `title="Delete (Ctrl+Delete)"` attribute.

- [ ] **Step 9: Verify build**

```bash
cd gui && npm run build
```

Expected: build succeeds, no errors.

- [ ] **Step 10: Commit**

```bash
git add gui/src/App.tsx
git commit -m "feat(knowledge): add shortcut hints to editor button tooltips"
```

---

## Task 5: Manual verification

**Files:** none (manual testing in dev build)

- [ ] **Step 1: Run dev build**

```bash
cd gui && npm run tauri dev
```

Wait for window to open.

- [ ] **Step 2: Open a note**

Navigate to Knowledge section. Click any note to open it.

- [ ] **Step 3: Test each shortcut**

Verify each:

| Shortcut | Expected behavior |
|---|---|
| `Ctrl+S` | Save button flashes "Saving..." → "Saved!". Page does not show browser save-as dialog. |
| `Ctrl+E` | Switches to edit-only view |
| `Ctrl+P` | Switches to preview-only view. Browser print dialog does NOT appear. |
| `Ctrl+\` | Switches to split view |
| `Ctrl+Shift+P` | Pin button toggles state |
| `Ctrl+Shift+C` | Copy Path button shows "Copied!" briefly |
| `Ctrl+R` | Filename becomes editable (renaming input focused). Browser does NOT reload. |
| `Ctrl+Delete` | Confirm dialog appears. Cancel returns to editor. |
| `Esc` (no edits) | Returns to dashboard immediately |
| `Esc` (after typing) | Save flashes briefly, then returns to dashboard. Re-open note — typed content is persisted. |

- [ ] **Step 4: Test rename mode bypass**

Click filename to enter rename mode. Press `Ctrl+S`, `Esc`, `Ctrl+E`, etc. — none should fire (filename input keeps focus and handles its own Enter/Escape per existing code at App.tsx:3866-3869).

- [ ] **Step 5: Test scope**

Press `Esc` from the Knowledge dashboard view (no note open) — nothing happens. Switch to another section (Agents, Voice, etc.) and press `Ctrl+S` — nothing happens.

- [ ] **Step 6: Commit verification notes**

If all checks pass, no commit needed. If any check fails, fix the relevant task code and re-test.

---

## Self-Review

**Spec coverage:**
- Shortcut map (9 shortcuts) → Task 3 implements all 9
- Auto-save on close → Tasks 1 + 2 add state and wrapper; Task 3 wires Esc
- Visual feedback (reuse `noteSaving`/`noteSaved`) → Task 1 leaves existing flash logic intact, Save handler still triggers it
- Discoverability (button title attrs) → Task 4 covers all 8 buttons + filename
- Edge cases (rename bypass, modifier-only keypress, confirm dialog) → Task 3 handles all three
- Linux-only `e.ctrlKey` (no `metaKey`) → Task 3 honors this
- Browser default suppression for Ctrl+S/P/R → Task 3 calls `e.preventDefault()` for each
- Manual testing checklist → Task 5

**Placeholder scan:** All steps include actual code. No "TBD", no "similar to", no "add error handling". `onClick={handleSmartClose}` substitution in Task 4 is intentional and explained.

**Type consistency:** `noteSavedContent` typed `string` in Task 1, used as string in Tasks 2 + 3. `handleSmartClose` declared `async` in Task 2, called as fire-and-forget from Task 3 (event handler — same pattern as existing `handleSaveNote` calls). Handler names match existing code: `handleSaveNote`, `handleCloseNote`, `handleDeleteNote`, `togglePinNote`, `handleCopyPath`, `setNotePreview`, `setNoteNameInput`, `setEditingNoteName`.
