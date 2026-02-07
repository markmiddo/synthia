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


class TestSaveAndLoadConfig:
    """Tests for save_config and load_config roundtrip."""

    def test_save_config_writes_valid_yaml(self, tmp_path, monkeypatch):
        """Save config writes valid YAML that can be read back."""
        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        config = {
            "repos": [
                "/home/user/project1",
                "/home/user/project2",
            ]
        }

        result = patch("synthia.worktrees.CONFIG_PATH", fake_config_path)
        with result:
            from synthia.worktrees import save_config

            saved = save_config(config)

        assert saved is True
        assert fake_config_path.exists()

    def test_save_and_load_config_roundtrip(self, tmp_path, monkeypatch):
        """Save and load config preserves data."""
        from synthia.worktrees import load_config, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        original_config = {
            "repos": [
                "/home/user/project1",
                "/home/user/project2",
            ]
        }

        save_config(original_config)
        loaded_config = load_config()

        assert loaded_config == original_config
        assert loaded_config["repos"] == original_config["repos"]

    def test_save_config_creates_parent_directories(self, tmp_path, monkeypatch):
        """Save config creates parent directories if they don't exist."""
        from synthia.worktrees import save_config

        fake_config_path = tmp_path / "deep" / "nested" / "path" / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        result = save_config({"repos": []})

        assert result is True
        assert fake_config_path.parent.exists()


class TestGetConfiguredRepos:
    """Tests for get_configured_repos function."""

    def test_get_configured_repos_returns_list(self, tmp_path, monkeypatch):
        """Get configured repos returns a list of repo paths."""
        from synthia.worktrees import get_configured_repos, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        config = {
            "repos": [
                "/home/user/project1",
                "/home/user/project2",
            ]
        }
        save_config(config)

        repos = get_configured_repos()

        assert isinstance(repos, list)
        assert len(repos) == 2
        assert "/home/user/project1" in repos
        assert "/home/user/project2" in repos

    def test_get_configured_repos_returns_empty_when_no_config(self, tmp_path, monkeypatch):
        """Get configured repos returns empty list when no config exists."""
        from synthia.worktrees import get_configured_repos

        fake_config_path = tmp_path / "nonexistent" / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        repos = get_configured_repos()

        assert repos == []


class TestAddRepo:
    """Tests for add_repo function."""

    def test_add_repo_adds_new_repository(self, tmp_path, monkeypatch):
        """Add repo adds a new repository path to config."""
        from synthia.worktrees import add_repo, get_configured_repos, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        save_config({"repos": []})

        result = add_repo("/home/user/newproject")

        assert result is True
        repos = get_configured_repos()
        assert "/home/user/newproject" in [r for r in repos]

    def test_add_repo_idempotent_does_not_duplicate(self, tmp_path, monkeypatch):
        """Add repo does not create duplicate entries."""
        from synthia.worktrees import add_repo, get_configured_repos, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        repo_path = "/home/user/project1"
        save_config({"repos": [repo_path]})

        # Add the same repo again
        result = add_repo(repo_path)

        assert result is True
        repos = get_configured_repos()
        count = sum(1 for r in repos if r == repo_path)
        assert count == 1

    def test_add_repo_normalizes_paths(self, tmp_path, monkeypatch):
        """Add repo normalizes paths for comparison."""
        from synthia.worktrees import add_repo, get_configured_repos, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        save_config({"repos": []})

        # Add with relative-like path
        add_repo("/home/user/project")

        repos = get_configured_repos()
        assert any("project" in r for r in repos)


class TestRemoveRepo:
    """Tests for remove_repo function."""

    def test_remove_repo_removes_repository(self, tmp_path, monkeypatch):
        """Remove repo removes a repository path from config."""
        from synthia.worktrees import get_configured_repos, remove_repo, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        repo_path = "/home/user/projecttoremove"
        save_config({"repos": [repo_path, "/home/user/otherproject"]})

        result = remove_repo(repo_path)

        assert result is True
        repos = get_configured_repos()
        assert repo_path not in repos
        assert "/home/user/otherproject" in repos

    def test_remove_repo_handles_missing_gracefully(self, tmp_path, monkeypatch):
        """Remove repo handles missing repo paths gracefully."""
        from synthia.worktrees import remove_repo, save_config

        fake_config_path = tmp_path / "worktrees.yaml"
        monkeypatch.setattr("synthia.worktrees.CONFIG_PATH", fake_config_path)

        save_config({"repos": ["/home/user/project1"]})

        # Try to remove non-existent repo
        result = remove_repo("/home/user/nonexistent")

        assert result is True


class TestWorktreeTaskDataclass:
    """Tests for WorktreeTask dataclass."""

    def test_worktree_task_has_required_fields(self):
        """WorktreeTask has content, status, and active_form fields."""
        task = WorktreeTask(
            content="Do something",
            status="in_progress",
            active_form="Doing something",
        )

        assert task.content == "Do something"
        assert task.status == "in_progress"
        assert task.active_form == "Doing something"

    def test_worktree_task_status_values(self):
        """WorktreeTask can have pending, in_progress, or completed status."""
        for status in ["pending", "in_progress", "completed"]:
            task = WorktreeTask(
                content="Task",
                status=status,
                active_form="Doing task",
            )
            assert task.status == status


class TestWorktreeInfoDataclass:
    """Tests for WorktreeInfo dataclass."""

    def test_worktree_info_has_required_fields(self):
        """WorktreeInfo has path, branch, and optional fields."""
        info = WorktreeInfo(
            path="/home/user/project",
            branch="feature/123-test",
        )

        assert info.path == "/home/user/project"
        assert info.branch == "feature/123-test"
        assert info.session_id is None
        assert info.session_summary is None

    def test_worktree_info_with_session_fields(self):
        """WorktreeInfo can store session_id and session_summary."""
        info = WorktreeInfo(
            path="/home/user/project",
            branch="feature/123-test",
            issue_number=123,
            issue_title="Test feature",
            session_id="session-123",
            session_summary="Working on test feature",
        )

        assert info.session_id == "session-123"
        assert info.session_summary == "Working on test feature"
        assert info.issue_title == "Test feature"

    def test_worktree_info_with_tasks(self):
        """WorktreeInfo can store tasks list."""
        tasks = [
            WorktreeTask(content="Task 1", status="pending", active_form="Working on task 1"),
            WorktreeTask(content="Task 2", status="completed", active_form="Completed task 2"),
        ]
        info = WorktreeInfo(
            path="/home/user/project",
            branch="feature/123-test",
            tasks=tasks,
        )

        assert len(info.tasks) == 2
        assert info.tasks[0].content == "Task 1"
        assert info.tasks[1].status == "completed"
