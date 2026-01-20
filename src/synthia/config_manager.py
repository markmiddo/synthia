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