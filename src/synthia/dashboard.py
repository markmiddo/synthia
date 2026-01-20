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
from typing import Any, Optional

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
    PluginInfo,
    list_plugins,
    set_plugin_enabled,
    HookConfig,
    list_hooks,
    CommandConfig,
    list_commands,
    save_command,
    delete_command,
)
from synthia.dashboard_screens import (
    ConfirmDeleteScreen,
    EditAgentScreen,
    EditCommandScreen,
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


class PluginListItem(ListItem):
    """List item for plugin entries."""

    def __init__(self, plugin: PluginInfo):
        super().__init__()
        self.plugin = plugin

    def compose(self) -> ComposeResult:
        status = "✓" if self.plugin.enabled else "✗"
        text = f"[{status}] {self.plugin.display_name} ({self.plugin.version})"
        yield Label(text)


class HookListItem(ListItem):
    """List item for hook entries."""

    def __init__(self, hook: HookConfig):
        super().__init__()
        self.hook = hook

    def compose(self) -> ComposeResult:
        # Show event type and truncated command
        cmd_short = self.hook.command[-40:] if len(self.hook.command) > 40 else self.hook.command
        text = f"[{self.hook.event}] {cmd_short}"
        yield Label(text)


class CommandListItem(ListItem):
    """List item for command entries."""

    def __init__(self, command: CommandConfig):
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        # Show filename (without .md) and description preview
        name = self.command.filename.replace('.md', '')
        desc = self.command.description[:40] if self.command.description else "No description"
        text = f"/{name} - {desc}"
        yield Label(text)


class SettingListItem(ListItem):
    """List item for settings entries."""

    def __init__(self, key: str, value: Any):
        super().__init__()
        self.key = key
        self.value = value

    def compose(self) -> ComposeResult:
        # Format value display
        if isinstance(self.value, bool):
            val_str = "✓" if self.value else "✗"
        elif isinstance(self.value, dict):
            val_str = "{...}"
        elif isinstance(self.value, list):
            val_str = f"[{len(self.value)} items]"
        else:
            val_str = str(self.value)[:30]
        text = f"{self.key}: {val_str}"
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

    #content-list {
        height: 1fr;
        border: solid $secondary;
        display: none;
    }

    #content-list.visible {
        display: block;
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
        Binding("space", "toggle_plugin", "Toggle", show=False),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("n", "new_item", "New"),
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
                yield ListView(id="content-list")
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

        # Get content widgets
        content_area = self.query_one("#content-area", Static)
        content_list = self.query_one("#content-list", ListView)

        # Memory uses its own widgets, others use content-list
        if section == Section.MEMORY:
            content_area.display = True
            content_list.remove_class("visible")
            self._show_memory_section()
        elif section in (Section.AGENTS, Section.PLUGINS, Section.COMMANDS, Section.HOOKS, Section.SETTINGS):
            content_area.display = False
            content_list.add_class("visible")
            content_list.clear()
            if section == Section.AGENTS:
                self._show_agents_section()
            elif section == Section.PLUGINS:
                self._show_plugins_section()
            elif section == Section.COMMANDS:
                self._show_commands_section()
            elif section == Section.HOOKS:
                self._show_hooks_section()
            elif section == Section.SETTINGS:
                self._show_settings_section()
            else:
                self._set_status(f"{section.value.title()} | Coming soon")

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
            self._set_status(f"Plugins | {len(plugins)} found | [Space] Toggle")
        except Exception:
            pass

    def action_toggle_plugin(self) -> None:
        """Toggle selected plugin enabled/disabled."""
        if self.current_section != Section.PLUGINS:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            if list_view.highlighted_child and isinstance(list_view.highlighted_child, PluginListItem):
                plugin = list_view.highlighted_child.plugin
                new_state = not plugin.enabled
                set_plugin_enabled(plugin.name, new_state)
                self._load_plugins()  # Refresh
        except Exception:
            pass

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
            for command in commands:
                list_view.append(CommandListItem(command))
            self._set_status(f"Commands | {len(commands)} found")
        except Exception:
            pass

    def _show_settings_section(self) -> None:
        """Show settings section."""
        self._load_settings()

    @work(thread=True)
    def _load_settings(self) -> None:
        """Load settings."""
        from synthia.config_manager import load_settings
        settings = load_settings()
        # Filter out complex nested objects for display
        display_settings = {
            k: v for k, v in settings.items()
            if k not in ("hooks", "enabledPlugins")
        }
        self.call_from_thread(self._display_settings, display_settings)

    def _display_settings(self, settings: dict) -> None:
        """Display settings in list."""
        self._settings = settings
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for key, value in sorted(settings.items()):
                list_view.append(SettingListItem(key, value))
            self._set_status(f"Settings | {len(settings)} items")
        except Exception:
            pass

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
            save_command(result)
            self._load_commands()
            self._set_status(f"Saved command: {result.filename}")

    def action_new_item(self) -> None:
        """Create a new item in current section."""
        if self.current_section == Section.AGENTS:
            self.push_screen(EditAgentScreen(None), self._on_agent_edit_complete)
        elif self.current_section == Section.COMMANDS:
            self.push_screen(EditCommandScreen(None), self._on_command_edit_complete)

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
        delete_command(filename)
        self._load_commands()
        self._set_status("Command deleted")


def main():
    """Run the Synthia Dashboard."""
    app = SynthiaDashboard()
    app.run()


if __name__ == "__main__":
    main()
