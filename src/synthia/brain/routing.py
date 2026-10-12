"""The one place that decides which transport hears what.

Rules:
- Telegram is the delivery of record for job events (acked only after its push); the desk
  gets a best-effort copy when a client is connected. The desk never acks or blocks.
- A permission question goes to the transport that started the turn. A turn with no origin
  (a job-event or housekeeping turn) asks on both, and the first real answer wins.
- A desk turn whose client has gone falls back to Telegram rather than being lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class Router:
    def __init__(self, desk: Any, telegram: Any) -> None:
        self.desk = desk
        self.telegram = telegram
        self.brain: Any = None
        # Job ids already copied to the desk, so a requeued event is not shown twice.
        self._mirrored: set[str] = set()

    def _legs(self, origin: str | None) -> list[Any]:
        telegram = [self.telegram] if self.telegram is not None else []
        desk = [self.desk] if self.desk is not None and self.desk.has_clients else []
        if origin == "telegram":
            return telegram
        if origin == "desk":
            return desk or telegram
        return desk + telegram

    async def confirm(self, question: str) -> bool:
        legs = self._legs(getattr(self.brain, "turn_origin", None))
        if not legs:
            logger.warning("no transport to confirm with; denying: %s", question)
            return False
        tasks = [asyncio.ensure_future(leg.ask(question)) for leg in legs]
        approved = False
        try:
            for done in asyncio.as_completed(tasks):
                try:
                    answer = await done
                except Exception:
                    logger.exception("a confirmation leg failed")
                    continue
                if answer is not None:
                    approved = answer
                    break
        finally:
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        journal = getattr(self.brain, "journal", None)
        if journal is not None:
            journal.confirmation(question, approved)
        return approved

    async def mirror_event(self, ev: Any) -> None:
        """Copy a finished-job event to the desk. Best effort: never raises, never acks."""
        if self.desk is None or not self.desk.has_clients or ev.job.id in self._mirrored:
            return
        try:
            await self.desk.push_event(ev.text or f"{ev.job.name} finished.")
            self._mirrored.add(ev.job.id)
        except Exception:
            logger.exception("desk copy of a job event failed")
