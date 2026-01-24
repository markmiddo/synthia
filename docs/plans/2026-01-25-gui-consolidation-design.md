# Synthia GUI Consolidation Design

## Overview

Consolidate the TUI dashboard and GUI into a single Tauri application. The TUI will be deprecated. The GUI becomes the unified interface for voice assistant control and Claude Code worktree management.

## Goals

- Single interface to maintain instead of two
- Flexible window that can be positioned anywhere across dual monitors
- Fix task detection (migrate from old todos system to new tasks system)
- Clean, dark aesthetic matching the existing GUI style

## Navigation Structure

Grouped sidebar navigation with 4 top-level items:

```
Worktrees (default)
Voice
Memory
Config
  ├── Agents
  ├── Commands
  ├── Plugins
  ├── Hooks
  └── Settings
```

## Section Details

### Worktrees (Primary View)

The main view for daily coding work.

**Worktree List Panel:**
- All worktrees from configured repos (`~/.config/synthia/worktrees.yaml`)
- Each entry shows: branch name, issue number, task progress bar
- Color coding: green (completed tasks), orange (in-progress), grey (no tasks)
- Click to select, details appear in side panel

**Task Detail Panel:**
- Task list with status indicators
- Dependencies shown visually (blocked tasks greyed out with "blocked by #X")
- Progress summary: "3/7 completed" with visual progress bar

**Actions:**
- Resume Claude session in WezTerm
- View on GitHub
- Refresh

### Voice

Existing voice assistant controls, reorganized as a section:

**Included:**
- Start/Stop Synthia toggle
- Remote mode (Telegram) toggle
- Hotkey display and configuration
- Voice history
- Word dictionary

**Disabled for now (not working):**
- Clipboard history
- Phone inbox

### Memory

Claude Code knowledge management:
- Bugs, patterns, gotchas, stack knowledge
- Add/edit/delete entries
- Search/filter

### Config

Setup-once features grouped together:
- **Agents** - manage agent configurations
- **Commands** - slash command management
- **Plugins** - enable/disable plugins
- **Hooks** - configure event hooks
- **Settings** - general Synthia settings

## Window Behavior

- Resizable, remembers position and size
- Can be minimized to tray
- Optional "always on top" toggle
- Tray icon: left-click opens GUI, right-click shows quick actions (Start/Stop, Toggle Remote, Quit)

## Technical Implementation

### Task System Migration

**Problem:** Synthia reads from old `~/.claude/todos/{sessionId}-agent-*.json` format.

**Solution:** Read from new `~/.claude/tasks/{sessionId}/` directory structure.

**New format (per task file):**
```json
{
  "id": "1",
  "subject": "Task title",
  "description": "Full description",
  "activeForm": "Present tense action",
  "status": "pending|in_progress|completed",
  "blocks": ["2", "3"],
  "blockedBy": ["4"]
}
```

### New Rust Backend Commands

| Command | Description |
|---------|-------------|
| `get_worktrees` | Scan repos, return worktree list with task data |
| `get_tasks` | Read from `~/.claude/tasks/{sessionId}/` |
| `resume_session` | Spawn WezTerm pane with Claude session |

### React Frontend Changes

- New components: WorktreeList, TaskPanel, MemoryEditor
- Tab/sidebar navigation system
- Reorganize existing Voice components into Voice section

### Data Flow

- Poll worktrees every 30 seconds (or manual refresh)
- Tasks load when worktree selected
- Config sections load on demand

## Migration Plan

1. Implement new task reading logic in Rust backend
2. Build Worktrees section in React
3. Reorganize existing Voice components
4. Port Memory section from TUI
5. Port Config sections from TUI
6. Deprecate TUI dashboard

## Out of Scope

- Transparency (not needed for GUI)
- Clipboard history (disabled, not working)
- Phone inbox (disabled, not working)
- VS Code integration
- File manager integration
