"""Shared fixtures for Synthia tests."""

import json
import os
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_config_dir(tmp_path):
    """Create a temporary config directory with a config.yaml."""
    config_dir = tmp_path / ".config" / "synthia"
    config_dir.mkdir(parents=True)
    return config_dir


@pytest.fixture
def tmp_config_file(tmp_config_dir):
    """Create a temporary config.yaml file."""
    config_file = tmp_config_dir / "config.yaml"
    config_file.write_text(yaml.dump({"language": "en-AU", "sample_rate": 16000}))
    return config_file


@pytest.fixture
def tmp_memory_dir(tmp_path):
    """Create a temporary memory directory with empty JSONL files."""
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir(parents=True)
    for name in [
        "bugs.jsonl",
        "patterns.jsonl",
        "architecture.jsonl",
        "gotchas.jsonl",
        "stack.jsonl",
    ]:
        (memory_dir / name).touch()
    return memory_dir


@pytest.fixture
def tmp_tasks_file(tmp_path):
    """Create a temporary tasks.json file."""
    tasks_file = tmp_path / "tasks.json"
    tasks_file.write_text(json.dumps({"tasks": []}))
    return tasks_file


@pytest.fixture
def tmp_inbox_dir(tmp_path):
    """Create a temporary inbox directory."""
    inbox_dir = tmp_path / "inbox"
    inbox_dir.mkdir(parents=True)
    files_dir = inbox_dir / "files"
    files_dir.mkdir()
    return inbox_dir


@pytest.fixture
def clean_env(monkeypatch):
    """Remove display-related env vars for clean testing."""
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
