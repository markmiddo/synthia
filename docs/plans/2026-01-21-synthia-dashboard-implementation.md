# Synthia Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a unified TUI dashboard (`synthia-dash`) for managing Claude Code configuration: memory, agents, commands, plugins, hooks, and settings.

**Architecture:** Textual-based TUI with sidebar navigation and section-specific content panels. Reuses existing memory system and modal patterns from `memory_tui.py`. New `config_manager.py` handles Claude config file operations.

**Tech Stack:** Python 3.10+, Textual TUI framework, PyYAML for frontmatter parsing

---

## Task 1: Create Config Manager - Settings Operations

**Files:**
- Create: `src/synthia/config_manager.py`

**Step 1: Create config_manager.py with settings functions**

```python
"""Config manager for Claude Code settings files.

Handles reading/writing:
- ~/.claude/settings.json (hooks, plugins, general settings)
- ~/.claude/agents/*.md (agent definitions)
- ~/.claude/commands/*.md (slash commands)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

CLAUDE_DIR = Path.home() / ".claude"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
AGENTS_DIR = CLAUDE_DIR / "agents"
COMMANDS_DIR = CLAUDE_DIR / "commands"


def load_settings() -> Dict[str, Any]:
    """Load settings.json, return empty dict if not found."""
    if not SETTINGS_FILE.exists():
        return {}
    with open(SETTINGS_FILE, "r") as f:
        return json.load(f)


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings.json with 2-space indentation."""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
```

**Step 2: Verify file created**

Run: `ls -la src/synthia/config_manager.py`
Expected: File exists

**Step 3: Commit**

```bash
git add src/synthia/config_manager.py
git commit -m "feat(dashboard): add config_manager with settings load/save"
```

---

## Task 2: Config Manager - Agent Operations

**Files:**
- Modify: `src/synthia/config_manager.py`

**Step 1: Add AgentConfig dataclass and agent functions**

Add after the `save_settings` function:

```python
@dataclass
class AgentConfig:
    """Represents an agent definition from ~/.claude/agents/*.md"""

    filename: str
    name: str
    description: str
    model: str = "sonnet"
    color: str = "green"
    body: str = ""

    @classmethod
    def from_file(cls, filepath: Path) -> "AgentConfig":
        """Parse agent markdown file with YAML frontmatter."""
        content = filepath.read_text()
        frontmatter, body = parse_frontmatter(content)
        return cls(
            filename=filepath.name,
            name=frontmatter.get("name", filepath.stem),
            description=frontmatter.get("description", ""),
            model=frontmatter.get("model", "sonnet"),
            color=frontmatter.get("color", "green"),
            body=body.strip(),
        )

    def to_markdown(self) -> str:
        """Convert back to markdown with frontmatter."""
        lines = [
            "---",
            f"name: {self.name}",
            f"description: {self.description}",
            f"model: {self.model}",
            f"color: {self.color}",
            "---",
            "",
            self.body,
        ]
        return "\n".join(lines)


def parse_frontmatter(content: str) -> tuple[Dict[str, str], str]:
    """Parse YAML frontmatter from markdown content.

    Returns (frontmatter_dict, body_content).
    """
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = {}
    for line in parts[1].strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            frontmatter[key.strip()] = value.strip()

    return frontmatter, parts[2]


def list_agents() -> List[AgentConfig]:
    """List all agent configs from ~/.claude/agents/"""
    if not AGENTS_DIR.exists():
        return []

    agents = []
    for filepath in sorted(AGENTS_DIR.glob("*.md")):
        try:
            agents.append(AgentConfig.from_file(filepath))
        except Exception:
            pass
    return agents


def load_agent(filename: str) -> Optional[AgentConfig]:
    """Load a specific agent by filename."""
    filepath = AGENTS_DIR / filename
    if not filepath.exists():
        return None
    return AgentConfig.from_file(filepath)


def save_agent(agent: AgentConfig) -> None:
    """Save agent to file."""
    AGENTS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = AGENTS_DIR / agent.filename
    filepath.write_text(agent.to_markdown())


def delete_agent(filename: str) -> bool:
    """Delete an agent file. Returns True if deleted."""
    filepath = AGENTS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return True
    return False
```

**Step 2: Verify syntax**

Run: `python -c "from synthia.config_manager import list_agents; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/config_manager.py
git commit -m "feat(dashboard): add agent config operations to config_manager"
```

---

## Task 3: Config Manager - Command Operations

**Files:**
- Modify: `src/synthia/config_manager.py`

**Step 1: Add CommandConfig dataclass and command functions**

Add after the agent functions:

```python
@dataclass
class CommandConfig:
    """Represents a slash command from ~/.claude/commands/*.md"""

    filename: str
    description: str
    body: str = ""

    @classmethod
    def from_file(cls, filepath: Path) -> "CommandConfig":
        """Parse command markdown file."""
        content = filepath.read_text()
        frontmatter, body = parse_frontmatter(content)
        return cls(
            filename=filepath.name,
            description=frontmatter.get("description", ""),
            body=body.strip(),
        )

    def to_markdown(self) -> str:
        """Convert back to markdown with frontmatter."""
        lines = [
            "---",
            f"description: {self.description}",
            "---",
            "",
            self.body,
        ]
        return "\n".join(lines)


def list_commands() -> List[CommandConfig]:
    """List all command configs from ~/.claude/commands/"""
    if not COMMANDS_DIR.exists():
        return []

    commands = []
    for filepath in sorted(COMMANDS_DIR.glob("*.md")):
        try:
            commands.append(CommandConfig.from_file(filepath))
        except Exception:
            pass
    return commands


def load_command(filename: str) -> Optional[CommandConfig]:
    """Load a specific command by filename."""
    filepath = COMMANDS_DIR / filename
    if not filepath.exists():
        return None
    return CommandConfig.from_file(filepath)


def save_command(command: CommandConfig) -> None:
    """Save command to file."""
    COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = COMMANDS_DIR / command.filename
    filepath.write_text(command.to_markdown())


def delete_command(filename: str) -> bool:
    """Delete a command file. Returns True if deleted."""
    filepath = COMMANDS_DIR / filename
    if filepath.exists():
        filepath.unlink()
        return True
    return False
```

