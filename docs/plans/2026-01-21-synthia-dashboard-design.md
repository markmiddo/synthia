# Synthia Dashboard Design

**Command:** `synthia-dash`
**Date:** 2026-01-21
**Status:** Approved

## Overview

Synthia Dashboard is a unified TUI for managing Claude Code configuration and memory. It replaces the standalone `synthia-memory` command with a comprehensive control panel.

## Layout

```
┌─────────────────────────────────────────────────────────┐
│  Synthia Dashboard                            [Header]  │
├──────────┬──────────────────────────────────────────────┤
│          │                                              │
│ Memory   │  [Main Content Area]                         │
│ Agents   │                                              │
│ Commands │  Changes based on selected section           │
│ Plugins  │                                              │
│ Hooks    │                                              │
│ Settings │                                              │
│          │                                              │
├──────────┴──────────────────────────────────────────────┤
│  [s]earch [e]dit [d]elete [n]ew [q]uit       [Footer]   │
└─────────────────────────────────────────────────────────┘
```

## Sections

### Memory
- Secondary toolbar: `[All] [Bugs] [Patterns] [Arch] [Gotchas] [Stack] [Search: ___]`
- List view showing entries with category tag prefix
- Detail panel at bottom showing full entry
- Edit/Delete via modal screens (reuse existing code)
- Stats panel showing counts per category

### Agents
- List of agent files with name and description preview
- Select to view full markdown in detail panel
- `[n]ew` creates new agent from template
- `[e]dit` opens built-in editor modal
- `[d]elete` with confirmation

### Commands
- Same pattern as Agents - list of command files
- Preview description, edit in modal

### Plugins
- List showing plugin name, version, enabled/disabled status
- Toggle enabled state with `[space]` or `[enter]`
- No editing of plugin content (they're managed externally)

### Hooks
- List of hook types (UserPromptSubmit, Stop, etc.)
- Show configured command for each
- Edit command path/timeout in modal

### Settings
- Key-value list (statusLine, alwaysThinkingEnabled, etc.)
- Toggle booleans with space, edit strings in modal

## Navigation

**Sidebar:**
- Always visible on the left (~15 chars wide)
- Arrow keys or `1-6` to switch sections
- Mouse click also works
- Each section remembers its scroll position

**Memory Subcategories:**
- Secondary toolbar within the Memory section
- Filter buttons specific to Memory, don't clutter sidebar

## Editing

**Built-in Editor Modal:**
```
┌─────────────────────────────────────────────────────────┐
│  Edit Agent: backend-developer                          │
├─────────────────────────────────────────────────────────┤
│  Name: [daz                                        ]    │
│  Description: [Use this agent when you need to...  ]    │
│  Model: [opus ▼]                                        │
│  Color: [blue ▼]                                        │
│  ───────────────────────────────────────────────────    │
│  Content:                                               │
│  ┌─────────────────────────────────────────────────┐    │
│  │ You are an expert Go backend developer...       │    │
│  │ (scrollable TextArea)                           │    │
│  └─────────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────────┤
│  [Save (Ctrl+S)]  [Cancel (Esc)]                        │
└─────────────────────────────────────────────────────────┘
```

**Field Types:**
- Text inputs for name, description
- Dropdown selects for model (sonnet/opus/haiku) and color
- Large TextArea for the main content body
- YAML frontmatter parsed into fields, body stays as markdown

**Validation:**
- Required fields checked before save
- Duplicate name warning for agents/commands

## Keyboard Shortcuts

**Global (work everywhere):**
- `1-6` - Jump to section (1=Memory, 2=Agents, etc.)
- `q` - Quit dashboard
- `r` - Refresh current section
- `?` - Show help overlay

**List Navigation:**
- `↑/↓` or `j/k` - Move through list
- `Enter` - View details / expand
- `e` - Edit selected item
- `d` - Delete selected item (with confirmation)
- `n` - New item
- `/` - Focus search (in sections that have it)

**In Memory Section:**
- `Tab` - Cycle through category filters
- `s` - Focus search input

**In Modals:**
- `Ctrl+S` - Save
- `Escape` - Cancel/close
- `Tab` - Move between fields

**Mouse Support:**
- Click sidebar items to switch sections
- Click list items to select
- Click buttons (filter buttons, Save/Cancel)
- Scroll with mouse wheel

## Data Sources

| Section | Source |
|---------|--------|
| Memory | `~/.claude/memory/*.jsonl` |
| Agents | `~/.claude/agents/*.md` |
| Commands | `~/.claude/commands/*.md` |
| Plugins | `~/.claude/settings.json` (enabledPlugins) |
| Hooks | `~/.claude/settings.json` (hooks) |
| Settings | `~/.claude/settings.json` (other keys) |

## File Structure

```
src/synthia/
├── dashboard.py          # Main TUI app (new)
├── dashboard_screens.py  # Modal screens for editing (new)
├── config_manager.py     # Claude config file operations (new)
├── memory.py             # Existing - no changes
└── memory_tui.py         # Deprecate
```

**Config Manager Functions:**
- `load_settings()` - parse `~/.claude/settings.json`
- `save_settings()` - write back with formatting preserved
- `list_agents()` / `load_agent()` / `save_agent()`
- `list_commands()` / `load_command()` / `save_command()`
- Parse markdown frontmatter separately from body

## Entry Point

In `pyproject.toml`:
```toml
[project.scripts]
synthia-dash = "synthia.dashboard:main"
```

Remove `synthia-memory` entry (deprecated).

## Dependencies

Uses Textual (already installed) - no new dependencies.

## Out of Scope

- Backup/restore of settings
- Diff view for changes
- Remote sync
