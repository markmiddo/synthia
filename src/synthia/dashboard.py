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
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from textual import work
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical
    from textual.widgets import (
        Button,
        Footer,
        Header,
        Label,
        ListView,
        Static,
    )
except ImportError as _textual_err:
    raise ImportError(
        "textual is required for the dashboard. Install with: pip install synthia[tui]"
    ) from _textual_err

from synthia.config_manager import (
    AgentConfig,
    CommandConfig,
    HookConfig,
    PluginInfo,
    delete_agent,
    delete_command,
    list_agents,
    list_commands,
    list_hooks,
    list_plugins,
    save_agent,
    save_command,
    set_plugin_enabled,
)
from synthia.dashboard_screens import (
    ConfirmDeleteScreen,
    EditAgentScreen,
    EditCommandScreen,
    EditMemoryScreen,
    HelpScreen,
)
from synthia.memory import (
    MEMORY_CATEGORIES,
    MemoryEntry,
    get_memory_system,
)
from synthia.widgets import (
    AgentListItem,
    CommandListItem,
    HookListItem,
    MemoryListItem,
    PluginListItem,
    Section,
    SettingListItem,
    SidebarItem,
    WorktreeListItem,
)
from synthia.worktrees import WorktreeInfo, scan_worktrees


class SynthiaDashboard(App):
    """Unified TUI Dashboard for Claude Code configuration."""

    ENABLE_COMMAND_PALETTE = False

    CSS = """
    Screen {
        background: ansi_default;
    }

    #sidebar {
        width: 18;
        height: 100%;
        border: solid $primary;
        padding: 1;
        background: ansi_default;
    }

    #sidebar-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }

    #sidebar ListView {
        height: 1fr;
        background: ansi_default;
    }

    #sidebar ListItem {
        padding: 0 1;
        background: ansi_default;
    }

    #sidebar ListItem:hover {
        background: $primary 30%;
    }

    #main-content {
        width: 1fr;
        height: 100%;
        padding: 1;
        background: ansi_default;
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
        background: ansi_default;
    }

    #content-list {
        height: 1fr;
        border: solid $secondary;
        display: none;
        background: ansi_default;
    }

    #content-list.visible {
        display: block;
    }

    #status-bar {
        height: 1;
        color: $text;
        padding: 0 1;
        background: $surface;
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

    #memory-toolbar {
        display: none;
    }

    #memory-toolbar.visible {
        display: block;
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

    #detail-panel {
        height: 12;
        border: solid $accent;
        margin-top: 1;
        padding: 1;
        background: ansi_default;
    }

    Header {
        background: ansi_default;
    }

    Footer {
        background: $surface;
    }

    Static {
        background: ansi_default;
    }

    ListView {
        background: ansi_default;
    }

    ListItem {
        background: ansi_default;
    }

    ListItem.-highlight {
        background: $primary 30%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "goto_section('worktrees')", "Worktrees", show=False),
        Binding("w", "goto_section('worktrees')", "Worktrees", show=False),
        Binding("2", "goto_section('memory')", "Memory", show=False),
        Binding("3", "goto_section('agents')", "Agents", show=False),
        Binding("4", "goto_section('commands')", "Commands", show=False),
        Binding("5", "goto_section('plugins')", "Plugins", show=False),
        Binding("6", "goto_section('hooks')", "Hooks", show=False),
        Binding("7", "goto_section('settings')", "Settings", show=False),
        Binding("r", "refresh", "Refresh"),
        Binding("space", "toggle_plugin", "Toggle", show=False),
        Binding("e", "edit_selected", "Edit"),
        Binding("d", "delete_selected", "Delete"),
        Binding("n", "new_item", "New"),
        Binding("?", "show_help", "Help"),
        Binding("g", "open_github", "GitHub", show=False),
        Binding("o", "open_terminal", "Terminal", show=False),
        Binding("c", "resume_session", "Resume", show=False),
    ]

    TITLE = "Synthia Dashboard"

    def __init__(self) -> None:
        super().__init__()
        self.current_section: Section = Section.WORKTREES

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Label("Sections", id="sidebar-title")
                yield ListView(
                    SidebarItem(Section.WORKTREES, 1),
                    SidebarItem(Section.MEMORY, 2),
                    SidebarItem(Section.AGENTS, 3),
                    SidebarItem(Section.COMMANDS, 4),
                    SidebarItem(Section.PLUGINS, 5),
                    SidebarItem(Section.HOOKS, 6),
                    SidebarItem(Section.SETTINGS, 7),
                    id="sidebar-list",
                )
            with Vertical(id="main-content"):
                yield Label("Memory", id="content-title")
                with Horizontal(id="memory-toolbar", classes="toolbar"):
                    yield Button("All", id="mem-all", variant="primary")
                    yield Button("Bugs", id="mem-bugs")
                    yield Button("Patterns", id="mem-patterns")
                    yield Button("Arch", id="mem-arch")
                    yield Button("Gotchas", id="mem-gotchas")
                    yield Button("Stack", id="mem-stack")
                yield Static("Select a section from the sidebar", id="content-area")
                yield ListView(id="content-list")
                yield Static("Select an item to view details", id="detail-panel")
        yield Static("[1-7] Section | [r] Refresh | [q] Quit", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        """Initialize with Worktrees section."""
        self._switch_section(Section.WORKTREES)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar selection."""
        if isinstance(event.item, SidebarItem):
            self._switch_section(event.item.section)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Update detail panel when item is highlighted."""
        try:
            detail = self.query_one("#detail-panel", Static)
        except Exception:
            return

        if isinstance(event.item, AgentListItem):
            agent = event.item.agent
            detail.update(
                f"Name: {agent.name}\nModel: {agent.model}\nColor: {agent.color}\n\n{agent.description}"
            )
        elif isinstance(event.item, CommandListItem):
            cmd = event.item.command
            detail.update(f"Command: /{cmd.filename.replace('.md', '')}\n\n{cmd.description}")
        elif isinstance(event.item, PluginListItem):
            plugin = event.item.plugin
            status = "Enabled" if plugin.enabled else "Disabled"
            detail.update(
                f"Plugin: {plugin.display_name}\nVersion: {plugin.version}\nStatus: {status}"
            )
        elif isinstance(event.item, HookListItem):
            hook = event.item.hook
            detail.update(f"Event: {hook.event}\nCommand: {hook.command}\nTimeout: {hook.timeout}s")
        elif isinstance(event.item, SettingListItem):
            detail.update(f"Key: {event.item.key}\nValue: {event.item.value}")
        elif isinstance(event.item, MemoryListItem):
            entry = event.item.entry
            # Show memory entry details based on category
            if entry.category == "bug":
                detail.update(
                    f"Error: {entry.data.get('error', 'N/A')}\nFix: {entry.data.get('fix', 'N/A')}"
                )
            elif entry.category == "pattern":
                detail.update(
                    f"Topic: {entry.data.get('topic', 'N/A')}\nPattern: {entry.data.get('pattern', 'N/A')}"
                )
            else:
                detail.update(str(entry.data))
        elif isinstance(event.item, WorktreeListItem):
            wt = event.item.worktree
            lines = [f"Path: {wt.path}", f"Branch: {wt.branch}"]
            if wt.issue_number:
                lines.append(f"Issue: #{wt.issue_number}")
            if wt.session_summary:
                lines.append(f"Session: {wt.session_summary}")
            completed, total = wt.progress
            if total > 0:
                lines.append(f"\nTasks ({completed}/{total}):")
                for task in wt.tasks:
                    status = (
                        "✓"
                        if task.status == "completed"
                        else "○" if task.status == "pending" else "▶"
                    )
                    lines.append(f"  {status} {task.content[:50]}")
            detail.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses for memory filter."""
        button_id = event.button.id
        if button_id and button_id.startswith("mem-"):
            # Memory filter button
            category = button_id.replace("mem-", "")
            self._filter_memory(category)
            # Update button variants to show active filter
            for btn in self.query("#memory-toolbar Button"):
                btn.variant = "primary" if btn.id == button_id else "default"  # type: ignore[attr-defined]

    def _filter_memory(self, category: str) -> None:
        """Filter memory entries by category."""
        if category == "all":
            self._load_memory_all()
        elif category == "bugs":
            self._load_memory_category("bug")
        elif category == "patterns":
            self._load_memory_category("pattern")
        elif category == "arch":
            self._load_memory_category("arch")
        elif category == "gotchas":
            self._load_memory_category("gotcha")
        elif category == "stack":
            self._load_memory_category("stack")

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
        detail_panel = self.query_one("#detail-panel", Static)
        memory_toolbar = self.query_one("#memory-toolbar", Horizontal)

        # Clear detail panel when switching sections
        detail_panel.update("Select an item to view details")

        # Hide content-area, show content-list for all sections
        content_area.display = False
        content_list.add_class("visible")
        content_list.clear()

        # Show memory toolbar only for Memory section
        if section == Section.MEMORY:
            memory_toolbar.add_class("visible")
            self._show_memory_section()
        else:
            memory_toolbar.remove_class("visible")
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
            elif section == Section.WORKTREES:
                self._show_worktrees_section()

        self._set_status(f"Viewing {section.value.title()}")

    def _set_status(self, text: str) -> None:
        """Update status bar."""
        status = self.query_one("#status-bar", Static)
        status.update(f"{text} | [1-7] Section | [r] Refresh | [q] Quit")

    def _show_memory_section(self) -> None:
        """Show the memory section content."""
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
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for entry, line_num in entries:
                list_view.append(MemoryListItem(entry, line_num))
            self._set_status(f"Memory | {len(entries)} entries")
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
            if list_view.highlighted_child and isinstance(
                list_view.highlighted_child, PluginListItem
            ):
                plugin = list_view.highlighted_child.plugin
                new_state = not plugin.enabled
                set_plugin_enabled(plugin.name, new_state)
                self._load_plugins()  # Refresh
        except Exception as e:
            logger.debug("toggle_plugin error: %s", e)

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
            k: v for k, v in settings.items() if k not in ("hooks", "enabledPlugins")
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

    def _show_worktrees_section(self) -> None:
        """Show the worktrees section content."""
        self._load_worktrees()

    @work(thread=True)
    def _load_worktrees(self) -> None:
        """Load all worktrees."""
        worktrees = scan_worktrees()
        self.call_from_thread(self._display_worktrees, worktrees)

    def _display_worktrees(self, worktrees: list[WorktreeInfo]) -> None:
        """Display worktrees in list."""
        self._worktrees = worktrees
        try:
            list_view = self.query_one("#content-list", ListView)
            list_view.clear()
            for wt in worktrees:
                list_view.append(WorktreeListItem(wt))
            self._set_status(
                f"Worktrees | {len(worktrees)} found | [c] Resume [g] GitHub [o] Path [d] Delete"
            )
        except Exception:
            pass

    def action_edit_selected(self) -> None:
        """Edit the selected item."""
        if self.current_section == Section.MEMORY:
            self._edit_selected_memory()
        elif self.current_section == Section.AGENTS:
            self._edit_selected_agent()
        elif self.current_section == Section.COMMANDS:
            self._edit_selected_command()

    def _edit_selected_agent(self) -> None:
        """Edit selected agent."""
        if not hasattr(self, "_agents") or not self._agents:
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
        if not hasattr(self, "_commands") or not self._commands:
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

    def _edit_selected_memory(self) -> None:
        """Edit selected memory entry."""
        if not hasattr(self, "_memory_entries") or not self._memory_entries:
            self._set_status("No memory entry selected")
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._memory_entries):
                entry, line_num = self._memory_entries[index]
                self.push_screen(EditMemoryScreen(entry, line_num), self._on_memory_edit_complete)
        except Exception:
            pass

    def _on_memory_edit_complete(self, result: Optional[dict]) -> None:
        """Handle memory edit completion."""
        if result:
            self._save_memory_edit(result)

    def _save_memory_edit(self, result: dict) -> None:
        """Save the edited memory entry."""
        category = result["category"]
        line_number = result["line_number"]
        new_data = result["data"]
        new_tags = result["tags"]

        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES[category]

        # Read all lines
        with open(filepath, "r") as f:
            lines = f.readlines()

        # Update the specific line
        if 0 <= line_number < len(lines):
            entry = MemoryEntry(category=category, data=new_data, tags=new_tags)
            lines[line_number] = json.dumps(entry.to_dict()) + "\n"

            # Write back
            with open(filepath, "w") as f:
                f.writelines(lines)

            self._set_status(f"Saved {category} entry")
            self._load_memory_all()  # Refresh
        else:
            self._set_status("Error: Could not save (line number mismatch)")

    def action_new_item(self) -> None:
        """Create a new item in current section."""
        if self.current_section == Section.AGENTS:
            self.push_screen(EditAgentScreen(None), self._on_agent_edit_complete)
        elif self.current_section == Section.COMMANDS:
            self.push_screen(EditCommandScreen(None), self._on_command_edit_complete)

    def action_delete_selected(self) -> None:
        """Delete the selected item."""
        if self.current_section == Section.MEMORY:
            self._delete_selected_memory()
        elif self.current_section == Section.AGENTS:
            self._delete_selected_agent()
        elif self.current_section == Section.COMMANDS:
            self._delete_selected_command()
        elif self.current_section == Section.WORKTREES:
            self._delete_selected_worktree()

    def _delete_selected_agent(self) -> None:
        """Delete selected agent."""
        if not hasattr(self, "_agents") or not self._agents:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._agents):
                agent = self._agents[index]
                self.push_screen(
                    ConfirmDeleteScreen(agent.name),
                    lambda confirmed: self._do_delete_agent(agent.filename) if confirmed else None,
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
        if not hasattr(self, "_commands") or not self._commands:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._commands):
                cmd = self._commands[index]
                name = cmd.filename.replace(".md", "")
                self.push_screen(
                    ConfirmDeleteScreen(f"/{name}"),
                    lambda confirmed: self._do_delete_command(cmd.filename) if confirmed else None,
                )
        except Exception:
            pass

    def _do_delete_command(self, filename: str) -> None:
        """Actually delete the command."""
        delete_command(filename)
        self._load_commands()
        self._set_status("Command deleted")

    def _delete_selected_memory(self) -> None:
        """Delete selected memory entry."""
        if not hasattr(self, "_memory_entries") or not self._memory_entries:
            self._set_status("No memory entry selected")
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._memory_entries):
                entry, line_num = self._memory_entries[index]
                # Store for callback
                self._pending_memory_delete = (entry.category, line_num)
                self.push_screen(
                    ConfirmDeleteScreen(f"{entry.category.upper()} entry"),
                    self._on_memory_delete_confirm,  # type: ignore[arg-type]
                )
        except Exception:
            pass

    def _on_memory_delete_confirm(self, confirmed: bool) -> None:
        """Callback when memory delete confirmation is dismissed."""
        pending = getattr(self, "_pending_memory_delete", None)
        if confirmed and pending is not None:
            category, line_num = pending
            self._do_delete_memory(category, line_num)
        self._pending_memory_delete = None  # type: ignore[assignment]

    def _do_delete_memory(self, category: str, line_number: int) -> None:
        """Actually delete the memory entry."""
        mem = get_memory_system()
        filepath = mem.memory_dir / MEMORY_CATEGORIES[category]

        with open(filepath, "r") as f:
            lines = f.readlines()

        if 0 <= line_number < len(lines):
            del lines[line_number]

            with open(filepath, "w") as f:
                f.writelines(lines)

            self._set_status(f"Deleted {category} entry")
            self._load_memory_all()  # Refresh
        else:
            self._set_status("Error: Could not delete")

    def action_show_help(self) -> None:
        """Show help overlay."""
        self.push_screen(HelpScreen())

    def action_open_github(self) -> None:
        """Open GitHub issue for selected worktree."""
        if self.current_section != Section.WORKTREES:
            return
        if not hasattr(self, "_worktrees") or not self._worktrees:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._worktrees):
                wt = self._worktrees[index]
                if wt.issue_number:
                    import subprocess

                    subprocess.Popen(["gh", "issue", "view", str(wt.issue_number), "--web"])
                    self._set_status(f"Opening issue #{wt.issue_number} in browser...")
                else:
                    self._set_status("No issue linked to this worktree")
        except Exception:
            pass

    def action_open_terminal(self) -> None:
        """Open terminal at worktree path."""
        if self.current_section != Section.WORKTREES:
            return
        if not hasattr(self, "_worktrees") or not self._worktrees:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._worktrees):
                wt = self._worktrees[index]
                # Show path in status - user can cd to it
                self._set_status(f"Path: {wt.path}")
        except Exception:
            pass

    def action_resume_session(self) -> None:
        """Resume Claude session in selected worktree."""
        if self.current_section != Section.WORKTREES:
            return
        if not hasattr(self, "_worktrees") or not self._worktrees:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._worktrees):
                wt = self._worktrees[index]
                import subprocess

                # Open new pane below (synthia stays on top) and start claude session
                subprocess.Popen(
                    [
                        "flatpak",
                        "run",
                        "org.wezfurlong.wezterm",
                        "cli",
                        "split-pane",
                        "--bottom",
                        "--percent",
                        "50",
                        "--",
                        "bash",
                        "-c",
                        f"cd {wt.path} && claude --dangerously-skip-permissions",
                    ]
                )
                self._set_status(f"Opening Claude in {Path(wt.path).name}...")
        except Exception:
            pass

    def _delete_selected_worktree(self) -> None:
        """Delete selected worktree."""
        if not hasattr(self, "_worktrees") or not self._worktrees:
            return
        try:
            list_view = self.query_one("#content-list", ListView)
            index = list_view.index
            if index is not None and 0 <= index < len(self._worktrees):
                wt = self._worktrees[index]
                short_name = Path(wt.path).name
                self.push_screen(
                    ConfirmDeleteScreen(f"worktree '{short_name}'"),
                    lambda confirmed: self._do_delete_worktree(wt.path) if confirmed else None,
                )
        except Exception:
            pass

    def _do_delete_worktree(self, path: str) -> None:
        """Actually delete the worktree."""
        import subprocess

        try:
            subprocess.run(["git", "worktree", "remove", path], check=True)
            self._set_status("Worktree deleted")
            self._load_worktrees()  # Refresh
        except subprocess.CalledProcessError:
            self._set_status("Error: Could not delete worktree")


def main() -> None:
    """Run the Synthia Dashboard."""
    app = SynthiaDashboard()
    app.run()


if __name__ == "__main__":
    main()