**Step 2: Verify syntax**

Run: `python -c "from synthia.config_manager import list_commands; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/config_manager.py
git commit -m "feat(dashboard): add command config operations to config_manager"
```

---

## Task 4: Config Manager - Plugin Operations

**Files:**
- Modify: `src/synthia/config_manager.py`

**Step 1: Add plugin helper functions**

Add after the command functions:

```python
PLUGINS_FILE = CLAUDE_DIR / "plugins" / "installed_plugins.json"


@dataclass
class PluginInfo:
    """Plugin information combining installed status and enabled state."""

    name: str
    version: str
    enabled: bool
    installed_at: str = ""

    @property
    def display_name(self) -> str:
        """Extract readable name from plugin ID."""
        # "context7@claude-plugins-official" -> "context7"
        return self.name.split("@")[0]


def list_plugins() -> List[PluginInfo]:
    """List all installed plugins with their enabled status."""
    settings = load_settings()
    enabled_plugins = settings.get("enabledPlugins", {})

    if not PLUGINS_FILE.exists():
        # Fall back to just what's in settings
        return [
            PluginInfo(name=name, version="", enabled=enabled)
            for name, enabled in enabled_plugins.items()
        ]

    with open(PLUGINS_FILE, "r") as f:
        installed = json.load(f)

    plugins = []
    for name, versions in installed.get("plugins", {}).items():
        if versions:
            latest = versions[0]
            plugins.append(PluginInfo(
                name=name,
                version=latest.get("version", ""),
                enabled=enabled_plugins.get(name, False),
                installed_at=latest.get("installedAt", ""),
            ))

    return plugins


def set_plugin_enabled(plugin_name: str, enabled: bool) -> None:
    """Enable or disable a plugin."""
    settings = load_settings()
    if "enabledPlugins" not in settings:
        settings["enabledPlugins"] = {}
    settings["enabledPlugins"][plugin_name] = enabled
    save_settings(settings)
```

**Step 2: Verify syntax**

Run: `python -c "from synthia.config_manager import list_plugins; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/config_manager.py
git commit -m "feat(dashboard): add plugin operations to config_manager"
```

---

## Task 5: Config Manager - Hooks Operations

**Files:**
- Modify: `src/synthia/config_manager.py`

**Step 1: Add hook helper functions**

Add after the plugin functions:

```python
@dataclass
class HookConfig:
    """Represents a hook configuration."""

    event: str  # "UserPromptSubmit", "Stop", etc.
    command: str
    timeout: int = 30
    hook_type: str = "command"


def list_hooks() -> List[HookConfig]:
    """List all configured hooks."""
    settings = load_settings()
    hooks_config = settings.get("hooks", {})

    hooks = []
    for event, event_hooks in hooks_config.items():
        for hook_group in event_hooks:
            for hook in hook_group.get("hooks", []):
                hooks.append(HookConfig(
                    event=event,
                    command=hook.get("command", ""),
                    timeout=hook.get("timeout", 30),
                    hook_type=hook.get("type", "command"),
                ))

    return hooks


def save_hook(hook: HookConfig) -> None:
    """Save or update a hook configuration."""
    settings = load_settings()
    if "hooks" not in settings:
        settings["hooks"] = {}

    if hook.event not in settings["hooks"]:
        settings["hooks"][hook.event] = []

    # Find and update existing or add new
    event_hooks = settings["hooks"][hook.event]
    found = False
    for hook_group in event_hooks:
        for existing in hook_group.get("hooks", []):
            if existing.get("command") == hook.command:
                existing["timeout"] = hook.timeout
                existing["type"] = hook.hook_type
                found = True
                break

    if not found:
        if not event_hooks:
            event_hooks.append({"hooks": []})
        event_hooks[0]["hooks"].append({
            "type": hook.hook_type,
            "command": hook.command,
            "timeout": hook.timeout,
        })

    save_settings(settings)


def delete_hook(event: str, command: str) -> bool:
    """Delete a hook by event and command. Returns True if deleted."""
    settings = load_settings()
    hooks_config = settings.get("hooks", {})

    if event not in hooks_config:
        return False

    for hook_group in hooks_config[event]:
        hooks_list = hook_group.get("hooks", [])
        for i, hook in enumerate(hooks_list):
            if hook.get("command") == command:
                hooks_list.pop(i)
                save_settings(settings)
                return True

    return False
```

**Step 2: Verify syntax**

Run: `python -c "from synthia.config_manager import list_hooks; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/config_manager.py
git commit -m "feat(dashboard): add hook operations to config_manager"
```

---

## Task 6: Dashboard Shell - Basic Layout

**Files:**
- Create: `src/synthia/dashboard.py`

**Step 1: Create dashboard.py with basic sidebar layout**

