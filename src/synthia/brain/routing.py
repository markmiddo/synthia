"""The one place that decides which transport hears what.

Rules:
- A finished job or squad always lands in the HUD Inbox first. Then, exactly one channel hears
  about it, and only that channel's success acks the event (at-least-once):
  - Desk mode (a desk client is connected and Mark is present: an active HUD presence frame
    within 10 minutes, or a desk voice turn within 30): an `inbox` frame plus one short
    spoken `event` line at the desk. Nothing goes to Telegram.
  - Away mode: one short Telegram TEXT message (never a voice note, never a model turn).
  - If Telegram cannot be used (desk-only serve, or no chat yet) and a desk client is
    connected, the desk gets it even when Mark is not present; with neither, the event waits.
- A permission question goes to the transport that started the turn. A turn with no origin
  (a job-event or housekeeping turn) asks on both, and the first real answer wins.
- A desk turn whose client has gone falls back to Telegram rather than being lost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Awaitable, Callable

from synthia import inbox

logger = logging.getLogger(__name__)


class Router:
    def __init__(self, desk: Any, telegram: Any) -> None:
        self.desk = desk
        self.telegram = telegram
        self.brain: Any = None

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
        winner: bool | None = None
        try:
            for done in asyncio.as_completed(tasks):
                try:
                    answer = await done
                except Exception:
                    logger.exception("a confirmation leg failed")
                    continue
                if answer is not None:
                    approved = winner = answer
                    break
        finally:
            # Tell each leg still waiting how the question closed (None: nobody answered),
            # so it can say so where the user is looking before it is cancelled.
            for leg, t in zip(legs, tasks):
                hook = getattr(leg, "resolved", None)
                if not t.done() and callable(hook):
                    hook(winner)
            for t in tasks:
                t.cancel()
            for t in tasks:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await t
        journal = getattr(self.brain, "journal", None)
        if journal is not None:
            journal.confirmation(question, approved)
        return approved

    async def deliver_event(
        self, ev: Any, away_send: Callable[[str], Awaitable[None]] | None = None
    ) -> bool:
        """Route one finished-job event to the desk or, when Mark is away, to Telegram.

        `away_send` sends one short text to Telegram (None when it cannot right now). True
        means the event was delivered and the caller should ack it. False means nothing could
        hear it yet, so the caller requeues. Exceptions from `away_send` propagate so the
        caller can count failures.
        """
        rec = ev.job
        item = inbox.get(rec.inbox_id) if rec.inbox_id else None
        desk_up = self.desk is not None and self.desk.has_clients
        if desk_up and (away_send is None or self.desk.is_present):
            return await self._to_desk(ev, item)
        if away_send is None:
            return False
        if item is not None and (item.get("notified") or {}).get("telegram"):
            return True  # sent before a restart or a failed ack; do not text twice
        ok = rec.ok is not False
        text = inbox.away_line(item, ok) if item is not None else ev.text
        await away_send(text or f"{rec.name} finished.")
        if item is not None:
            inbox.mark_notified(item["id"], "telegram")
        return True

    async def _to_desk(self, ev: Any, item: dict[str, Any] | None) -> bool:
        if item is not None and (item.get("notified") or {}).get("desk"):
            return True
        try:
            if item is not None:
                await self.desk.push_inbox(item["id"], str(item.get("title") or ""))
            await self.desk.push_event(ev.text or f"{ev.job.name} finished.")
        except Exception:
            logger.exception("desk delivery of a job event failed")
            return False
        if item is not None:
            inbox.mark_notified(item["id"], "desk")
        return True
