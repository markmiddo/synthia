"""Telegram transport: voice notes in, voice notes out, job events pushed."""

from __future__ import annotations

import asyncio
import logging
import re
import tempfile
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

try:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.error import TimedOut
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    HAS_TELEGRAM = True
except ImportError:  # pragma: no cover - only hit without the `brain` extra
    HAS_TELEGRAM = False

    class TimedOut(Exception):  # type: ignore[no-redef]
        """Stand-in so the except clause below still compiles without the extra."""


from synthia.brain.config import BrainConfig

logger = logging.getLogger(__name__)

_YES = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|go ahead|do it|approved)\b", re.IGNORECASE)

# Telegram caps voice message captions at 1024 characters.
CAPTION_LIMIT = 1024

# How long to wait before retrying an event we could not push, or restarting a crashed pump.
EVENT_RETRY_DELAY_S = 30
# Voice uploads are slow on a phone-tethered or busy link; the library default is 5 s.
VOICE_TIMEOUT_S = 60
# Each retry re-synthesises the voice note (paid TTS), so a push that keeps failing is
# given up after this many attempts; the job's result is already in the walk journal.
MAX_EVENT_PUSH_ATTEMPTS = 5

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
        desk: Any = None,
        deliver_event: (
            Callable[[Any, Callable[[str], Awaitable[None]] | None], Awaitable[bool]] | None
        ) = None,
    ) -> None:
        self.brain = brain
        # When serving both transports the desk server's life is tied to this application's.
        self.desk = desk
        # Routes each job event to the desk or, when Mark is away, to a short text here.
        self.deliver_event = deliver_event
        self.speech = speech
        self.allowed_users = set(allowed_users)
        self.chat_id = chat_id
        self.confirm_timeout_s = confirm_timeout_s
        self.work_dir = work_dir
        self.bot: Any = None
        self._pending_confirm: asyncio.Future[bool] | None = None
        # How the current question closed when another transport answered it first.
        self._resolution: bool | None = None
        # Failed Telegram pushes per job id, so a dead chat cannot retry forever.
        self._push_failures: dict[str, int] = {}
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
                        chat_id=chat_id,
                        voice=f,
                        caption=caption if i == 0 else None,
                        read_timeout=VOICE_TIMEOUT_S,
                        write_timeout=VOICE_TIMEOUT_S,
                    )
            except TimedOut:
                # Telegram usually has the upload by the time the response times out; a retry
                # sends Mark the same note again (13 Oct: three copies). Treat it as sent.
                logger.warning("voice note timed out waiting for Telegram; assuming delivered")
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
        chunks = [c async for c in self.brain.send(text, origin="telegram")]
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
        await self.brain.interrupt("telegram")
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

    async def ask(self, question: str) -> bool | None:
        """Ask in the chat. True/False is an answer; None means nobody answered (no chat,
        another question pending, timed out, or the question was cancelled)."""
        if self.bot is None or self.chat_id is None:
            logger.warning("confirm requested with no chat: %s", question)
            return None
        if self._pending_confirm is not None and not self._pending_confirm.done():
            # Overwriting the future would strand the first waiter forever.
            logger.warning("confirmation already pending: %s", question)
            return None
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bool] = loop.create_future()
        self._pending_confirm = fut
        self._resolution = None
        try:
            await self._speak(self.bot, self.chat_id, f"I want to {question}. Say yes to confirm.")
            return await asyncio.wait_for(fut, self.confirm_timeout_s)
        except asyncio.TimeoutError:
            await self._speak(self.bot, self.chat_id, "No confirmation, so I did not do it.")
            return None
        except asyncio.CancelledError:
            # Closed elsewhere (the desk answered, or the turn ended). Say so in text, or a
            # late "yes" here would reach the model as a fresh request.
            if self._pending_confirm is fut:
                self._pending_confirm = None
            await self._notify_closed()
            raise
        finally:
            if self._pending_confirm is fut:
                self._pending_confirm = None

    def resolved(self, approved: bool | None) -> None:
        """The Router closed this question: another transport answered (None: nobody)."""
        self._resolution = approved

    async def _notify_closed(self) -> None:
        if self.bot is None or self.chat_id is None:
            return
        if self._resolution is None:
            text = "That question was cancelled, so nothing was done."
        else:
            text = f"Answered at the desk: {'approved' if self._resolution else 'declined'}."
        try:
            await asyncio.wait_for(self.bot.send_message(chat_id=self.chat_id, text=text), 5)
        except Exception as e:
            logger.error("failed to tell the chat the question closed: %s", e)

    async def confirm(self, question: str) -> bool:
        approved = bool(await self.ask(question))
        journal = getattr(self.brain, "journal", None)
        if journal is not None:
            journal.confirmation(question, approved)
        return approved

    # ---- job events ----

    async def _send_text(self, bot: Any, chat_id: int, text: str) -> None:
        """One short plain text message. A timeout counts as sent: Telegram usually has it."""
        try:
            await bot.send_message(chat_id=chat_id, text=text)
        except TimedOut:
            logger.warning("text message timed out waiting for Telegram; assuming delivered")

    async def pump_events(self, bot: Any) -> None:
        """Route finished-job events, for the life of the process.

        Mark at his desk hears them there; away, he gets one short text message here.

        Restarts itself if `events()` raises: the pump is the only thing that tells Mark
        a job finished, so it must outlive a bad turn.
        """
        while True:
            try:
                async for ev in self.brain.events():
                    try:
                        chat_id = self.chat_id
                        away = None
                        if chat_id is not None:

                            async def away(text: str, chat_id: int = chat_id) -> None:
                                await self._send_text(bot, chat_id, text)

                        route = self.deliver_event
                        if route is None:
                            from synthia.brain.routing import Router

                            route = Router(self.desk, self).deliver_event
                        if not await route(ev, away):
                            logger.warning("no way to deliver %s yet; requeuing", ev.job.id)
                            self.brain.requeue(ev.job)
                            await asyncio.sleep(EVENT_RETRY_DELAY_S)
                            continue
                        self._push_failures.pop(ev.job.id, None)
                        self.brain.ack(ev.job)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Keep the event: its spoken text is cached, so the retry costs no
                        # model turn, and the router remembers the desk already has its copy.
                        failures = self._push_failures.get(ev.job.id, 0) + 1
                        if failures >= MAX_EVENT_PUSH_ATTEMPTS:
                            logger.exception(
                                "event push failed %d times; giving up on %s", failures, ev.job.id
                            )
                            self._push_failures.pop(ev.job.id, None)
                            self.brain.ack(ev.job)
                            continue
                        self._push_failures[ev.job.id] = failures
                        logger.exception("event push failed; requeuing %s", ev.job.id)
                        self.brain.requeue(ev.job)
                        await asyncio.sleep(EVENT_RETRY_DELAY_S)
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
        if self.desk is not None:
            await self.desk.start()
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
        if self.desk is not None:
            await self.desk.stop()
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