```python
"""Synthia Dashboard - Unified TUI for Claude Code configuration.

Launch with: synthia-dash

Features:
- Memory management (bugs, patterns, architecture, gotchas, stack)
- Agent configuration
- Slash command management
- Plugin enable/disable
- Hook configuration
- General settings
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Header, Label, ListItem, ListView, Static


class Section(Enum):
    """Dashboard sections."""
    MEMORY = "memory"
    AGENTS = "agents"
    COMMANDS = "commands"
    PLUGINS = "plugins"
    HOOKS = "hooks"
    SETTINGS = "settings"


class SidebarItem(ListItem):
    """Sidebar navigation item."""

    def __init__(self, section: Section, index: int):
        super().__init__()
        self.section = section
        self.index = index

    def compose(self) -> ComposeResult:
        label = f"{self.index}. {self.section.value.title()}"
        yield Label(label)


class SynthiaDashboard(App):
    """Unified TUI Dashboard for Claude Code configuration."""

    CSS = """
    Screen {
        background: $surface;
    }

    #sidebar {
        width: 18;
        height: 100%;
        border: solid $primary;
        padding: 1;
    }

    #sidebar-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #sidebar ListView {
        height: 1fr;
    }

    #sidebar ListItem {
        padding: 0 1;
    }

    #sidebar ListItem:hover {
        background: $primary-darken-2;
    }

    #main-content {
        width: 1fr;
        height: 100%;
        padding: 1;
    }

    #content-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #content-area {
        height: 1fr;
        border: solid $secondary;
        padding: 1;
    }

    #status-bar {
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "goto_section('memory')", "Memory", show=False),
        Binding("2", "goto_section('agents')", "Agents", show=False),
        Binding("3", "goto_section('commands')", "Commands", show=False),
        Binding("4", "goto_section('plugins')", "Plugins", show=False),
        Binding("5", "goto_section('hooks')", "Hooks", show=False),
        Binding("6", "goto_section('settings')", "Settings", show=False),
        Binding("r", "refresh", "Refresh"),
    ]

    TITLE = "Synthia Dashboard"

    def __init__(self):
        super().__init__()
        self.current_section: Section = Section.MEMORY

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Sections", id="sidebar-title")
                yield ListView(
                    SidebarItem(Section.MEMORY, 1),
                    SidebarItem(Section.AGENTS, 2),
                    SidebarItem(Section.COMMANDS, 3),
                    SidebarItem(Section.PLUGINS, 4),
                    SidebarItem(Section.HOOKS, 5),
                    SidebarItem(Section.SETTINGS, 6),
                    id="sidebar-list",
                )
            with Vertical(id="main-content"):
                yield Label("Memory", id="content-title")
                yield Static("Select a section from the sidebar", id="content-area")
        yield Static("[1-6] Section | [r] Refresh | [q] Quit", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize with Memory section."""
        self._switch_section(Section.MEMORY)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar selection."""
        if isinstance(event.item, SidebarItem):
            self._switch_section(event.item.section)

    def action_goto_section(self, section_name: str) -> None:
        """Jump to section by name."""
        try:
            section = Section(section_name)
            self._switch_section(section)
        except ValueError:
            pass

    def action_refresh(self) -> None:
        """Refresh current section."""
        self._switch_section(self.current_section)
        self._set_status("Refreshed")

    def _switch_section(self, section: Section) -> None:
        """Switch to a different section."""
        self.current_section = section
        title = self.query_one("#content-title", Label)
        title.update(section.value.title())

        content = self.query_one("#content-area", Static)
        content.update(f"[{section.value.upper()}] Content will appear here")

        self._set_status(f"Viewing {section.value.title()}")

    def _set_status(self, text: str) -> None:
        """Update status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(f"{text} | [1-6] Section | [r] Refresh | [q] Quit")


def main():
    """Run the Synthia Dashboard."""
    app = SynthiaDashboard()
    app.run()


if __name__ == "__main__":
    main()
```

**Step 2: Test the shell runs**

Run: `cd /home/markmiddo/dev/misc/synthia && python -c "from synthia.dashboard import SynthiaDashboard; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add basic dashboard shell with sidebar navigation"
```

---

## Task 7: Add Entry Point to pyproject.toml

**Files:**
- Modify: `pyproject.toml:58-60`

**Step 1: Update project.scripts to add synthia-dash and remove synthia-memory**

Replace the `[project.scripts]` section:

```toml
[project.scripts]
synthia = "synthia.main:main"
synthia-dash = "synthia.dashboard:main"
```

**Step 2: Reinstall package**

Run: `cd /home/markmiddo/dev/misc/synthia && pip install -e .`
Expected: Successfully installed synthia

**Step 3: Test entry point**

Run: `which synthia-dash`
Expected: Path to synthia-dash

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(dashboard): add synthia-dash entry point, deprecate synthia-memory"
```

---

## Task 8: Memory Section - Integrate Existing Memory UI

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add memory section imports and widgets**

Add to the imports at the top:

```python
import json
from textual import work
from textual.widgets import Button, Input, TextArea
from textual.screen import ModalScreen

