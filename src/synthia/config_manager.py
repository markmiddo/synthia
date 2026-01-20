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