"""Widget classes for the Synthia Dashboard."""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    Input,
    Label,
    ListItem,
    ListView,
    Static,
)

from synthia.config_manager import (
    AgentConfig,
    CommandConfig,
    HookConfig,
    PluginInfo,
)
from synthia.memory import MemoryEntry
from synthia.worktrees import WorktreeInfo


class Section(Enum):
    """Dashboard sections."""

    WORKTREES = "worktrees"
    MEMORY = "memory"
    AGENTS = "agents"
    COMMANDS = "commands"
    PLUGINS = "plugins"
    HOOKS = "hooks"
    SETTINGS = "settings"


class SidebarItem(ListItem):
    """Sidebar navigation item."""

    def __init__(self, section: Section, index: int) -> None:
        super().__init__()
        self.section = section
        self.index = index

    def compose(self) -> ComposeResult:
        label = f"{self.index}. {self.section.value.title()}"
        yield Label(label)


class MemoryListItem(ListItem):
    """List item for memory entries."""

    def __init__(self, entry: MemoryEntry, line_number: int) -> None:
        super().__init__()
        self.entry = entry
        self.line_number = line_number

    def compose(self) -> ComposeResult:
        cat = self.entry.category.upper()
        if self.entry.category == "bug":
            content = self.entry.data.get("error", "N/A")[:50]
        elif self.entry.category == "pattern":
            content = self.entry.data.get("topic", "N/A")[:50]
        elif self.entry.category == "arch":
            content = self.entry.data.get("decision", "N/A")[:50]
        elif self.entry.category == "gotcha":
            content = self.entry.data.get("area", "N/A")[:50]
        elif self.entry.category == "stack":
            content = self.entry.data.get("tool", "N/A")[:50]
        else:
            content = "Unknown"
        text = f"[{cat}] {content}"
        yield Label(text, markup=False)


class MemorySectionContent(Vertical):
    """Content widget for Memory section."""

    def __init__(self) -> None:
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

    def __init__(self, agent: AgentConfig) -> None:
        super().__init__()
        self.agent = agent

    def compose(self) -> ComposeResult:
        text = f"[{self.agent.model.upper()}] {self.agent.name}"
        yield Label(text, markup=False)


class PluginListItem(ListItem):
    """List item for plugin entries."""

    def __init__(self, plugin: PluginInfo) -> None:
        super().__init__()
        self.plugin = plugin

    def compose(self) -> ComposeResult:
        status = "✓" if self.plugin.enabled else "✗"
        text = f"[{status}] {self.plugin.display_name} ({self.plugin.version})"
        yield Label(text, markup=False)


class HookListItem(ListItem):
    """List item for hook entries."""

    def __init__(self, hook: HookConfig) -> None:
        super().__init__()
        self.hook = hook

    def compose(self) -> ComposeResult:
        # Show event type and truncated command
        cmd_short = self.hook.command[-40:] if len(self.hook.command) > 40 else self.hook.command
        text = f"[{self.hook.event}] {cmd_short}"
        yield Label(text, markup=False)


class CommandListItem(ListItem):
    """List item for command entries."""

    def __init__(self, command: CommandConfig) -> None:
        super().__init__()
        self.command = command

    def compose(self) -> ComposeResult:
        # Show filename (without .md) and description preview
        name = self.command.filename.replace(".md", "")
        desc = self.command.description[:40] if self.command.description else "No description"
        text = f"/{name} - {desc}"
        yield Label(text)


class SettingListItem(ListItem):
    """List item for settings entries."""

    def __init__(self, key: str, value: Any) -> None:
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


class WorktreeListItem(ListItem):
    """List item for worktree entries."""

    def __init__(self, worktree: WorktreeInfo, expanded: bool = False) -> None:
        super().__init__()
        self.worktree = worktree
        self.expanded = expanded

    def compose(self) -> ComposeResult:
        # Get progress
        completed, total = self.worktree.progress
        if total > 0:
            # Create progress bar: ████░░░░ 4/5
            filled = int((completed / total) * 8)
            progress_bar = "█" * filled + "░" * (8 - filled)
            progress_str = f"{progress_bar} {completed}/{total}"
        else:
            progress_str = "No tasks"

        # Get issue display
        issue_str = f"#{self.worktree.issue_number}" if self.worktree.issue_number else ""

        # Get short path (just the worktree folder name)
        short_path = Path(self.worktree.path).name

        if self.expanded:
            # Full details
            lines = [f"📁 {short_path}"]
            lines.append(f"   Branch: {self.worktree.branch}")
            if self.worktree.issue_number:
                lines.append(f"   Issue: #{self.worktree.issue_number}")
            if self.worktree.session_summary:
                lines.append(f'   Session: "{self.worktree.session_summary[:40]}..."')
            lines.append(f"   Tasks: {progress_str}")
            text = "\n".join(lines)
        else:
            # Collapsed: 📁 issue-295  ████░░░░ 4/5  #295
            text = f"📁 {short_path}  {progress_str}  {issue_str}"

        yield Label(text, markup=False)