from synthia.memory import (
    MEMORY_CATEGORIES,
    MemoryEntry,
    get_memory_system,
)
```

**Step 2: Add MemoryListItem class after SidebarItem**

```python
class MemoryListItem(ListItem):
    """List item for memory entries."""

    def __init__(self, entry: MemoryEntry, line_number: int):
        super().__init__()
        self.entry = entry
        self.line_number = line_number

    def compose(self) -> ComposeResult:
        cat = self.entry.category.upper()
        if self.entry.category == "bug":
            text = f"[{cat}] {self.entry.data.get('error', 'N/A')[:50]}"
        elif self.entry.category == "pattern":
            text = f"[{cat}] {self.entry.data.get('topic', 'N/A')[:50]}"
        elif self.entry.category == "arch":
            text = f"[{cat}] {self.entry.data.get('decision', 'N/A')[:50]}"
        elif self.entry.category == "gotcha":
            text = f"[{cat}] {self.entry.data.get('area', 'N/A')[:50]}"
        elif self.entry.category == "stack":
            text = f"[{cat}] {self.entry.data.get('tool', 'N/A')[:50]}"
        else:
            text = f"[{cat}] Unknown"
        yield Label(text)
```

**Step 3: Add memory section content widget class**

Add after MemoryListItem:

```python
class MemorySectionContent(Vertical):
    """Content widget for Memory section."""

    def __init__(self):
        super().__init__()
        self.current_entries: list[tuple[MemoryEntry, int]] = []
        self.selected_index: int = -1
        self.active_filter: str = "all"

    def compose(self) -> ComposeResult:
        with Horizontal(classes="toolbar"):
            yield Button("All", id="btn-all", variant="primary")
            yield Button("Bugs", id="btn-bugs")
            yield Button("Patterns", id="btn-patterns")
            yield Button("Arch", id="btn-arch")
            yield Button("Gotchas", id="btn-gotchas")
            yield Button("Stack", id="btn-stack")
            yield Input(placeholder="Search...", id="memory-search")
        yield ListView(id="memory-list")
        yield Static("Select an entry to view details", id="memory-detail")
```

**Step 4: Update CSS in SynthiaDashboard to include toolbar and memory styles**

Add to the CSS string:

```python
    .toolbar {
        height: 3;
        margin-bottom: 1;
    }

    .toolbar Button {
        margin-right: 1;
    }

    .toolbar Input {
        width: 1fr;
    }

    #memory-list {
        height: 1fr;
        border: solid $secondary;
    }

    #memory-detail {
        height: 10;
        border: solid $accent;
        margin-top: 1;
        padding: 1;
    }
```

**Step 5: Commit partial progress**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add memory section widgets and styling"
```

---

## Task 9: Memory Section - Load and Display

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add memory loading methods to SynthiaDashboard**

Add these methods to the SynthiaDashboard class:

```python
    def _show_memory_section(self) -> None:
        """Show the memory section content."""
        content = self.query_one("#content-area", Static)
        # Replace static with memory content widget
        content.update("")
        self._load_memory_all()

    @work(thread=True)
    def _load_memory_all(self) -> None:
        """Load all memory entries."""
        mem = get_memory_system()
        all_entries = []

        for cat, filename in MEMORY_CATEGORIES.items():
            filepath = mem.memory_dir / filename
            if filepath.exists():
                with open(filepath, "r") as f:
                    for i, line in enumerate(f):
                        line = line.strip()
                        if line:
                            try:
                                data = json.loads(line)
                                entry = MemoryEntry.from_dict(cat, data)
                                all_entries.append((entry, i))
                            except json.JSONDecodeError:
                                pass

        self.call_from_thread(self._display_memory_results, all_entries, "All Entries")

    @work(thread=True)
    def _load_memory_category(self, category: str) -> None:
        """Load specific memory category."""
        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES.get(category, "")

        entries = []
        if filepath.exists():
            with open(filepath, "r") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            entry = MemoryEntry.from_dict(category, data)
                            entries.append((entry, i))
                        except json.JSONDecodeError:
                            pass

        self.call_from_thread(self._display_memory_results, entries, f"{category.title()}")

    def _display_memory_results(self, entries: list[tuple[MemoryEntry, int]], title: str) -> None:
        """Display memory entries in the list."""
        self._memory_entries = entries
        try:
            list_view = self.query_one("#memory-list", ListView)
            list_view.clear()
            for entry, line_num in entries:
                list_view.append(MemoryListItem(entry, line_num))
            self._set_status(f"{title} | {len(entries)} entries")
        except Exception:
            pass
```

**Step 2: Update _switch_section to call memory section**

Modify the `_switch_section` method:

```python
    def _switch_section(self, section: Section) -> None:
        """Switch to a different section."""
        self.current_section = section
        title = self.query_one("#content-title", Label)
        title.update(section.value.title())

        if section == Section.MEMORY:
            self._show_memory_section()
        else:
            content = self.query_one("#content-area", Static)
            content.update(f"[{section.value.upper()}] Content will appear here")

        self._set_status(f"Viewing {section.value.title()}")
```

**Step 3: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add memory section data loading"
```

---

## Task 10: Agents Section - List and Display

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add agent imports**

Add to imports:

```python
from synthia.config_manager import (
    AgentConfig,
    list_agents,
    load_agent,
    save_agent,
    delete_agent,
)
```

**Step 2: Add AgentListItem class**

```python
class AgentListItem(ListItem):
    """List item for agent entries."""

    def __init__(self, agent: AgentConfig):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        text = f"[{self.agent.model.upper()}] {self.agent.name}"
        yield Label(text)
