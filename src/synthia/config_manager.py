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
