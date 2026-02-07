#!/usr/bin/env python3
"""
CLI for managing Synthia tasks from Claude Code or Telegram bot.

Usage:
    python tasks_cli.py list [--status STATUS]
    python tasks_cli.py add "Task title" [--desc "Description"] [--tags "tag1,tag2"] [--due "2026-02-10"]
    python tasks_cli.py done TASK_ID_OR_TITLE
    python tasks_cli.py move TASK_ID_OR_TITLE STATUS
    python tasks_cli.py delete TASK_ID_OR_TITLE
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

TASKS_FILE = Path.home() / ".config" / "synthia" / "tasks.json"


def load_tasks() -> dict:
    if not TASKS_FILE.exists():
        return {"tasks": []}
    with open(TASKS_FILE) as f:
        return json.load(f)


def save_tasks(data: dict) -> None:
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def find_task(data: dict, identifier: str) -> Optional[dict]:
    """Find task by ID or title (partial match)."""
    # Try exact ID match first
    for task in data["tasks"]:
        if task["id"] == identifier:
            return task
    # Try title match (case-insensitive, partial)
    identifier_lower = identifier.lower()
    for task in data["tasks"]:
        if identifier_lower in task["title"].lower():
            return task
    return None


def list_tasks(status: Optional[str] = None) -> None:
    data = load_tasks()
    tasks = data["tasks"]

    if status:
        tasks = [t for t in tasks if t["status"] == status]

    if not tasks:
        print("No tasks found.")
        return

    # Group by status
    by_status = {"todo": [], "in_progress": [], "done": []}
    for t in tasks:
        by_status.get(t["status"], []).append(t)

    for status_name, status_tasks in [("To Do", by_status["todo"]),
                                        ("In Progress", by_status["in_progress"]),
                                        ("Done", by_status["done"])]:
        if status_tasks:
            print(f"\n{status_name}:")
            for t in status_tasks:
                due = f" (due: {t['due_date']})" if t.get("due_date") else ""
                tags = f" [{', '.join(t['tags'])}]" if t.get("tags") else ""
                print(f"  - {t['title']}{due}{tags}")


def add_task(title: str, description: Optional[str] = None, tags: Optional[str] = None, due_date: Optional[str] = None) -> None:
    data = load_tasks()

    task = {
        "id": str(uuid.uuid4()),
        "title": title,
        "description": description,
        "status": "todo",
        "tags": tags.split(",") if tags else [],
        "due_date": due_date,
        "created_at": datetime.now().astimezone().isoformat(),
        "completed_at": None
    }

    data["tasks"].append(task)
    save_tasks(data)
    print(f"Added task: {title}")


def complete_task(identifier: str) -> bool:
    data = load_tasks()
    task = find_task(data, identifier)

    if not task:
        print(f"Task not found: {identifier}")
        return False

    task["status"] = "done"
    task["completed_at"] = datetime.now().astimezone().isoformat()
    save_tasks(data)
    print(f"Completed: {task['title']}")
    return True


def move_task(identifier: str, status: str) -> bool:
    if status not in ["todo", "in_progress", "done"]:
        print(f"Invalid status: {status}. Use: todo, in_progress, done")
        return False

    data = load_tasks()
    task = find_task(data, identifier)

    if not task:
        print(f"Task not found: {identifier}")
        return False

    task["status"] = status
    if status == "done":
        task["completed_at"] = datetime.now().astimezone().isoformat()
    else:
        task["completed_at"] = None

    save_tasks(data)
    print(f"Moved '{task['title']}' to {status}")
    return True


def delete_task(identifier: str) -> bool:
    data = load_tasks()
    task = find_task(data, identifier)

    if not task:
        print(f"Task not found: {identifier}")
        return False

    data["tasks"] = [t for t in data["tasks"] if t["id"] != task["id"]]
    save_tasks(data)
    print(f"Deleted: {task['title']}")
    return True


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "list":
        status = None
        if "--status" in sys.argv:
            idx = sys.argv.index("--status")
            if idx + 1 < len(sys.argv):
                status = sys.argv[idx + 1]
        list_tasks(status)

    elif command == "add":
        if len(sys.argv) < 3:
            print("Usage: tasks_cli.py add \"Task title\" [--desc \"...\"] [--tags \"...\"] [--due \"...\"]")
            return

        title = sys.argv[2]
        description = None
        tags = None
        due_date = None

        args = sys.argv[3:]
        i = 0
        while i < len(args):
            if args[i] == "--desc" and i + 1 < len(args):
                description = args[i + 1]
                i += 2
            elif args[i] == "--tags" and i + 1 < len(args):
                tags = args[i + 1]
                i += 2
            elif args[i] == "--due" and i + 1 < len(args):
                due_date = args[i + 1]
                i += 2
            else:
                i += 1

        add_task(title, description, tags, due_date)

    elif command == "done":
        if len(sys.argv) < 3:
            print("Usage: tasks_cli.py done TASK_ID_OR_TITLE")
            return
        complete_task(sys.argv[2])

    elif command == "move":
        if len(sys.argv) < 4:
            print("Usage: tasks_cli.py move TASK_ID_OR_TITLE STATUS")
            return
        move_task(sys.argv[2], sys.argv[3])

    elif command == "delete":
        if len(sys.argv) < 3:
            print("Usage: tasks_cli.py delete TASK_ID_OR_TITLE")
            return
        delete_task(sys.argv[2])

    else:
        print(f"Unknown command: {command}")
        print(__doc__)


if __name__ == "__main__":
    main()