```

**Step 3: Add agent section methods to SynthiaDashboard**

```python
    def _show_agents_section(self) -> None:
        """Show agents section."""
        self._load_agents()

    @work(thread=True)
    def _load_agents(self) -> None:
        """Load all agents."""
        agents = list_agents()
        self.call_from_thread(self._display_agents, agents)

    def _display_agents(self, agents: list[AgentConfig]) -> None:
        """Display agents in list."""
        self._agents = agents
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for agent in agents:
                list_view.append(AgentListItem(agent))
            self._set_status(f"Agents | {len(agents)} found")
        except Exception:
            pass
```

**Step 4: Update _switch_section for agents**

Add to the `_switch_section` method:

```python
        elif section == Section.AGENTS:
            self._show_agents_section()
```

**Step 5: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add agents section listing"
```

---

## Task 11: Plugins Section - List and Toggle

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add plugin imports**

Add to config_manager imports:

```python
from synthia.config_manager import (
    # ... existing imports ...
    PluginInfo,
    list_plugins,
    set_plugin_enabled,
)
```

**Step 2: Add PluginListItem class**

```python
class PluginListItem(ListItem):
    """List item for plugin entries."""

    def __init__(self, plugin: PluginInfo):
        super().__init__()
        self.plugin = plugin

    def compose(self) -> ComposeResult:
        status = "✓" if self.plugin.enabled else "✗"
        text = f"[{status}] {self.plugin.display_name} (v{self.plugin.version[:8]})"
        yield Label(text)
```

**Step 3: Add plugin section methods**

```python
    def _show_plugins_section(self) -> None:
        """Show plugins section."""
        self._load_plugins()

    @work(thread=True)
    def _load_plugins(self) -> None:
        """Load all plugins."""
        plugins = list_plugins()
        self.call_from_thread(self._display_plugins, plugins)

    def _display_plugins(self, plugins: list[PluginInfo]) -> None:
        """Display plugins in list."""
        self._plugins = plugins
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for plugin in plugins:
                list_view.append(PluginListItem(plugin))
            self._set_status(f"Plugins | {len(plugins)} installed | Space to toggle")
        except Exception:
            pass

    def _toggle_selected_plugin(self) -> None:
        """Toggle the selected plugin's enabled state."""
        if not hasattr(self, '_plugins') or not self._plugins:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._plugins):
                plugin = self._plugins[index]
                new_state = not plugin.enabled
                set_plugin_enabled(plugin.name, new_state)
                self._load_plugins()
                self._set_status(f"{'Enabled' if new_state else 'Disabled'} {plugin.display_name}")
        except Exception:
            pass
```

**Step 4: Add space binding for toggle**

Add to BINDINGS:

```python
        Binding("space", "toggle_item", "Toggle", show=False),
```

Add action method:

```python
    def action_toggle_item(self) -> None:
        """Toggle current item (for plugins)."""
        if self.current_section == Section.PLUGINS:
            self._toggle_selected_plugin()
```

**Step 5: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add plugins section with toggle"
```

---

## Task 12: Hooks Section - List Display

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add hook imports**

Add to config_manager imports:

```python
from synthia.config_manager import (
    # ... existing imports ...
    HookConfig,
    list_hooks,
)
```

**Step 2: Add HookListItem class**

```python
class HookListItem(ListItem):
    """List item for hook entries."""

    def __init__(self, hook: HookConfig):
        super().__init__()
        self.hook = hook

    def compose(self) -> ComposeResult:
        cmd_short = self.hook.command.split("/")[-1][:30]
        text = f"[{self.hook.event}] {cmd_short}"
        yield Label(text)
```

**Step 3: Add hooks section methods**

```python
    def _show_hooks_section(self) -> None:
        """Show hooks section."""
        self._load_hooks()

    @work(thread=True)
    def _load_hooks(self) -> None:
        """Load all hooks."""
        hooks = list_hooks()
        self.call_from_thread(self._display_hooks, hooks)

    def _display_hooks(self, hooks: list[HookConfig]) -> None:
        """Display hooks in list."""
        self._hooks = hooks
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for hook in hooks:
                list_view.append(HookListItem(hook))
            self._set_status(f"Hooks | {len(hooks)} configured")
        except Exception:
            pass
```

**Step 4: Update _switch_section for hooks**

Add case:

```python
        elif section == Section.HOOKS:
            self._show_hooks_section()
```

**Step 5: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add hooks section listing"
```

---

## Task 13: Settings Section - Key/Value Display

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add SettingListItem class**

```python
class SettingListItem(ListItem):
    """List item for settings."""

    def __init__(self, key: str, value: Any):
        super().__init__()
        self.key = key
        self.value = value

    def compose(self) -> ComposeResult:
        if isinstance(self.value, bool):
            display = "✓ Enabled" if self.value else "✗ Disabled"
        elif isinstance(self.value, dict):
            display = "{...}"
        else:
            display = str(self.value)[:40]
        yield Label(f"{self.key}: {display}")
```

**Step 2: Add settings section methods**

```python
    def _show_settings_section(self) -> None:
        """Show settings section."""
        self._load_settings()

    @work(thread=True)
    def _load_settings(self) -> None:
        """Load settings."""
        from synthia.config_manager import load_settings
        settings = load_settings()
        # Filter out hooks, enabledPlugins (shown in other sections)
        filtered = {k: v for k, v in settings.items()
                   if k not in ("hooks", "enabledPlugins")}
        self.call_from_thread(self._display_settings, filtered)

    def _display_settings(self, settings: dict) -> None:
        """Display settings in list."""
        self._settings = settings
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for key, value in settings.items():
                list_view.append(SettingListItem(key, value))
            self._set_status(f"Settings | {len(settings)} items | Space to toggle booleans")
        except Exception:
            pass
```

