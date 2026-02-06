"""Memory system for Synthia - persistent knowledge storage and retrieval.

This module provides a tag-based JSONL memory system for storing:
- Bugs: Error → cause → fix mappings
- Patterns: Coding conventions and "how we do X"
- Architecture: Why we built things this way
- Gotchas: Project-specific landmines
- Stack: Tool/config quirks and reference
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default memory location (can be overridden in config)
DEFAULT_MEMORY_DIR = Path.home() / ".claude" / "memory"

# Memory categories and their file names
MEMORY_CATEGORIES = {
    "bug": "bugs.jsonl",
    "pattern": "patterns.jsonl",
    "arch": "architecture.jsonl",
    "gotcha": "gotchas.jsonl",
    "stack": "stack.jsonl",
}


@dataclass
class MemoryEntry:
    """A single memory entry."""

    category: str
    data: Dict[str, Any]
    tags: List[str] = field(default_factory=list)
    date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m"))

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        result = self.data.copy()
        result["tags"] = self.tags
        result["date"] = self.date
        return result

    @classmethod
    def from_dict(cls, category: str, data: Dict[str, Any]) -> "MemoryEntry":
        """Create from dictionary loaded from JSONL."""
        tags = data.pop("tags", [])
        date = data.pop("date", "")
        return cls(category=category, data=data, tags=tags, date=date)

    def format_display(self) -> str:
        """Format entry for display."""
        lines = []

        if self.category == "bug":
            lines.append(f"[BUG] {self.data.get('error', 'N/A')}")
            lines.append(f"  Cause: {self.data.get('cause', 'N/A')}")
            lines.append(f"  Fix: {self.data.get('fix', 'N/A')}")
        elif self.category == "pattern":
            lines.append(f"[PATTERN] {self.data.get('topic', 'N/A')}")
            lines.append(f"  Rule: {self.data.get('rule', 'N/A')}")
            lines.append(f"  Why: {self.data.get('why', 'N/A')}")
        elif self.category == "arch":
            lines.append(f"[ARCHITECTURE] {self.data.get('decision', 'N/A')}")
            lines.append(f"  Why: {self.data.get('why', 'N/A')}")
        elif self.category == "gotcha":
            lines.append(f"[GOTCHA] {self.data.get('area', 'N/A')}")
            lines.append(f"  {self.data.get('gotcha', 'N/A')}")
        elif self.category == "stack":
            lines.append(f"[STACK] {self.data.get('tool', 'N/A')}")
            lines.append(f"  {self.data.get('note', 'N/A')}")
        else:
            lines.append(f"[{self.category.upper()}] {self.data}")

        lines.append(f"  Tags: {', '.join(self.tags)}")
        return "\n".join(lines)


class MemorySystem:
    """Manages persistent memory storage and retrieval."""

    def __init__(self, memory_dir: Optional[Path] = None):
        """Initialize memory system.

        Args:
            memory_dir: Directory containing JSONL memory files.
                       Defaults to ~/.claude/memory/
        """
        self.memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        self._ensure_memory_dir()

    def _ensure_memory_dir(self):
        """Ensure memory directory and files exist."""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # Create empty files if they don't exist
        for filename in MEMORY_CATEGORIES.values():
            filepath = self.memory_dir / filename
            if not filepath.exists():
                filepath.touch()

    def _get_category_from_filename(self, filename: str) -> str:
        """Get category name from filename."""
        for cat, fname in MEMORY_CATEGORIES.items():
            if fname == filename:
                return cat
        return "unknown"

    def recall(
        self,
        tags: List[str],
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[MemoryEntry]:
        """Retrieve memories matching any of the given tags.

        Args:
            tags: List of tags to search for (OR logic)
            category: Optional category to limit search (bug, pattern, arch, gotcha, stack)
            limit: Maximum number of results to return

        Returns:
            List of matching MemoryEntry objects
        """
        results = []
        tags_lower = [t.lower() for t in tags]

        # Determine which files to search
        if category:
            if category not in MEMORY_CATEGORIES:
                logger.warning("Unknown category: %s", category)
                return []
            files = [self.memory_dir / MEMORY_CATEGORIES[category]]
        else:
            files = [self.memory_dir / fname for fname in MEMORY_CATEGORIES.values()]

        # Search each file
        for filepath in files:
            if not filepath.exists():
                continue

            cat = self._get_category_from_filename(filepath.name)

            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        entry_tags = [t.lower() for t in data.get("tags", [])]

                        # Check if any search tag matches any entry tag
                        if any(tag in entry_tags for tag in tags_lower):
                            entry = MemoryEntry.from_dict(cat, data)
                            results.append(entry)

                            if len(results) >= limit:
                                return results
                    except json.JSONDecodeError:
                        continue

        return results

    def remember(
        self,
        category: str,
        tags: List[str],
        **data,
    ) -> bool:
        """Add a new memory entry.

        Args:
            category: One of: bug, pattern, arch, gotcha, stack
            tags: List of tags for retrieval
            **data: Category-specific data fields

        Category-specific required fields:
            bug: error, cause, fix
            pattern: topic, rule, why
            arch: decision, why
            gotcha: area, gotcha
            stack: tool, note

        Returns:
            True if successful, False otherwise
        """
        if category not in MEMORY_CATEGORIES:
            logger.warning("Unknown category: %s", category)
            logger.warning("Valid categories: %s", ", ".join(MEMORY_CATEGORIES.keys()))
            return False

        # Validate required fields
        required_fields = {
            "bug": ["error", "cause", "fix"],
            "pattern": ["topic", "rule", "why"],
            "arch": ["decision", "why"],
            "gotcha": ["area", "gotcha"],
            "stack": ["tool", "note"],
        }

        missing = [f for f in required_fields[category] if f not in data]
        if missing:
            logger.warning("Missing required fields for %s: %s", category, ", ".join(missing))
            return False

        # Create entry
        entry = MemoryEntry(category=category, data=data, tags=tags)

        # Append to file
        filepath = self.memory_dir / MEMORY_CATEGORIES[category]
        with open(filepath, "a") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")

        logger.info("Added %s entry with tags: %s", category, ", ".join(tags))
        return True

    def list_categories(self) -> Dict[str, int]:
        """List all categories with entry counts."""
        counts = {}
        for cat, filename in MEMORY_CATEGORIES.items():
            filepath = self.memory_dir / filename
            if filepath.exists():
                with open(filepath, "r") as f:
                    counts[cat] = sum(1 for line in f if line.strip())
            else:
                counts[cat] = 0
        return counts

    def list_all_tags(self) -> Dict[str, int]:
        """List all unique tags with usage counts."""
        tag_counts: Dict[str, int] = {}

        for filename in MEMORY_CATEGORIES.values():
            filepath = self.memory_dir / filename
            if not filepath.exists():
                continue

            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        for tag in data.get("tags", []):
                            tag_counts[tag] = tag_counts.get(tag, 0) + 1
                    except json.JSONDecodeError:
                        continue

        return dict(sorted(tag_counts.items(), key=lambda x: -x[1]))

    def search_text(self, query: str, limit: int = 20) -> List[MemoryEntry]:
        """Full-text search across all memory entries.

        Args:
            query: Text to search for (case-insensitive)
            limit: Maximum results to return

        Returns:
            List of matching entries
        """
        results = []
        query_lower = query.lower()

        for filename in MEMORY_CATEGORIES.values():
            filepath = self.memory_dir / filename
            if not filepath.exists():
                continue

            cat = self._get_category_from_filename(filepath.name)

            with open(filepath, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    if query_lower in line.lower():
                        try:
                            data = json.loads(line)
                            entry = MemoryEntry.from_dict(cat, data)
                            results.append(entry)

                            if len(results) >= limit:
                                return results
                        except json.JSONDecodeError:
                            continue

        return results

    def get_context_for_task(self, task_description: str) -> str:
        """Extract relevant memories for a given task description.

        This is used for auto-retrieval in Dev Mode - it extracts keywords
        from the task and returns relevant memories as context.

        Args:
            task_description: Description of the current task

        Returns:
            Formatted string of relevant memories
        """
        # Extract potential tags from task description
        keywords = self._extract_keywords(task_description)

        if not keywords:
            return ""

        # Search for memories
        entries = self.recall(tags=keywords, limit=10)

        if not entries:
            return ""

        # Format for injection
        lines = ["=== Relevant Memory Context ===", ""]
        for entry in entries:
            lines.append(entry.format_display())
            lines.append("")

        lines.append("=== End Memory Context ===")
        return "\n".join(lines)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract potential tag keywords from text."""
        # Common technology/project terms that might be tags
        known_tags = {
            "frontend",
            "backend",
            "react",
            "typescript",
            "golang",
            "go",
            "mongodb",
            "aws",
            "api",
            "auth",
            "stripe",
            "payments",
            "deployment",
            "testing",
            "vitest",
            "playwright",
            "git",
            "docker",
            "ecs",
            "amplify",
            "vite",
            "eventflo",
            "fan-experience",
            "organizer-platform",
            "organizer-backend",
        }

        text_lower = text.lower()
        found = []

        for tag in known_tags:
            if tag in text_lower:
                found.append(tag)

        return found


# Singleton instance for easy access
_memory_system: Optional[MemorySystem] = None


def get_memory_system(memory_dir: Optional[Path] = None) -> MemorySystem:
    """Get or create the memory system singleton."""
    global _memory_system
    if _memory_system is None:
        _memory_system = MemorySystem(memory_dir)
    return _memory_system


# Convenience functions
def recall(tags: List[str], category: Optional[str] = None) -> List[MemoryEntry]:
    """Recall memories by tags."""
    return get_memory_system().recall(tags, category)


def remember(category: str, tags: List[str], **data) -> bool:
    """Remember a new entry."""
    return get_memory_system().remember(category, tags, **data)


def search(query: str) -> List[MemoryEntry]:
    """Search memories by text."""
    return get_memory_system().search_text(query)
