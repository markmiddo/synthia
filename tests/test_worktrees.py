"""Tests for worktrees.py pure-logic functions."""

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from synthia.worktrees import (
    WorktreeInfo,
    WorktreeTask,
    _parse_worktree_list,
    extract_issue_number,
    load_config,
)


class TestExtractIssueNumber:
    """Tests for extract_issue_number function."""

    def test_feature_branch_pattern(self):
        """Extract issue number from feature/XXX-name pattern."""
        assert extract_issue_number("feature/295-dark-mode") == 295

    def test_issue_branch_pattern(self):
        """Extract issue number from issue-XXX-name pattern."""
        assert extract_issue_number("issue-301-fix-auth") == 301

    def test_fix_branch_pattern(self):
        """Extract issue number from fix/XXX-name pattern."""
        assert extract_issue_number("fix/42-bug") == 42

    def test_bugfix_branch_pattern(self):
        """Extract issue number from bugfix/XXX-name pattern."""
        assert extract_issue_number("bugfix/100-crash") == 100

    def test_hotfix_branch_pattern(self):
        """Extract issue number from hotfix/XXX-name pattern."""
        assert extract_issue_number("hotfix/99-urgent") == 99

    def test_number_prefix_pattern(self):
        """Extract issue number from XXX-name pattern."""
        assert extract_issue_number("295-flosale-mobile") == 295

    def test_main_branch_returns_none(self):
        """Main branch has no issue number."""
        assert extract_issue_number("main") is None

    def test_development_branch_returns_none(self):
        """Development branch has no issue number."""
        assert extract_issue_number("development") is None

    def test_empty_string_returns_none(self):
        """Empty string has no issue number."""
        assert extract_issue_number("") is None


class TestParseWorktreeList:
    """Tests for _parse_worktree_list function."""

    def test_single_worktree(self):
        """Parse output with single worktree entry."""
        output = """worktree /home/user/project
HEAD abc123def456
branch refs/heads/feature/295-dark-mode

"""
        result = _parse_worktree_list(output)
        assert len(result) == 1
        assert result[0]["path"] == "/home/user/project"
        assert result[0]["branch"] == "feature/295-dark-mode"

    def test_multiple_worktrees(self):
        """Parse output with multiple worktree entries."""
        output = """worktree /home/user/project
HEAD abc123def456
branch refs/heads/main

worktree /home/user/project-worktrees/feature-branch
HEAD def789ghi012
branch refs/heads/feature/42-new-feature

worktree /home/user/project-worktrees/bugfix
HEAD 111222333444
branch refs/heads/bugfix/100-fix-crash

"""
        result = _parse_worktree_list(output)
        assert len(result) == 3
        assert result[0]["path"] == "/home/user/project"
        assert result[0]["branch"] == "main"
        assert result[1]["path"] == "/home/user/project-worktrees/feature-branch"
        assert result[1]["branch"] == "feature/42-new-feature"
        assert result[2]["path"] == "/home/user/project-worktrees/bugfix"
        assert result[2]["branch"] == "bugfix/100-fix-crash"

    def test_empty_output(self):
        """Parse empty output returns empty list."""
        result = _parse_worktree_list("")
        assert result == []

    def test_strips_refs_heads_prefix(self):
        """Branch names have refs/heads/ prefix stripped."""
        output = """worktree /home/user/project
HEAD abc123
branch refs/heads/development

"""
        result = _parse_worktree_list(output)
        assert result[0]["branch"] == "development"
        assert "refs/heads/" not in result[0]["branch"]


class TestLoadConfig:
    """Tests for load_config function."""

    def test_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        """Return default config when config file does not exist."""
        fake_config_path = tmp_path / "nonexistent" / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        result = load_config()
        assert result == {}

    def test_reads_yaml_file(self, tmp_path, monkeypatch):
        """Read and parse existing yaml config file."""
        fake_config_path = tmp_path / "worktrees.yaml"
        config_data = {
            "repos": [
                {"path": "/home/user/project1", "name": "project1"},
                {"path": "/home/user/project2", "name": "project2"},
            ]
        }
        with open(fake_config_path, "w") as f:
            yaml.dump(config_data, f)

        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        result = load_config()
        assert result == config_data
        assert len(result["repos"]) == 2
        assert result["repos"][0]["name"] == "project1"


class TestWorktreeInfoProgress:
    """Tests for WorktreeInfo.progress property."""

    def test_progress_with_no_tasks(self):
        """Progress returns (0, 0) when no tasks exist."""
        info = WorktreeInfo(
            path="/home/user/project",
            branch="feature/123-test",
            issue_number=123,
            tasks=[],
        )
        completed, total = info.progress
        assert completed == 0
        assert total == 0

    def test_progress_with_tasks(self):
        """Progress returns correct completed and total counts."""
        tasks = [
            WorktreeTask(content="Task 1", status="completed", active_form="Doing task 1"),
            WorktreeTask(content="Task 2", status="pending", active_form="Doing task 2"),
            WorktreeTask(content="Task 3", status="completed", active_form="Doing task 3"),
            WorktreeTask(content="Task 4", status="in_progress", active_form="Doing task 4"),
            WorktreeTask(content="Task 5", status="completed", active_form="Doing task 5"),
        ]
        info = WorktreeInfo(
            path="/home/user/project",
            branch="feature/456-work",
            issue_number=456,
            tasks=tasks,
        )
        completed, total = info.progress
        assert completed == 3
        assert total == 5
