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
