# Knowledge Section Redesign — "Second Brain Dashboard"

**Date:** 2026-02-26
**Status:** Approved

## Problem

The current knowledge section is visually overwhelming. Three vertically stacked sections (pinned chips, recent list, full-width folder browser) compete for attention. It reads more like a file manager than a second brain. Pinned notes are tiny chips with no context. The folder browser takes up excessive vertical space with full-width rows.

## Design

### Layout: Two-Column Split

```
┌─────────────────────────────────────────────────────────────┐
│  🔍 Search notes...                                    [+] │
├──────────────────────┬──────────────────────────────────────┤
│  FOLDERS (tree)      │  PINNED (cards)                      │
│  35% width           │  65% width                           │
│  scrollable          │                                      │
│                      │  RECENT (compact list)               │
└──────────────────────┴──────────────────────────────────────┘
```

- **Search bar** spans full width at top — primary action gets prime real estate
- **"+ New" button** in the search bar row, always accessible
- **Left column (35%)** — Compact collapsible tree view of folders
- **Right column (65%)** — Pinned cards grid + recent notes list

### Left Column: Folder Tree

- Folders collapsed by default with triangle toggles (▸/▾)
- Clicking a folder expands it inline — no page navigation
- 16px indentation per nesting level
- Folders: yellow-tinted text, Files: cyan-tinted text
- Own scroll area so it doesn't push content down
- Expanded/collapsed state persisted in knowledge-meta.json
- Clicking a file opens it in the editor (same as current behavior)

### Right Column: Pinned Cards

- 2-column responsive grid (drops to 1 column when narrow)
- Each card contains:
  - **Title** — bold, white, single line with ellipsis
  - **Preview** — first 2-3 lines of note content, muted gray, line-clamp
  - **Timestamp** — relative format ("2h ago", "yesterday") at bottom
- Card styling:
  - Background: `rgba(10, 11, 20, 0.6)` with subtle border
  - Left border: 3px purple accent (`rgba(168, 85, 247, 0.6)`)
  - Hover: brightness lift + subtle border glow
  - Border radius: 8px
- Clicking a card opens the note in the editor

### Right Column: Recent Notes

- Below pinned cards, section header "RECENT"
- Compact rows: note name (left) + relative timestamp (right)
- No icons — section header provides context
- Subtle divider lines between items
- Max 6 items (same as current)

### Search Behavior

- When typing, right column switches from pinned/recent to search results
- Results as flat list with folder breadcrumbs in muted text
- Clear search returns to pinned/recent view
- Tree stays visible during search

### Data Model Changes

Extend `KnowledgeMeta` to include:
- `expanded_folders: string[]` — which folders are expanded in tree
- No other data model changes needed

### Backend Changes

Add new Tauri command:
- `get_note_preview(path: String) -> String` — returns first ~200 chars of a note for card preview
- `get_note_modified(path: String) -> u64` — returns last modified timestamp

Alternatively, extend `NoteEntry` to include `preview` and `modified` fields in `list_notes` responses.

## User Research

- Primary use case: finding a specific note quickly
- Typically 3-5 pinned notes (small curated set)
- Preferred tree view for folder browsing over full-width rows
- Wants "second brain" feel — at-a-glance context, not just filenames

## Out of Scope

- Full-text search (current filename search is sufficient for now)
- Tags or categories system
- Note linking / backlinks
- Drag-and-drop in tree view (keep existing drag-drop on browse items)
