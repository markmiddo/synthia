"""Brain configuration: ~/.config/synthia/brain.yaml plus environment secrets."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Mapping

import yaml

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path.home() / ".config" / "synthia" / "brain.yaml"
DEFAULT_STATE_DIR = Path.home() / ".local" / "share" / "synthia" / "brain"
DEFAULT_JOURNAL_DIR = (
    Path.home() / ".claude" / "projects" / "-home-markmiddo-dev-eventflo" / "memory" / "walk"
)

DEFAULT_PHRASE_HINTS = ["eventflo", "Eva", "Eva Core", "Barry", "FloSale", "Vishal", "Corey"]

DEFAULT_ALLOWED_TOOLS = [
    "Read",
    "Glob",
    "Grep",
    "Skill",
    "WebFetch",
    "WebSearch",
    "mcp__jobs__dispatch_job",
    "mcp__jobs__job_status",
    "mcp__jobs__list_jobs",
    "mcp__jobs__cancel_job",
]

# Workers are headless: nobody can answer a permission prompt, so anything not in this
# list is denied outright. Safety comes from the synced PreToolUse security-gate hook.
DEFAULT_WORKER_ALLOWED_TOOLS = [
    "Bash",
    "Read",
    "Write",
    "Edit",
    "Glob",
    "Grep",
    "Skill",
    "Task",
    "TodoWrite",
    "WebFetch",
    "WebSearch",
    "mcp__claude_ai_Gmail__*",
    "mcp__claude_ai_Google_Calendar__*",
    "mcp__claude_ai_Google_Drive__*",
    "mcp__claude_ai_Notion__*",
    "mcp__eva-core__*",
    "mcp__tavily__*",
]


@dataclass
class BrainConfig:
    cwd: Path = field(default_factory=lambda: Path.home() / "dev" / "eventflo")
    repos: list[Path] = field(default_factory=list)
    state_dir: Path = field(default_factory=lambda: DEFAULT_STATE_DIR)
    journal_dir: Path = field(default_factory=lambda: DEFAULT_JOURNAL_DIR)
    model: str | None = None
    allowed_tools: list[str] = field(default_factory=lambda: list(DEFAULT_ALLOWED_TOOLS))
    worker_allowed_tools: list[str] = field(
        default_factory=lambda: list(DEFAULT_WORKER_ALLOWED_TOOLS)
    )
    max_workers: int = 2
    job_timeout_s: int = 1800
    language: str = "en-AU"
    voice: str = "en-AU-Neural2-B"
    phrase_hints: list[str] = field(default_factory=lambda: list(DEFAULT_PHRASE_HINTS))
    telegram_token: str = ""
    telegram_allowed_users: list[int] = field(default_factory=list)
    telegram_chat_id: int | None = None
    confirm_timeout_s: int = 120


_PATH_FIELDS = {"cwd", "state_dir", "journal_dir"}
_PATH_LIST_FIELDS = {"repos"}
_INT_FIELDS = {"max_workers", "job_timeout_s", "confirm_timeout_s"}


def _coerce_int(key: str, value: Any, default: Any) -> Any:
    """Ints from YAML are frequently strings or typos; never crash the brain over one."""
    if isinstance(value, bool) or value is None:
        logger.warning("brain.yaml: %s must be a number, got %r; using %r", key, value, default)
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("brain.yaml: %s must be a number, got %r; using %r", key, value, default)
        return default


def _coerce_int_list(key: str, value: Any, default: list[int]) -> list[int]:
    if not isinstance(value, (list, tuple)):
        logger.warning("brain.yaml: %s must be a list, got %r; using %r", key, value, default)
        return list(default)
    out: list[int] = []
    for item in value:
        if isinstance(item, bool):
            logger.warning("brain.yaml: %s entry %r is not a number; using %r", key, item, default)
            return list(default)
        try:
            out.append(int(item))
        except (TypeError, ValueError):
            logger.warning("brain.yaml: %s entry %r is not a number; using %r", key, item, default)
            return list(default)
    return out


def load_brain_config(
    path: Path | None = None, env: Mapping[str, str] | None = None
) -> BrainConfig:
    """Load config from YAML, then overlay secrets from the environment."""
    path = path or DEFAULT_PATH
    env = os.environ if env is None else env
    raw: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path) as f:
                loaded = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("Could not read %s: %s; using defaults", path, exc)
            loaded = {}
        if isinstance(loaded, dict):
            raw = loaded
        else:
            logger.warning("%s is not a mapping; using defaults", path)

    defaults = BrainConfig()
    known = {f.name for f in fields(BrainConfig)}
    kwargs: dict[str, Any] = {}
    for key, value in raw.items():
        if key not in known:
            logger.warning("brain.yaml: unknown key %r ignored", key)
            continue
        if key in _PATH_FIELDS:
            kwargs[key] = Path(os.path.expanduser(str(value)))
        elif key in _PATH_LIST_FIELDS:
            kwargs[key] = [Path(os.path.expanduser(str(v))) for v in value]
        elif key in _INT_FIELDS:
            kwargs[key] = _coerce_int(key, value, getattr(defaults, key))
        elif key == "telegram_chat_id":
            kwargs[key] = None if value is None else _coerce_int(key, value, None)
        elif key == "telegram_allowed_users":
            kwargs[key] = _coerce_int_list(key, value, defaults.telegram_allowed_users)
        else:
            kwargs[key] = value

    cfg = BrainConfig(**kwargs)
    token = env.get("BRAIN_TELEGRAM_TOKEN")
    if token:
        cfg.telegram_token = token
    return cfg
