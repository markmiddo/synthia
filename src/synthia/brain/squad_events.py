"""Turn squad `events.jsonl` lines into job events the concierge speaks."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Callable

from synthia.brain.jobs import JobRecord
from synthia.squads.events import EventTail

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 5.0


def event_record(ev: dict[str, Any]) -> JobRecord:
    now = datetime.now().replace(microsecond=0).isoformat()
    squad = str(ev.get("squad") or "squad")
    job = str(ev.get("job") or "")
    return JobRecord(
        id=f"squad-{uuid.uuid4().hex[:8]}",
        name=f"{squad} squad {job}".strip(),
        prompt="",
        started=now,
        finished=now,
        ok=True,
        summary=_spoken_summary(ev, squad),
        status=str(ev.get("kind") or "review"),
    )


def _spoken_summary(ev: dict[str, Any], squad: str) -> str:
    head = str(ev.get("text") or f"{squad} squad has finished")
    digest = str(ev.get("digest") or "").strip()
    desk = str(ev.get("desk") or "")
    if not digest:
        return head
    where = f" Full files: {desk}/out." if desk else ""
    return (
        f"{head}. Tell Mark the outcome in two or three spoken sentences from the director's "
        f"summary below (what was done, what needs him), no file names.{where}\n\n{digest}"
    )


async def run_squad_tail(
    tail: EventTail, push: Callable[[JobRecord], None], interval: float = POLL_INTERVAL_S
) -> None:
    """Poll the events file forever; hand each new event to `push` (Brain.requeue)."""
    while True:
        try:
            for ev in await asyncio.to_thread(tail.poll):
                push(event_record(ev))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("squad event tail failed; continuing")
        await asyncio.sleep(interval)
