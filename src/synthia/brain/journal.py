"""Walk journal: one markdown file per day recording what Mark and the brain said.

The file lives in the synced eventflo memory folder, so the desktop Claude Code
session (via its SessionStart hook) and the `/morning` skill can read what already
happened on the walk. Entries are appended, never rewritten; failures are logged and
swallowed so journaling can never break a turn.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

DEFAULT_JOURNAL_DIR = (
    Path.home() / ".claude" / "projects" / "-home-markmiddo-dev-eventflo" / "memory" / "walk"
)
REPLY_LIMIT = 600
SUMMARY_LIMIT = 400


def _one_line(text: str, limit: int) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


class WalkJournal:
    def __init__(
        self,
        root: Path,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.root = root
        self._now = now

    def path_for(self, day: date) -> Path:
        return self.root / f"{day.isoformat()}.md"

    def today_path(self) -> Path:
        return self.path_for(self._now().date())

    def _append(self, line: str) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            path = self.today_path()
            new_file = not path.exists()
            with open(path, "a", encoding="utf-8") as f:
                if new_file:
                    f.write(f"# Walk journal {self._now().date().isoformat()}\n\n")
                f.write(f"- {self._now().strftime('%H:%M')} {line}\n")
        except OSError:
            logger.warning("walk journal write failed", exc_info=True)

    def turn(self, user_text: str, reply_text: str) -> None:
        self._append(
            f"**Mark:** {_one_line(user_text, REPLY_LIMIT)}\n"
            f"  **Synthia:** {_one_line(reply_text, REPLY_LIMIT)}"
        )

    def job_dispatched(self, name: str, prompt: str) -> None:
        self._append(f"**Job dispatched:** {name} — {_one_line(prompt, SUMMARY_LIMIT)}")

    def job_finished(self, name: str, status: str, summary: str, spoken: str) -> None:
        self._append(
            f"**Job {status}:** {name} — {_one_line(summary, SUMMARY_LIMIT)}\n"
            f"  **Synthia:** {_one_line(spoken, REPLY_LIMIT)}"
        )

    def confirmation(self, question: str, approved: bool) -> None:
        verdict = "approved" if approved else "denied"
        self._append(f"**Confirmation {verdict}:** {_one_line(question, SUMMARY_LIMIT)}")

    def note(self, text: str) -> None:
        self._append(_one_line(text, REPLY_LIMIT))
