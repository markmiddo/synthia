"""Tests for the task functions in src/synthia/tasks_cli.py."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

import synthia.tasks_cli as tasks_cli
from synthia.tasks_cli import (
    add_task,
    complete_task,
    delete_task,
    find_task,
    list_tasks,
    load_tasks,
    move_task,
    save_tasks,
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

    def test_add_task_creates_task_with_uuid_and_timestamps(
        self, tmp_tasks_file: Path, monkeypatch
    ):
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

    def test_add_task_with_tags_parses_comma_separated_string(
        self, tmp_tasks_file: Path, monkeypatch
    ):
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


class TestListTasksOutput:
    """Tests for list_tasks output formatting."""

    def test_list_tasks_prints_all_tasks_when_no_filter(
        self, tmp_tasks_file: Path, monkeypatch, capsys
    ):
        """List tasks prints all tasks organized by status."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "1",
                    "title": "Todo task",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
                {
                    "id": "2",
                    "title": "In progress task",
                    "description": None,
                    "status": "in_progress",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
            ]
        }
        save_tasks(data)

        list_tasks()

        captured = capsys.readouterr()
        assert "To Do:" in captured.out
        assert "In Progress:" in captured.out
        assert "Todo task" in captured.out
        assert "In progress task" in captured.out

    def test_list_tasks_filters_by_status(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """List tasks with status filter only shows tasks with that status."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "1",
                    "title": "In progress 1",
                    "description": None,
                    "status": "in_progress",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
                {
                    "id": "2",
                    "title": "In progress 2",
                    "description": None,
                    "status": "in_progress",
                    "tags": [],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                },
                {
                    "id": "3",
                    "title": "Todo task",
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

        list_tasks(status="in_progress")

        captured = capsys.readouterr()
        assert "In progress 1" in captured.out
        assert "In progress 2" in captured.out
        assert "Todo task" not in captured.out

    def test_list_tasks_shows_message_when_empty(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """List tasks shows 'No tasks found' when no tasks exist."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        save_tasks({"tasks": []})

        list_tasks()

        captured = capsys.readouterr()
        assert "No tasks found" in captured.out

    def test_list_tasks_includes_due_dates_in_output(
        self, tmp_tasks_file: Path, monkeypatch, capsys
    ):
        """List tasks shows due dates when present."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "1",
                    "title": "Due soon",
                    "description": None,
                    "status": "todo",
                    "tags": [],
                    "due_date": "2024-02-20",
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        list_tasks()

        captured = capsys.readouterr()
        assert "2024-02-20" in captured.out

    def test_list_tasks_includes_tags_in_output(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """List tasks shows tags when present."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "1",
                    "title": "Tagged task",
                    "description": None,
                    "status": "todo",
                    "tags": ["urgent", "backend"],
                    "due_date": None,
                    "created_at": "2024-01-15T10:00:00",
                    "completed_at": None,
                }
            ]
        }
        save_tasks(data)

        list_tasks()

        captured = capsys.readouterr()
        assert "urgent" in captured.out
        assert "backend" in captured.out


class TestAddTaskWithDescription:
    """Tests for add_task with description parameter."""

    def test_add_task_with_description_stores_it(self, tmp_tasks_file: Path, monkeypatch):
        """Add task with description parameter stores the description."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        add_task(title="Task with desc", description="This is a detailed description")

        data = load_tasks()
        task = data["tasks"][0]

        assert task["title"] == "Task with desc"
        assert task["description"] == "This is a detailed description"

    def test_add_task_description_defaults_to_none(self, tmp_tasks_file: Path, monkeypatch):
        """Add task without description has None."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        add_task(title="No description")

        data = load_tasks()
        task = data["tasks"][0]

        assert task["description"] is None


class TestMainCliParsing:
    """Tests for main() CLI argument parsing."""

    def test_main_list_subcommand(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """main() with 'list' subcommand calls list_tasks."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)
        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "list"])

        data = {
            "tasks": [
                {
                    "id": "1",
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
        save_tasks(data)

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "Test task" in captured.out

    def test_main_add_subcommand_with_title(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """main() with 'add' subcommand adds a task."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)
        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "add", "New task"])

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "Added task: New task" in captured.out

        data = load_tasks()
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["title"] == "New task"

    def test_main_add_with_description_flag(self, tmp_tasks_file: Path, monkeypatch):
        """main() parses --desc flag for add command."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)
        monkeypatch.setattr(
            "sys.argv",
            ["tasks_cli.py", "add", "Task", "--desc", "Task description"],
        )

        tasks_cli.main()

        data = load_tasks()
        assert data["tasks"][0]["description"] == "Task description"

    def test_main_add_with_tags_flag(self, tmp_tasks_file: Path, monkeypatch):
        """main() parses --tags flag for add command."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)
        monkeypatch.setattr(
            "sys.argv",
            ["tasks_cli.py", "add", "Task", "--tags", "urgent,backend"],
        )

        tasks_cli.main()

        data = load_tasks()
        assert "urgent" in data["tasks"][0]["tags"]
        assert "backend" in data["tasks"][0]["tags"]

    def test_main_add_with_due_flag(self, tmp_tasks_file: Path, monkeypatch):
        """main() parses --due flag for add command."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)
        monkeypatch.setattr(
            "sys.argv",
            ["tasks_cli.py", "add", "Task", "--due", "2024-02-20"],
        )

        tasks_cli.main()

        data = load_tasks()
        assert data["tasks"][0]["due_date"] == "2024-02-20"

    def test_main_done_subcommand(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """main() with 'done' subcommand completes a task."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Complete me",
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

        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "done", "task-1"])

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "Completed:" in captured.out

    def test_main_move_subcommand(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """main() with 'move' subcommand changes task status."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-1",
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

        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "move", "task-1", "in_progress"])

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "in_progress" in captured.out

    def test_main_delete_subcommand(self, tmp_tasks_file: Path, monkeypatch, capsys):
        """main() with 'delete' subcommand removes a task."""
        monkeypatch.setattr("synthia.tasks_cli.TASKS_FILE", tmp_tasks_file)

        data = {
            "tasks": [
                {
                    "id": "task-1",
                    "title": "Delete me",
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

        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "delete", "task-1"])

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "Deleted:" in captured.out

    def test_main_unknown_command(self, monkeypatch, capsys):
        """main() with unknown command shows error."""
        monkeypatch.setattr("sys.argv", ["tasks_cli.py", "unknown"])

        tasks_cli.main()

        captured = capsys.readouterr()
        assert "Unknown command" in captured.out