**Step 3: Update _switch_section for settings**

Add case:

```python
        elif section == Section.SETTINGS:
            self._show_settings_section()
```

**Step 4: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add settings section listing"
```

---

## Task 14: Commands Section - List Display

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add command imports**

Add to config_manager imports:

```python
from synthia.config_manager import (
    # ... existing imports ...
    CommandConfig,
    list_commands,
)
```

**Step 2: Add CommandListItem class**

```python
class CommandListItem(ListItem):
    """List item for command entries."""

    def __init__(self, command: CommandConfig):
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        name = self.command.filename.replace(".md", "")
        desc = self.command.description[:40] if self.command.description else "No description"
        yield Label(f"/{name} - {desc}")
```

**Step 3: Add commands section methods**

```python
    def _show_commands_section(self) -> None:
        """Show commands section."""
        self._load_commands()

    @work(thread=True)
    def _load_commands(self) -> None:
        """Load all commands."""
        commands = list_commands()
        self.call_from_thread(self._display_commands, commands)

    def _display_commands(self, commands: list[CommandConfig]) -> None:
        """Display commands in list."""
        self._commands = commands
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for cmd in commands:
                list_view.append(CommandListItem(cmd))
            self._set_status(f"Commands | {len(commands)} found")
        except Exception:
            pass
```

**Step 4: Update _switch_section for commands**

Add case:

```python
        elif section == Section.COMMANDS:
            self._show_commands_section()
```

**Step 5: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add commands section listing"
```

---

## Task 15: Edit Modal Screens

**Files:**
- Create: `src/synthia/dashboard_screens.py`

**Step 1: Create dashboard_screens.py with edit modals**

```python
"""Modal screens for Synthia Dashboard editing."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, TextArea

from synthia.config_manager import AgentConfig, CommandConfig, HookConfig


class ConfirmDeleteScreen(ModalScreen[bool]):
    """Generic delete confirmation modal."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
    ]

    CSS = """
    ConfirmDeleteScreen {
        align: center middle;
    }

    #confirm-dialog {
        width: 50;
        height: 10;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }

    #confirm-title {
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #button-row {
        margin-top: 1;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, item_name: str):
        super().__init__()
        self.item_name = item_name

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label("Delete?", id="confirm-title")
            yield Static(f"Delete: {self.item_name}")
            with Horizontal(id="button-row"):
                yield Button("Yes (Y)", id="yes-btn", variant="error")
                yield Button("No (N)", id="no-btn", variant="primary")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes-btn")


class EditAgentScreen(ModalScreen[Optional[AgentConfig]]):
    """Modal for editing an agent."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    EditAgentScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 85%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
        color: $primary;
    }

    .field-row {
        height: 3;
    }

    .field-row Input {
        width: 1fr;
    }

    .field-row Select {
        width: 20;
    }

    #body-area {
        height: 1fr;
        margin-top: 1;
    }

    #button-row {
        margin-top: 1;
        height: 3;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, agent: Optional[AgentConfig] = None):
        super().__init__()
        self.agent = agent or AgentConfig(
            filename="new-agent.md",
            name="new-agent",
            description="",
            model="sonnet",
            color="green",
            body="",
        )
        self.is_new = agent is None

    def compose(self) -> ComposeResult:
        title = "New Agent" if self.is_new else f"Edit: {self.agent.name}"
        with Vertical(id="edit-dialog"):
            yield Label(title, id="edit-title")

            yield Label("Name:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(self.agent.name, id="name-input")

            yield Label("Description:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Input(self.agent.description, id="desc-input")

            yield Label("Model / Color:", classes="field-label")
            with Horizontal(classes="field-row"):
                yield Select(
                    [(m, m) for m in ["sonnet", "opus", "haiku"]],
                    value=self.agent.model,
                    id="model-select",
                )
                yield Select(
                    [(c, c) for c in ["green", "blue", "red", "yellow", "purple"]],
                    value=self.agent.color,
                    id="color-select",
                )

            yield Label("Content:", classes="field-label")
            yield TextArea(self.agent.body, id="body-area")

            with Horizontal(id="button-row"):
                yield Button("Save (Ctrl+S)", id="save-btn", variant="primary")
                yield Button("Cancel (Esc)", id="cancel-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._do_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._do_save()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _do_save(self) -> None:
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return

        desc = self.query_one("#desc-input", Input).value
        model = self.query_one("#model-select", Select).value
        color = self.query_one("#color-select", Select).value
        body = self.query_one("#body-area", TextArea).text

        filename = f"{name}.md" if self.is_new else self.agent.filename

        result = AgentConfig(
            filename=filename,
            name=name,
            description=desc,
            model=model or "sonnet",
            color=color or "green",
            body=body,
        )
        self.dismiss(result)


class EditCommandScreen(ModalScreen[Optional[CommandConfig]]):
    """Modal for editing a command."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    CSS = """
    EditCommandScreen {
        align: center middle;
    }

    #edit-dialog {
        width: 85%;
        height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #edit-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
        color: $primary;
    }

    #body-area {
        height: 1fr;
        margin-top: 1;
    }

    #button-row {
        margin-top: 1;
        height: 3;
    }

    #button-row Button {
        margin-right: 2;
    }
    """

    def __init__(self, command: Optional[CommandConfig] = None):
        super().__init__()
        self.command = command or CommandConfig(
            filename="new-command.md",
            description="",
            body="",
        )
        self.is_new = command is None

    def compose(self) -> ComposeResult:
        name = self.command.filename.replace(".md", "")
        title = "New Command" if self.is_new else f"Edit: /{name}"
        with Vertical(id="edit-dialog"):
            yield Label(title, id="edit-title")

            yield Label("Name (without .md):", classes="field-label")
            yield Input(name, id="name-input")

            yield Label("Description:", classes="field-label")
            yield Input(self.command.description, id="desc-input")

            yield Label("Content:", classes="field-label")
            yield TextArea(self.command.body, id="body-area")

            with Horizontal(id="button-row"):
                yield Button("Save (Ctrl+S)", id="save-btn", variant="primary")
                yield Button("Cancel (Esc)", id="cancel-btn")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        self._do_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            self._do_save()
        elif event.button.id == "cancel-btn":
            self.dismiss(None)

    def _do_save(self) -> None:
        name = self.query_one("#name-input", Input).value.strip()
        if not name:
            return

        desc = self.query_one("#desc-input", Input).value
        body = self.query_one("#body-area", TextArea).text

        filename = f"{name}.md"

        result = CommandConfig(
            filename=filename,
            description=desc,
            body=body,
        )
        self.dismiss(result)
```

