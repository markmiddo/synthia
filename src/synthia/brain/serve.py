"""`synthia-brain serve`: Telegram and the desk websocket on one concierge, one process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Any

from synthia.brain.config import BrainConfig

logger = logging.getLogger(__name__)


class ConfirmRouter:
    """Sends a permission question to the transport that started the current turn.

    A turn with no origin (a job-event or housekeeping turn) goes to the desk when a
    client is connected, otherwise to Telegram. If the originating desk client has
    dropped mid-turn the question falls back to Telegram rather than being lost.
    """

    def __init__(self, desk: Any, telegram: Any) -> None:
        self.desk = desk
        self.telegram = telegram
        self.brain: Any = None

    async def confirm(self, question: str) -> bool:
        origin = getattr(self.brain, "turn_origin", None)
        if origin == "telegram" and self.telegram is not None:
            return bool(await self.telegram.confirm(question))
        if self.desk.has_clients:
            return bool(await self.desk.confirm(question))
        if self.telegram is not None:
            return bool(await self.telegram.confirm(question))
        logger.warning("no transport to confirm with; denying: %s", question)
        return False


async def _pump_desk_events(brain: Any, desk: Any) -> None:
    """Desk-only mode: deliver job events to the desk, requeueing while no client is there."""
    from synthia.brain.concierge import EVENT_RETRY_DELAY_S

    while True:
        try:
            async for ev in brain.events():
                if not desk.has_clients:
                    brain.requeue(ev.job)
                    await asyncio.sleep(EVENT_RETRY_DELAY_S)
                    continue
                await desk.push_event(ev.text or f"{ev.job.name} finished.")
                brain.ack(ev.job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("desk event pump crashed; restarting")
            await asyncio.sleep(EVENT_RETRY_DELAY_S)


async def _serve_desk_only(cfg: BrainConfig, router: ConfirmRouter, desk: Any, brain: Any) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await brain.start()
    await desk.start()
    pump = asyncio.create_task(_pump_desk_events(brain, desk))
    try:
        await stop.wait()
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await desk.stop()
        await brain.stop()


def run_serve(cfg: BrainConfig) -> int:
    from synthia.brain.cli import pull_repos
    from synthia.brain.concierge import Brain
    from synthia.brain.speech import Speech
    from synthia.brain.transports.desk import DeskTransport

    pull_repos(cfg.repos)
    desk = DeskTransport(None, cfg.desk_port, cfg.desk_token_file, cfg.confirm_timeout_s)

    if not cfg.telegram_token:
        # No token means no Telegram poller at all; the desk still works.
        logger.warning("BRAIN_TELEGRAM_TOKEN is not set; serving the desk only")
        router = ConfirmRouter(desk, None)
        brain = Brain(cfg, router.confirm)
        router.brain = desk.brain = brain
        asyncio.run(_serve_desk_only(cfg, router, desk, brain))
        return 0

    from telegram import Update

    from synthia.brain.transports.telegram import TelegramTransport

    if not cfg.telegram_allowed_users:
        logger.warning("no allowed users configured; every Telegram message will be ignored")
    work_dir = cfg.state_dir / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    speech = Speech(cfg.language, cfg.voice, cfg.phrase_hints)
    telegram = TelegramTransport(
        brain=None,
        speech=speech,
        allowed_users=cfg.telegram_allowed_users,
        chat_id=cfg.telegram_chat_id,
        confirm_timeout_s=cfg.confirm_timeout_s,
        work_dir=work_dir,
        desk=desk,
    )
    router = ConfirmRouter(desk, telegram)
    brain = Brain(cfg, router.confirm)
    router.brain = desk.brain = telegram.brain = brain
    app = telegram.build_app(cfg.telegram_token)
    logger.info("Synthia brain serving Telegram and the desk")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0
