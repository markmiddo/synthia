"""`synthia-brain serve`: Telegram and the desk websocket on one concierge, one process."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
from typing import Any

from synthia.brain.config import BrainConfig
from synthia.brain.routing import Router

logger = logging.getLogger(__name__)


async def _pump_desk_events(brain: Any, router: Router) -> None:
    """Desk-only mode: the desk is the only transport, so an event with no client waits."""
    from synthia.brain.concierge import EVENT_RETRY_DELAY_S

    while True:
        try:
            async for ev in brain.events():
                if await router.deliver_event(ev):
                    brain.ack(ev.job)
                else:
                    # The push failed: keep the event (its spoken text is cached) and retry.
                    brain.requeue(ev.job)
                    await asyncio.sleep(EVENT_RETRY_DELAY_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("desk event pump crashed; restarting")
            await asyncio.sleep(EVENT_RETRY_DELAY_S)


async def _serve_desk_only(desk: Any, brain: Any, router: Router) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await brain.start()
    await desk.start()
    pump = asyncio.create_task(_pump_desk_events(brain, router))
    try:
        await stop.wait()
    finally:
        pump.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump
        await desk.stop()
        await brain.stop()


def _attach_squad_tail(brain: Any, cfg: BrainConfig) -> None:
    """Have the brain follow squad done signals; the offset lives in the brain state dir."""
    from synthia.squads.engine import EVENTS_FILE
    from synthia.squads.events import EventTail
    from synthia.squads.registry import DEFAULT_ROOT

    brain.squad_tail = EventTail(DEFAULT_ROOT / EVENTS_FILE, cfg.state_dir / "squad_events.offset")


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
        router = Router(desk, None)
        brain = Brain(cfg, router.confirm)
        _attach_squad_tail(brain, cfg)
        router.brain = desk.brain = brain
        asyncio.run(_serve_desk_only(desk, brain, router))
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
    router = Router(desk, telegram)
    telegram.deliver_event = router.deliver_event
    brain = Brain(cfg, router.confirm)
    _attach_squad_tail(brain, cfg)
    router.brain = desk.brain = telegram.brain = brain
    app = telegram.build_app(cfg.telegram_token)
    logger.info("Synthia brain serving Telegram and the desk")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0
