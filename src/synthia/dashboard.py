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

import json
from enum import Enum
from typing import Optional

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, TextArea

from synthia.memory import (
    MEMORY_CATEGORIES,
    MemoryEntry,
    get_memory_system,
)
from synthia.config_manager import (
    AgentConfig,
    list_agents,
    load_agent,
    save_agent,
    delete_agent,
)


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


class AgentListItem(ListItem):
    """List item for agent entries."""

    def __init__(self, agent: AgentConfig):
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        text = f"[{self.agent.model.upper()}] {self.agent.name}"
        yield Label(text)


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

        if section == Section.MEMORY:
            self._show_memory_section()
        elif section == Section.AGENTS:
            self._show_agents_section()
        else:
            content = self.query_one("#content-area", Static)
            content.update(f"[{section.value.upper()}] Content will appear here")

        self._set_status(f"Viewing {section.value.title()}")

    def _set_status(self, text: str) -> None:
        """Update status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(f"{text} | [1-6] Section | [r] Refresh | [q] Quit")

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


def main():
    """Run the Synthia Dashboard."""
    app = SynthiaDashboard()
    app.run()


if __name__ == "__main__":
    main()
