"""Tests for the task functions in src/synthia/tasks_cli.py."""

import json
import pytest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch

import synthia.tasks_cli as tasks_cli
from synthia.tasks_cli import (
    load_tasks,
    save_tasks,
    find_task,
    add_task,
    complete_task,
    move_task,
    delete_task,
    list_tasks,
)


class TestLoadTasks:
    """Tests for the load_tasks function."""

    def test_load_tasks_returns_empty_when_file_does_not_exist(self, tmp_path: Path, monkeypatch):
        """Load tasks returns empty structure when file doesn't exist."""
        nonexistent_file = tmp_path / "nonexistent" / "tasks.json"
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", nonexistent_file)

        result = load_tasks()

        assert result == {"tasks": []}

    def test_load_tasks_reads_existing_json(self, tmp_tasks_file: Path, monkeypatch):
        """Load tasks reads and parses existing JSON file."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        existing_data = {
            "tasks": [
                {
                    "id": "abc123",
                    "title": "Test task",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        with open(tmp_tasks_file, "w") as f:
            json.dump(existing_data, f)

        result = load_tasks()

        assert len(result["tasks"]) == 1
        assert result["tasks"][0]["title"] == "Test task"
        assert result["tasks"][0]["id"] == "abc123"


class TestSaveTasks:
    """Tests for the save_tasks function."""

    def test_save_tasks_writes_valid_json(self, tmp_tasks_file: Path, monkeypatch):
        """Save tasks writes valid JSON to file."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "xyz789",
                    "title": "Saved task",
                    "description": "A description",
                    "status": "in_progress",
                    "tags": ["urgent"],
                    "due_date": "2024-02-01",
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }

        save_tasks(data)

        with open(tmp_tasks_file) as f:
            loaded = json.load(f)

        assert loaded["tasks"][0]["title"] == "Saved task"
        assert loaded["tasks"][0]["status"] == "in_progress"


class TestAddTask:
    """Tests for the add_task function."""

    def test_add_task_creates_task_with_uuid_and_timestamps(self, tmp_tasks_file: Path, monkeypatch):
        """Add task creates task with UUID and created_at timestamp."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        add_task(title="New task")

        data = load_tasks()
        assert len(data["tasks"]) == 1
        task = data["tasks"][0]

        assert task["title"] == "New task"
        assert task["id"] is not None
        assert len(task["id"]) > 0
        assert task["created_at"] is not None
        assert task["status"] == "todo"
        assert task["completed_at"] is None

    def test_add_task_with_tags_parses_comma_separated_string(self, tmp_tasks_file: Path, monkeypatch):
        """Add task parses comma-separated tags string into list."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        add_task(title="Tagged task", tags="urgent,important,backend")

        data = load_tasks()
        task = data["tasks"][0]

        assert "urgent" in task["tags"]
        assert "important" in task["tags"]
        assert "backend" in task["tags"]

    def test_add_task_with_due_date(self, tmp_tasks_file: Path, monkeypatch):
        """Add task stores due date correctly."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        add_task(title="Due task", due_date="2024-02-15")

        data = load_tasks()
        task = data["tasks"][0]

        assert task["due_date"] == "2024-02-15"


class TestFindTask:
    """Tests for the find_task function."""

    def test_find_task_by_exact_id(self, tmp_tasks_file: Path, monkeypatch):
        """Find task locates task by exact ID match."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "exact-id-123",
                    "title": "Find me",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }

        task = find_task(data, "exact-id-123")

        assert task is not None
        assert task["title"] == "Find me"

    def test_find_task_by_partial_title_case_insensitive(self, tmp_tasks_file: Path, monkeypatch):
        """Find task locates task by partial title match (case insensitive)."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "some-id",
                    "title": "Implement User Authentication",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }

        task = find_task(data, "user auth")

        assert task is not None
        assert task["title"] == "Implement User Authentication"

    def test_find_task_returns_none_for_no_match(self, tmp_tasks_file: Path, monkeypatch):
        """Find task returns None when no task matches."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "some-id",
                    "title": "Some task",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }

        task = find_task(data, "nonexistent")

        assert task is None


class TestCompleteTask:
    """Tests for the complete_task function."""

    def test_complete_task_sets_status_and_completed_at(self, tmp_tasks_file: Path, monkeypatch):
        """Complete task sets status to done and sets completed_at timestamp."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-to-complete",
                    "title": "Complete me",
                    "description": None,
                    "status": "in_progress",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        result = complete_task("task-to-complete")

        assert result is True
        updated_data = load_tasks()
        task = updated_data["tasks"][0]
        assert task["status"] == "done"
        assert task["completed_at"] is not None

    def test_complete_task_returns_false_for_missing_task(self, tmp_tasks_file: Path, monkeypatch):
        """Complete task returns False when task doesn't exist."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        save_tasks({"tasks": []})

        result = complete_task("nonexistent-id")

        assert result is False


class TestMoveTask:
    """Tests for the move_task function."""

    def test_move_task_changes_status(self, tmp_tasks_file: Path, monkeypatch):
        """Move task changes task status."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-to-move",
                    "title": "Move me",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        result = move_task("task-to-move", "in_progress")

        assert result is True
        updated_data = load_tasks()
        assert updated_data["tasks"][0]["status"] == "in_progress"

    def test_move_task_rejects_invalid_status(self, tmp_tasks_file: Path, monkeypatch):
        """Move task returns False for invalid status."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-id",
                    "title": "Task",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        result = move_task("task-id", "invalid_status")

        assert result is False

    def test_move_task_to_done_sets_completed_at(self, tmp_tasks_file: Path, monkeypatch):
        """Move task to done sets completed_at timestamp."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-id",
                    "title": "Task",
                    "description": None,
                    "status": "in_progress",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        result = move_task("task-id", "done")

        assert result is True
        updated_data = load_tasks()
        assert updated_data["tasks"][0]["completed_at"] is not None

    def test_move_task_from_done_clears_completed_at(self, tmp_tasks_file: Path, monkeypatch):
        """Move task from done to another status clears completed_at."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-id",
                    "title": "Task",
                    "description": None,
                    "status": "done",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": "2024-01-16T10:00:00",
                }
            ]
        }
        save_tasks(data)

        result = move_task("task-id", "todo")

        assert result is True
        updated_data = load_tasks()
        assert updated_data["tasks"][0]["status"] == "todo"
        assert updated_data["tasks"][0]["completed_at"] is None


class TestDeleteTask:
    """Tests for the delete_task function."""

    def test_delete_task_removes_task(self, tmp_tasks_file: Path, monkeypatch):
        """Delete task removes task from list."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-to-delete",
                    "title": "Delete me",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
                {
                    "id": "task-to-keep",
                    "title": "Keep me",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
            ]
        }
        save_tasks(data)

        result = delete_task("task-to-delete")

        assert result is True
        updated_data = load_tasks()
        assert len(updated_data["tasks"]) == 1
        assert updated_data["tasks"][0]["id"] == "task-to-keep"

    def test_delete_task_returns_false_for_missing_task(self, tmp_tasks_file: Path, monkeypatch):
        """Delete task returns False when task doesn't exist."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        save_tasks({"tasks": []})

        result = delete_task("nonexistent-id")

        assert result is False