**Step 2: Verify syntax**

Run: `python -c "from synthia.dashboard_screens import EditAgentScreen; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/synthia/dashboard_screens.py
git commit -m "feat(dashboard): add edit modal screens for agents and commands"
```

---

## Task 16: Wire Up Edit/Delete Actions

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add imports for screens**

```python
from synthia.dashboard_screens import (
    ConfirmDeleteScreen,
    EditAgentScreen,
    EditCommandScreen,
)
```

**Step 2: Add edit/delete bindings**

Add to BINDINGS:

```python
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("n", "new_item", "New"),
```

**Step 3: Add edit action methods**

```python
    def action_edit_selected(self) -> None:
        """Edit the selected item."""
        if self.current_section == Section.AGENTS:
            self._edit_selected_agent()
        elif self.current_section == Section.COMMANDS:
            self._edit_selected_command()

    def _edit_selected_agent(self) -> None:
        """Edit selected agent."""
        if not hasattr(self, '_agents') or not self._agents:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._agents):
                agent = self._agents[index]
                self.push_screen(EditAgentScreen(agent), self._on_agent_edit_complete)
        except Exception:
            pass

    def _on_agent_edit_complete(self, result: Optional[AgentConfig]) -> None:
        """Handle agent edit completion."""
        if result:
            save_agent(result)
            self._load_agents()
            self._set_status(f"Saved agent: {result.name}")

    def _edit_selected_command(self) -> None:
        """Edit selected command."""
        if not hasattr(self, '_commands') or not self._commands:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._commands):
                cmd = self._commands[index]
                self.push_screen(EditCommandScreen(cmd), self._on_command_edit_complete)
        except Exception:
            pass

    def _on_command_edit_complete(self, result: Optional[CommandConfig]) -> None:
        """Handle command edit completion."""
        if result:
            from synthia.config_manager import save_command
            save_command(result)
            self._load_commands()
            self._set_status(f"Saved command: {result.filename}")
```

**Step 4: Add new item action**

```python
    def action_new_item(self) -> None:
        """Create a new item in current section."""
        if self.current_section == Section.AGENTS:
            self.push_screen(EditAgentScreen(None), self._on_agent_edit_complete)
        elif self.current_section == Section.COMMANDS:
            self.push_screen(EditCommandScreen(None), self._on_command_edit_complete)
```

**Step 5: Add delete action**

```python
    def action_delete_selected(self) -> None:
        """Delete the selected item."""
        if self.current_section == Section.AGENTS:
            self._delete_selected_agent()
        elif self.current_section == Section.COMMANDS:
            self._delete_selected_command()

    def _delete_selected_agent(self) -> None:
        """Delete selected agent."""
        if not hasattr(self, '_agents') or not self._agents:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._agents):
                agent = self._agents[index]
                self.push_screen(
                    ConfirmDeleteScreen(agent.name),
                    lambda confirmed: self._do_delete_agent(agent.filename) if confirmed else None
                )
        except Exception:
            pass

    def _do_delete_agent(self, filename: str) -> None:
        """Actually delete the agent."""
        delete_agent(filename)
        self._load_agents()
        self._set_status("Agent deleted")

    def _delete_selected_command(self) -> None:
        """Delete selected command."""
        if not hasattr(self, '_commands') or not self._commands:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._commands):
                cmd = self._commands[index]
                name = cmd.filename.replace(".md", "")
                self.push_screen(
                    ConfirmDeleteScreen(f"/{name}"),
                    lambda confirmed: self._do_delete_command(cmd.filename) if confirmed else None
                )
        except Exception:
            pass

    def _do_delete_command(self, filename: str) -> None:
        """Actually delete the command."""
        from synthia.config_manager import delete_command
        delete_command(filename)
        self._load_commands()
        self._set_status("Command deleted")
```

**Step 6: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): wire up edit, new, and delete actions"
```

---

## Task 17: Detail Panel for Selected Items

**Files:**
- Modify: `src/synthia/dashboard.py`

**Step 1: Add detail panel widget to compose**

Update the main content area in `compose()`:

```python
            with Vertical(id="main-content"):
                yield Label("Memory", id="content-title")
                yield ListView(id="content-list")
                yield Static("Select an item to view details", id="detail-panel")
