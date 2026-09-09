"""Telegram transport: voice notes in, voice notes out, job events pushed."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    HAS_TELEGRAM = True
except ImportError:  # pragma: no cover - only hit without the `brain` extra
    HAS_TELEGRAM = False

from synthia.brain.config import BrainConfig

logger = logging.getLogger(__name__)

_YES = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|go ahead|do it|approved)\b", re.IGNORECASE)

# Telegram caps voice message captions at 1024 characters.
CAPTION_LIMIT = 1024

# How long to wait before retrying an event we could not push, or restarting a crashed pump.
EVENT_RETRY_DELAY_S = 30

# python-telegram-bot's Application is generic over six type parameters; we don't
# customise any of them, so spell them out as Any rather than reach for # type: ignore.
# Only a type alias, so it stays resolvable when the package is not installed.
if TYPE_CHECKING:
    from telegram.ext import Application as _Application

    TelegramApp = _Application[Any, Any, Any, Any, Any, Any]
else:
    TelegramApp = Any


def is_yes(text: str) -> bool:
    return bool(_YES.search(text or ""))


def _truncate_caption(text: str) -> str:
    if len(text) <= CAPTION_LIMIT:
        return text
    return text[: CAPTION_LIMIT - 1].rstrip() + "…"


class TelegramTransport:
    def __init__(
        self,
        brain: Any,
        speech: Any,
        allowed_users: list[int],
        chat_id: int | None,
        confirm_timeout_s: int,
        work_dir: Path,
    ) -> None:
        self.brain = brain
        self.speech = speech
        self.allowed_users = set(allowed_users)
        self.chat_id = chat_id
        self.confirm_timeout_s = confirm_timeout_s
        self.work_dir = work_dir
        self.bot: Any = None
        self._pending_confirm: asyncio.Future[bool] | None = None
        self._pump_task: asyncio.Task[None] | None = None

    # ---- helpers ----

    def _authorised(self, update: Any) -> bool:
        user = getattr(update, "effective_user", None)
        return user is not None and user.id in self.allowed_users

    async def _speak(self, bot: Any, chat_id: int, text: str) -> None:
        if not text.strip():
            return
        try:
            files = await asyncio.to_thread(self.speech.speak_to_ogg, text, self.work_dir / "out")
        except Exception as e:
            logger.error("TTS failed: %s", e)
            await bot.send_message(chat_id=chat_id, text=text)
            return
        if not files:
            await bot.send_message(chat_id=chat_id, text=text)
            return
        caption = _truncate_caption(text)
        for i, path in enumerate(files):
            try:
                with open(path, "rb") as f:
                    await bot.send_voice(
                        chat_id=chat_id, voice=f, caption=caption if i == 0 else None
                    )
            finally:
                path.unlink(missing_ok=True)

    async def _handle_text(self, update: Any, context: Any, text: str) -> None:
        chat_id = update.effective_chat.id
        if self.chat_id is None:
            self.chat_id = chat_id
        if self._pending_confirm is not None and not self._pending_confirm.done():
            answer = is_yes(text)
            self._pending_confirm.set_result(answer)
            if not answer and update.message is not None:
                await update.message.reply_text("Taken as no.")
            return
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.RECORD_VOICE)
        t0 = time.monotonic()
        chunks = [c async for c in self.brain.send(text)]
        reply = "".join(chunks).strip()
        logger.info(
            "turn: in=%d chars out=%d chars %.1fs", len(text), len(reply), time.monotonic() - t0
        )
        await self._speak(context.bot, chat_id, reply or "I did not get a reply. Try again?")

    # ---- handlers ----

    async def on_text(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message or not update.message.text:
            return
        await self._handle_text(update, context, update.message.text.strip())

    async def on_voice(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message or not update.message.voice:
            return
        chat_id = update.effective_chat.id
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        tg_file = await update.message.voice.get_file()
        with tempfile.NamedTemporaryFile(suffix=".ogg", dir=self.work_dir, delete=False) as f:
            ogg_path = Path(f.name)
        try:
            await tg_file.download_to_drive(str(ogg_path))
            try:
                text = await asyncio.to_thread(self.speech.transcribe_ogg, ogg_path)
            except Exception as e:
                logger.error("STT failed: %s", e)
                await update.message.reply_text("Cloud speech is down. Type it instead?")
                return
        finally:
            ogg_path.unlink(missing_ok=True)
        if not text.strip():
            await update.message.reply_text("Couldn't make that out. Say it again?")
            return
        await self._handle_text(update, context, text)

    async def on_stop(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message:
            return
        await self.brain.interrupt()
        await update.message.reply_text("Stopped.")

    async def on_new(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message:
            return
        await self.brain.new_session()
        await update.message.reply_text("Fresh session.")

    async def on_jobs(self, update: Any, context: Any) -> None:
        if not self._authorised(update) or not update.message:
            return
        jobs = self.brain.jobs.list_jobs()
        text = "No jobs." if not jobs else "\n".join(f"{j.name}: {j.status}" for j in jobs)
        await update.message.reply_text(text)

    async def on_error(self, update: Any, context: Any) -> None:
        logger.exception("unhandled error in telegram handler", exc_info=context.error)
        if self.chat_id is not None:
            try:
                await context.bot.send_message(
                    chat_id=self.chat_id, text="Something went wrong on my end. Try again?"
                )
            except Exception as e:
                logger.error("failed to notify chat of error: %s", e)

    # ---- confirmation (Confirmer for the brain's gate) ----

    async def confirm(self, question: str) -> bool:
        if self.bot is None or self.chat_id is None:
            logger.warning("confirm requested with no chat; denying: %s", question)
            return False
        if self._pending_confirm is not None and not self._pending_confirm.done():
            # Overwriting the future would strand the first waiter forever.
            logger.warning("confirmation already pending; denying: %s", question)
            return False
        loop = asyncio.get_running_loop()
        self._pending_confirm = loop.create_future()
        await self._speak(self.bot, self.chat_id, f"I want to {question}. Say yes to confirm.")
        try:
            return await asyncio.wait_for(self._pending_confirm, self.confirm_timeout_s)
        except asyncio.TimeoutError:
            await self._speak(self.bot, self.chat_id, "No confirmation, so I did not do it.")
            return False
        finally:
            self._pending_confirm = None

    # ---- job events ----

    async def pump_events(self, bot: Any) -> None:
        """Push finished-job events as voice notes, for the life of the process.

        Restarts itself if `events()` raises: the pump is the only thing that tells Mark
        a job finished, so it must outlive a bad turn.
        """
        while True:
            try:
                async for ev in self.brain.events():
                    try:
                        if self.chat_id is None:
                            # No chat yet (Mark has not messaged since boot); keep it.
                            logger.warning("job event with no chat id; requeuing %s", ev.job.id)
                            self.brain.requeue(ev.job)
                            await asyncio.sleep(EVENT_RETRY_DELAY_S)
                            continue
                        await self._speak(bot, self.chat_id, ev.text or f"{ev.job.name} finished.")
                        self.brain.ack(ev.job)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        logger.exception("event push failed")
                        continue
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("event pump crashed; restarting")
                await asyncio.sleep(EVENT_RETRY_DELAY_S)

    # ---- wiring ----

    def build_app(self, token: str) -> TelegramApp:
        app: TelegramApp = (
            Application.builder()
            .token(token)
            .concurrent_updates(True)
            .post_init(self._post_init)
            .post_shutdown(self._post_shutdown)
            .build()
        )
        app.add_handler(CommandHandler("stop", self.on_stop))
        app.add_handler(CommandHandler("new", self.on_new))
        app.add_handler(CommandHandler("jobs", self.on_jobs))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_handler(MessageHandler(filters.VOICE, self.on_voice))
        app.add_error_handler(self.on_error)
        return app

    async def _post_init(self, app: TelegramApp) -> None:
        self.bot = app.bot
        await self.brain.start()
        # post_init runs before the application is "running", so use a plain
        # asyncio task and keep the reference; cancelled in _post_shutdown.
        self._pump_task = asyncio.create_task(self.pump_events(app.bot))

    async def _post_shutdown(self, app: TelegramApp) -> None:
        if self._pump_task is not None:
            self._pump_task.cancel()
            try:
                await self._pump_task
            except asyncio.CancelledError:
                pass
        await self.brain.stop()


def run_telegram(cfg: BrainConfig) -> int:
    from synthia.brain.cli import pull_repos
    from synthia.brain.concierge import Brain
    from synthia.brain.speech import Speech

    if not HAS_TELEGRAM:
        raise RuntimeError(
            "python-telegram-bot is not installed; install the brain extra with "
            'pip install -e ".[brain]"'
        )
    if not cfg.telegram_token:
        print("BRAIN_TELEGRAM_TOKEN is not set")
        return 2
    if not cfg.telegram_allowed_users:
        logger.warning("no allowed users configured; every message will be ignored")
    pull_repos(cfg.repos)
    work_dir = cfg.state_dir / "audio"
    work_dir.mkdir(parents=True, exist_ok=True)
    speech = Speech(cfg.language, cfg.voice, cfg.phrase_hints)
    transport = TelegramTransport(
        brain=None,
        speech=speech,
        allowed_users=cfg.telegram_allowed_users,
        chat_id=cfg.telegram_chat_id,
        confirm_timeout_s=cfg.confirm_timeout_s,
        work_dir=work_dir,
    )
    transport.brain = Brain(cfg, transport.confirm)
    app = transport.build_app(cfg.telegram_token)
    logger.info("Synthia brain listening on Telegram")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
    return 0
