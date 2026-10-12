"""Is Mark at the computer? Read from logind: the graphical session is unlocked and not idle.

The HUD's own presence frames only fire when its window has focus, and Mark mostly works in a
terminal with the HUD in the background, so the desktop session is the better signal. When
logind cannot answer (no session, no loginctl), this reports False and the desk falls back to
the HUD's frames and recent voice turns.
"""

from __future__ import annotations

import getpass
import logging
import subprocess
import time
from typing import Callable

logger = logging.getLogger(__name__)

CACHE_S = 30.0


def _run(args: list[str]) -> str:
    return subprocess.run(args, capture_output=True, text=True, timeout=3, check=True).stdout


def graphical_session_id(run: Callable[[list[str]], str] = _run) -> str | None:
    """The user's session on a seat (the desktop), not an SSH or tty login."""
    user = getpass.getuser()
    for line in run(["loginctl", "list-sessions", "--no-legend"]).splitlines():
        parts = line.split()
        # SESSION UID USER SEAT TTY ...
        if len(parts) >= 4 and parts[2] == user and parts[3].startswith("seat"):
            return parts[0]
    return None


def session_active(run: Callable[[list[str]], str] = _run) -> bool:
    sid = graphical_session_id(run)
    if sid is None:
        return False
    out = run(
        ["loginctl", "show-session", sid, "-p", "LockedHint", "-p", "IdleHint", "-p", "Active"]
    )
    props = dict(line.split("=", 1) for line in out.splitlines() if "=" in line)
    return (
        props.get("Active") == "yes"
        and props.get("LockedHint") == "no"
        and props.get("IdleHint") == "no"
    )


class CachedSessionActive:
    """`session_active` with a short cache, safe to call on every routed event."""

    def __init__(
        self,
        probe: Callable[[], bool] = session_active,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = CACHE_S,
    ) -> None:
        self._probe = probe
        self._clock = clock
        self._ttl = ttl
        self._at: float | None = None
        self._value = False

    def __call__(self) -> bool:
        now = self._clock()
        if self._at is None or now - self._at > self._ttl:
            try:
                self._value = self._probe()
            except Exception as exc:  # noqa: BLE001 - presence is advisory; never break routing
                logger.debug("logind presence check failed: %s", exc)
                self._value = False
            self._at = now
        return self._value