```

**Step 2: Add CSS for detail panel**

Add to CSS:

```python
    #content-list {
        height: 1fr;
        border: solid $secondary;
    }

    #detail-panel {
        height: 12;
        border: solid $accent;
        margin-top: 1;
        padding: 1;
    }
```

**Step 3: Add list view highlight handler**

```python
    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Update detail panel when item is highlighted."""
        detail = self.query_one("#detail-panel", Static)

        if isinstance(event.item, AgentListItem):
            agent = event.item.agent
            detail.update(f"Name: {agent.name}\nModel: {agent.model}\nColor: {agent.color}\n\n{agent.description}")
        elif isinstance(event.item, CommandListItem):
            cmd = event.item.command
            detail.update(f"Command: /{cmd.filename.replace('.md', '')}\n\n{cmd.description}")
        elif isinstance(event.item, PluginListItem):
            plugin = event.item.plugin
            status = "Enabled" if plugin.enabled else "Disabled"
            detail.update(f"Plugin: {plugin.display_name}\nVersion: {plugin.version}\nStatus: {status}")
        elif isinstance(event.item, HookListItem):
            hook = event.item.hook
            detail.update(f"Event: {hook.event}\nCommand: {hook.command}\nTimeout: {hook.timeout}s")
        elif isinstance(event.item, SettingListItem):
            detail.update(f"Key: {event.item.key}\nValue: {event.item.value}")
        elif isinstance(event.item, MemoryListItem):
            detail.update(event.item.entry.format_display())
```

**Step 4: Commit**

```bash
git add src/synthia/dashboard.py
git commit -m "feat(dashboard): add detail panel for selected items"
```

---

## Task 18: Help Overlay

**Files:**
- Modify: `src/synthia/dashboard_screens.py`

**Step 1: Add HelpScreen class**

```python
class HelpScreen(ModalScreen[None]):
    """Help overlay showing keyboard shortcuts."""

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("question_mark", "close", "Close"),
    ]

    CSS = """
    HelpScreen {
        align: center middle;
    }

    #help-dialog {
        width: 60;
        height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    #help-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    """

    def compose(self) -> ComposeResult:
        help_text = """
[1-6]  Jump to section
[j/k]  Move up/down in list
[e]    Edit selected item
[n]    New item
[d]    Delete selected item
[space] Toggle (plugins)
[r]    Refresh
[q]    Quit
[?]    This help
"""
        with Vertical(id="help-dialog"):
            yield Label("Keyboard Shortcuts", id="help-title")
            yield Static(help_text)

    def action_close(self) -> None:
        self.dismiss(None)

    def on_key(self, event) -> None:
        self.dismiss(None)
```

**Step 2: Add help binding to dashboard.py**

Add to BINDINGS:

```python
        Binding("question_mark", "show_help", "Help"),
```

Add action:

```python
    def action_show_help(self) -> None:
        """Show help overlay."""
        from synthia.dashboard_screens import HelpScreen
        self.push_screen(HelpScreen())
```

**Step 3: Commit**

```bash
git add src/synthia/dashboard.py src/synthia/dashboard_screens.py
git commit -m "feat(dashboard): add help overlay"
```

---

## Task 19: Final Integration Test

**Files:**
- None (testing only)

**Step 1: Reinstall package**

Run: `cd /home/markmiddo/dev/misc/synthia && pip install -e .`

**Step 2: Test dashboard launches**

Run: `timeout 2 synthia-dash || true`
Expected: App launches (times out after 2s)

**Step 3: Verify all imports work**

Run:
```bash
python -c "
from synthia.dashboard import SynthiaDashboard
from synthia.dashboard_screens import EditAgentScreen, EditCommandScreen, HelpScreen
from synthia.config_manager import list_agents, list_commands, list_plugins, list_hooks
print('All imports OK')
print(f'Agents: {len(list_agents())}')
print(f'Commands: {len(list_commands())}')
print(f'Plugins: {len(list_plugins())}')
print(f'Hooks: {len(list_hooks())}')
"
```

Expected: All imports successful, counts printed

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat(dashboard): complete synthia-dash implementation

Unified TUI dashboard for Claude Code configuration:
- Memory section with category filters
- Agents section with edit/new/delete
- Commands section with edit/new/delete
- Plugins section with enable/disable toggle
- Hooks section listing
- Settings section listing
- Keyboard navigation (1-6, j/k, e/n/d)
- Help overlay (?)"
```

---

## Summary

| Task | Description | Files |
|------|-------------|-------|
| 1 | Config manager - settings | config_manager.py |
| 2 | Config manager - agents | config_manager.py |
| 3 | Config manager - commands | config_manager.py |
| 4 | Config manager - plugins | config_manager.py |
| 5 | Config manager - hooks | config_manager.py |
| 6 | Dashboard shell | dashboard.py |
| 7 | Entry point | pyproject.toml |
| 8 | Memory section widgets | dashboard.py |
| 9 | Memory section loading | dashboard.py |
| 10 | Agents section | dashboard.py |
| 11 | Plugins section | dashboard.py |
| 12 | Hooks section | dashboard.py |
| 13 | Settings section | dashboard.py |
| 14 | Commands section | dashboard.py |
| 15 | Edit modal screens | dashboard_screens.py |
| 16 | Edit/delete actions | dashboard.py |
| 17 | Detail panel | dashboard.py |
| 18 | Help overlay | dashboard_screens.py |
| 19 | Integration test | - |

Total: 19 tasks with ~19 commits
