# Knowledge Editor Keyboard Shortcuts — Design

**Date:** 2026-05-05
**Scope:** GUI knowledge section, note editor view only
**Files affected:** `gui/src/App.tsx` (additive)

## Problem

Knowledge editor has no keyboard shortcuts. Users must mouse-click Save, Back, Pin, Edit/Preview toggle, Copy Path, Delete buttons. Friction during note-taking.

## Goal

Wire keyboard shortcuts to existing button handlers when knowledge note editor is open. No shortcuts elsewhere in app.

## Non-goals

- App-wide section-switching shortcuts
- Dashboard-level shortcuts (e.g., new-note from dashboard)
- New library dependency
- Customizable bindings
- Help overlay / cheat sheet panel

## Architecture

Single `useEffect` hook in `App.tsx`, gated on `noteEditing && selectedNote && !editingNoteName`. Attaches `keydown` listener to `window`. Cleanup on unmount or gate change.

Pattern matches existing scoped keyboard handler at `App.tsx:1292` (context menu Esc dismissal).

## Shortcut Map

| Combo | Action | Existing handler |
|---|---|---|
| `Ctrl+S` | Save note | `handleSaveNote()` |
| `Esc` | Auto-save if dirty, then close | new `handleSmartClose()` wrapper |
| `Ctrl+E` | Edit-only view | `setNotePreview(false)` |
| `Ctrl+P` | Preview-only view | `setNotePreview(true)` |
| `Ctrl+\` | Split view | `setNotePreview(null)` |
| `Ctrl+Shift+P` | Toggle pin | `togglePinNote(selectedNote)` |
| `Ctrl+Shift+C` | Copy file path | `handleCopyPath(selectedNote)` |
| `Ctrl+Delete` | Delete (with confirm) | `confirm() + handleDeleteNote()` |
| `Ctrl+R` | Rename (focus filename input) | `setNoteNameInput(...)` + `setEditingNoteName(true)` |

Modifier handling: `e.ctrlKey` only — Synthia is Linux-only (per CLAUDE.md).

Browser default suppression: `e.preventDefault()` for `Ctrl+S`, `Ctrl+P`, `Ctrl+R` to block save-page / print / reload.

## Auto-save on Close

New state: `noteSavedContent: string` — tracks last persisted content.

- Set in `handleOpenNote()` after fetching content
- Set in `handleSaveNote()` after successful save
- `handleSmartClose()`: if `noteContent !== noteSavedContent`, await `handleSaveNote()` then call `handleCloseNote()`. Else close immediately.

## Edge Cases

| Case | Behavior |
|---|---|
| Rename mode active (`editingNoteName === true`) | Skip all shortcuts. Filename input owns Enter/Escape. |
| Modifier-only keypress (`key === "Control"` etc.) | Ignore. |
| Confirm dialog open (Delete) | Browser `confirm()` blocks event loop — no collision. |
| Section change mid-save | Cleanup removes listener; in-flight save completes via `noteSaving` state. |
| Esc with no unsaved changes | Close immediately (no save call). |
| Esc during save in progress | Save handler is idempotent; await completes; close. |

## Visual Feedback

Reuse existing `noteSaving` / `noteSaved` state — Save button already shows "Saving..." / "Saved!" transitions. Esc-triggered save uses same path, same UI flash.

## Discoverability

Update `title` attrs on existing buttons:

- Save → `Save (Ctrl+S)`
- Back → `Close (Esc)`
- Edit → `Edit only (Ctrl+E)`
- Preview → `Preview only (Ctrl+P)`
- Pin → `${isPinned ? "Unpin" : "Pin"} (Ctrl+Shift+P)`
- Copy Path → `Copy file path (Ctrl+Shift+C)`
- Delete → `Delete (Ctrl+Delete)`
- Filename (rename) → `Click to rename (Ctrl+R)`

No help panel.

## Testing

Manual verification only (existing handlers have no unit tests; pure wiring).

Checklist:
- Each shortcut fires correct action
- Browser defaults blocked (`Ctrl+S`, `Ctrl+P`, `Ctrl+R`)
- Rename mode bypasses all shortcuts
- Esc with dirty buffer auto-saves before closing
- Esc with clean buffer closes immediately
- Shortcuts inactive on dashboard view
- Shortcuts inactive after navigating to other section

## Implementation Notes

- Add new state `const [noteSavedContent, setNoteSavedContent] = useState("")`
- Set `noteSavedContent` after content load in `handleOpenNote`
- Set `noteSavedContent` after save success in `handleSaveNote`
- New `useEffect` block, dependency array: `[noteEditing, selectedNote, editingNoteName, noteContent, noteSavedContent, pinnedNotes, notePreview]`
- New `handleSmartClose` async function near existing `handleCloseNote`
- Update `title` props on 8 buttons in `renderKnowledgeSection()`

## Out of Scope (future)

- Tab/Shift+Tab indentation in textarea
- Markdown formatting shortcuts (Ctrl+B bold, etc.)
- Search shortcut (Ctrl+F) inside editor
- Cheat sheet overlay (`?` key)
