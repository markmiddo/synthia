"""Skip the whole brain test directory when the `brain` extra is not installed.

A conftest-level `importorskip` skips collection of this directory, so CI runs
that install only `.[dev]` see the brain tests as skipped rather than erroring.
"""

import pytest

pytest.importorskip("claude_agent_sdk")
pytest.importorskip("telegram")
pytest.importorskip("google.cloud.speech")
