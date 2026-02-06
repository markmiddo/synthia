"""Inbox management for phone-to-desktop file sync via Telegram."""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def get_inbox_dir() -> Path:
    """Get the inbox directory, creating it if necessary."""
    inbox_dir = Path.home() / ".local" / "share" / "synthia" / "inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    return inbox_dir


def get_files_dir() -> Path:
    """Get the files subdirectory for downloaded files."""
    files_dir = get_inbox_dir() / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    return files_dir


def get_inbox_file() -> Path:
    """Get the path to the inbox JSON file."""
    return get_inbox_dir() / "inbox.json"


def load_inbox() -> list[dict]:
    """Load inbox items from JSON file."""
    inbox_file = get_inbox_file()
    try:
        if inbox_file.exists():
            with open(inbox_file) as f:
                data = json.load(f)
                return data.get("items", [])
    except Exception as e:
        logger.warning("Failed to load inbox: %s", e)
    return []


def save_inbox(items: list[dict]):
    """Save inbox items to JSON file."""
    inbox_file = get_inbox_file()
    try:
        with open(inbox_file, "w") as f:
            json.dump({"items": items}, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save inbox: %s", e)


def add_inbox_item(
    item_type: str,
    filename: str,
    path: Optional[str] = None,
    url: Optional[str] = None,
    size_bytes: Optional[int] = None,
    from_user: Optional[str] = None,
) -> dict:
    """Add a new item to the inbox."""
    items = load_inbox()

    item = {
        "id": str(uuid.uuid4()),
        "type": item_type,
        "filename": filename,
        "path": path,
        "url": url,
        "received_at": datetime.now().isoformat(),
        "size_bytes": size_bytes,
        "from_user": from_user,
        "opened": False,
    }

    items.insert(0, item)

    # Keep only last 50 items
    items = items[:50]

    save_inbox(items)
    return item


def mark_item_opened(item_id: str):
    """Mark an inbox item as opened."""
    items = load_inbox()
    for item in items:
        if item.get("id") == item_id:
            item["opened"] = True
            break
    save_inbox(items)


def delete_inbox_item(item_id: str) -> bool:
    """Delete an inbox item and its associated file."""
    items = load_inbox()
    new_items = []
    deleted = False

    for item in items:
        if item.get("id") == item_id:
            # Delete associated file if it exists
            if item.get("path") and os.path.exists(item["path"]):
                try:
                    os.remove(item["path"])
                except OSError as e:
                    logger.debug("Failed to delete inbox file %s: %s", item["path"], e)
            deleted = True
        else:
            new_items.append(item)

    save_inbox(new_items)
    return deleted


def clear_inbox():
    """Clear all inbox items and their files."""
    items = load_inbox()

    # Delete all files
    for item in items:
        if item.get("path") and os.path.exists(item["path"]):
            try:
                os.remove(item["path"])
            except OSError as e:
                logger.debug("Failed to delete inbox file %s: %s", item["path"], e)

    save_inbox([])


def get_inbox_items() -> list[dict]:
    """Get all inbox items."""
    return load_inbox()
