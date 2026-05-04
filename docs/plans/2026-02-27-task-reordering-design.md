# Task Reordering Design

**Date:** 2026-02-27
**Status:** Approved

## Problem

Tasks in the kanban board appear in creation order with no way to reorder them. Users want to drag high-priority tasks to the top of a column.

## Approach: Sort-order field

Add a numeric `sort_order: f64` field to each task. Drag-and-drop within a column calculates a new sort_order using the midpoint between neighboring tasks.

## Data Model Change

Add to both Rust struct and TypeScript interface:

- `sort_order: f64` — determines display order within a column (ascending)

## Backend Changes (lib.rs)

### Migration
- On load, if any task is missing `sort_order`, assign sequential values (1000, 2000, 3000...) preserving current array order.

### New command
- `reorder_task(id: String, sort_order: f64)` — updates a single task's sort_order and saves to disk.

### Modified behavior
- `list_tasks` returns tasks sorted by `sort_order` ascending.
- `add_task` assigns `sort_order` = current timestamp in ms (float), so new tasks appear at the bottom.

## Frontend Changes (App.tsx)

### Within-column drag-and-drop
- Extend existing HTML5 drag-and-drop to detect drops within the same column (not just cross-column moves).
- On drop, calculate new `sort_order`:
  - Top of column: `first_task.sort_order - 1000`
  - Bottom of column: `last_task.sort_order + 1000`
  - Between two tasks: `(above.sort_order + below.sort_order) / 2`
- Call `reorder_task` Tauri command with the new value.

### Visual feedback
- Show a drop indicator (horizontal line/gap) between cards during drag.

### Column rendering
- Sort filtered tasks by `sort_order` before rendering each column.

## What stays the same
- Cross-column drag (status change via `move_task`) — sort_order preserved
- All existing CRUD operations
- JSON file format (just gains the extra field)
