"""Skip the whole brain test directory when the `brain` extra is not installed.

A conftest-level `importorskip` skips collection of this directory, so CI runs
that install only `.[dev]` see the brain tests as skipped rather than erroring.
"""

import pytest

pytest.importorskip("claude_agent_sdk")
pytest.importorskip("telegram")
pytest.importorskip("google.cloud.speech")


@pytest.fixture(autouse=True)
def _no_real_journal(monkeypatch, tmp_path):
    """Never let a test write into Mark's real walk journal folder."""
    from synthia.brain import config as brain_config

    monkeypatch.setattr(brain_config, "DEFAULT_JOURNAL_DIR", tmp_path / "default-walk")
