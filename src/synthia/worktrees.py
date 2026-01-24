"""Worktree scanner for Synthia Dashboard.

Scans git worktrees and their associated Claude Code sessions.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class WorktreeTask:
    """Represents a task from a Claude Code session."""

    content: str
    status: str  # "pending", "in_progress", "completed"
    active_form: str


@dataclass
class WorktreeInfo:
    """Information about a git worktree and its associated Claude Code session."""

    path: str
    branch: str
    issue_number: Optional[int] = None
    issue_title: Optional[str] = None
    session_id: Optional[str] = None
    session_summary: Optional[str] = None
    tasks: list[WorktreeTask] = field(default_factory=list)

    @property
    def progress(self) -> tuple[int, int]:
        """Return (completed, total) task counts."""
        completed = sum(1 for t in self.tasks if t.status == "completed")
        return (completed, len(self.tasks))


# Patterns for extracting issue numbers from branch names
ISSUE_PATTERNS = [
    r"feature/(\d+)-",  # feature/295-flosale-mobile
    r"issue-(\d+)-",  # issue-295-manage-order
    r"fix/(\d+)-",  # fix/301-bug-name
    r"bugfix/(\d+)-",  # bugfix/301-bug-name
    r"hotfix/(\d+)-",  # hotfix/301-urgent-fix
    r"(\d+)-",  # 295-flosale-mobile (fallback)
]


def extract_issue_number(branch: str) -> Optional[int]:
    """Extract issue number from branch name.

    Supports various branch naming conventions:
    - feature/295-flosale-mobile
    - issue-295-manage-order
    - fix/301-bug-name
    - bugfix/301-bug-name
    - hotfix/301-urgent-fix
    - 295-flosale-mobile

    Args:
        branch: The branch name to parse

    Returns:
        The issue number if found, None otherwise
    """
    for pattern in ISSUE_PATTERNS:
        match = re.search(pattern, branch)
        if match:
            return int(match.group(1))
    return None


def _parse_worktree_list(output: str) -> list[dict[str, str]]:
    """Parse git worktree list --porcelain output.

    Format:
        worktree /path/to/worktree
        HEAD abc123...
        branch refs/heads/feature/295-name

        worktree /path/to/another
        HEAD def456...
        branch refs/heads/main

    Args:
        output: Raw output from git worktree list --porcelain

    Returns:
        List of dicts with 'path' and 'branch' keys
    """
    worktrees = []
    current: dict[str, str] = {}

    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            if current.get("path") and current.get("branch"):
                worktrees.append(current)
            current = {}
            continue

        if line.startswith("worktree "):
            current["path"] = line[9:]  # Remove "worktree " prefix
        elif line.startswith("branch "):
            # Remove "branch refs/heads/" prefix
            branch = line[7:]  # Remove "branch " prefix
            if branch.startswith("refs/heads/"):
                branch = branch[11:]  # Remove "refs/heads/" prefix
            current["branch"] = branch
        # HEAD lines are ignored for now

    # Don't forget the last entry
    if current.get("path") and current.get("branch"):
        worktrees.append(current)

    return worktrees


def _find_session_for_path(project_path: str) -> Optional[dict]:
    """Find Claude Code session matching a project path.

    Searches through ~/.claude/projects/*/sessions-index.json files.

    Args:
        project_path: Absolute path to the project/worktree

    Returns:
        Session entry dict if found, None otherwise
    """
    claude_dir = Path.home() / ".claude" / "projects"

    if not claude_dir.exists():
        return None

    # Normalize the project path for comparison
    normalized_path = str(Path(project_path).resolve())

    try:
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue

            index_file = project_dir / "sessions-index.json"
            if not index_file.exists():
                continue

            try:
                with open(index_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                entries = data.get("entries", [])
                for entry in entries:
                    entry_path = entry.get("projectPath", "")
                    # Normalize for comparison
                    if str(Path(entry_path).resolve()) == normalized_path:
                        return entry
            except (json.JSONDecodeError, IOError):
                continue

    except OSError:
        return None

    return None


def _load_tasks_for_session(session_id: str) -> list[WorktreeTask]:
    """Load tasks from Claude Code todo files for a session.

    Tasks are stored in ~/.claude/todos/{sessionId}-agent-*.json

    Args:
        session_id: The Claude Code session ID

    Returns:
        List of WorktreeTask objects
    """
    todos_dir = Path.home() / ".claude" / "todos"

    if not todos_dir.exists():
        return []

    tasks = []
    pattern = f"{session_id}-agent-*.json"

    try:
        for todo_file in todos_dir.glob(pattern):
            try:
                with open(todo_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Handle both list format and object format
                if isinstance(data, list):
                    task_list = data
                elif isinstance(data, dict):
                    task_list = data.get("tasks", [])
                else:
                    continue

                for task_data in task_list:
                    if isinstance(task_data, dict):
                        task = WorktreeTask(
                            content=task_data.get("content", task_data.get("subject", "")),
                            status=task_data.get("status", "pending"),
                            active_form=task_data.get("activeForm", task_data.get("active_form", "")),
                        )
                        tasks.append(task)

            except (json.JSONDecodeError, IOError):
                continue

    except OSError:
        return []

    return tasks


def scan_worktrees() -> list[WorktreeInfo]:
    """Scan for git worktrees and their associated Claude Code sessions.

    This function:
    1. Runs `git worktree list --porcelain` to get all worktrees
    2. For each worktree:
       - Extracts the branch name
       - Extracts issue number from branch name using regex patterns
       - Finds matching Claude Code session in sessions-index.json
       - Loads tasks from todo files

    Returns:
        List of WorktreeInfo objects with session and task data
    """
    worktrees: list[WorktreeInfo] = []

    # Run git worktree list
    try:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode != 0:
            return []

        parsed = _parse_worktree_list(result.stdout)

    except (subprocess.SubprocessError, FileNotFoundError, OSError):
        return []

    # Process each worktree
    for wt in parsed:
        path = wt["path"]
        branch = wt["branch"]

        info = WorktreeInfo(
            path=path,
            branch=branch,
            issue_number=extract_issue_number(branch),
        )

        # Find associated Claude Code session
        session = _find_session_for_path(path)
        if session:
            info.session_id = session.get("sessionId")
            info.session_summary = session.get("summary")

            # Load tasks for this session
            if info.session_id:
                info.tasks = _load_tasks_for_session(info.session_id)

        worktrees.append(info)

    return worktrees


def get_worktree_by_path(path: str) -> Optional[WorktreeInfo]:
    """Get worktree info for a specific path.

    Args:
        path: Path to look up

    Returns:
        WorktreeInfo if found, None otherwise
    """
    normalized = str(Path(path).resolve())
    for wt in scan_worktrees():
        if str(Path(wt.path).resolve()) == normalized:
            return wt
    return None


def get_worktree_by_issue(issue_number: int) -> Optional[WorktreeInfo]:
    """Get worktree info for a specific issue number.

    Args:
        issue_number: GitHub issue number to look up

    Returns:
        WorktreeInfo if found, None otherwise
    """
    for wt in scan_worktrees():
        if wt.issue_number == issue_number:
            return wt
    return None
