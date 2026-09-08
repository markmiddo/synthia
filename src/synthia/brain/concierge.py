"""The concierge: one warm Claude Agent SDK session that talks and dispatches jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import warnings
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Protocol

from claude_agent_sdk import (
    CanUseToolShadowedWarning,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ResultMessage,
    StreamEvent,
)

from synthia.brain.config import BrainConfig
from synthia.brain.gate import Confirmer, make_can_use_tool
from synthia.brain.job_tools import build_jobs_server
from synthia.brain.jobs import JobFinished, JobManager, JobRecord, JobStore, Runner, claude_runner
from synthia.brain.persona import build_system_prompt

logger = logging.getLogger(__name__)

# Our allowed_tools intentionally allowlists read-only tools that bypass can_use_tool;
# that's expected here, not a misconfiguration, so silence the SDK's warning about it.
warnings.filterwarnings("ignore", category=CanUseToolShadowedWarning)

HANDOVER_PROMPT = (
    "This session is closing for the day. Write a five-line handover for tomorrow's "
    "session: what we worked on, anything unfinished, anything to remember. Plain text."
)

# How long to wait for a leftover turn's ResultMessage to arrive after interrupting it.
DRAIN_TIMEOUT_S = 15

# How long to wait before retrying a job event whose delivery turn failed.
EVENT_RETRY_DELAY_S = 30


class ClientLike(Protocol):
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def query(self, prompt: str, session_id: str = "default") -> None: ...
    async def interrupt(self) -> None: ...
    def receive_response(self) -> AsyncIterator[Any]: ...


ClientFactory = Callable[[ClaudeAgentOptions], ClientLike]


@dataclass
class SpokenEvent:
    job: JobRecord
    text: str


def _delta_text(message: Any) -> str | None:
    if not isinstance(message, StreamEvent) or message.parent_tool_use_id:
        return None
    ev = message.event
    if ev.get("type") != "content_block_delta":
        return None
    delta = ev.get("delta") or {}
    if delta.get("type") != "text_delta":
        return None
    return str(delta.get("text", ""))


class Brain:
    def __init__(
        self,
        config: BrainConfig,
        confirm: Confirmer,
        client_factory: ClientFactory | None = None,
        runner: Runner | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.config = config
        self.confirm = confirm
        self._factory: ClientFactory = client_factory or (lambda o: ClaudeSDKClient(options=o))
        self._today = today
        self.session_id: str | None = None
        self._session_date: str | None = None
        self._client: ClientLike | None = None
        self._lock = asyncio.Lock()
        # Serialises concurrent drain attempts so only one ever reads the stream.
        self._drain_lock = asyncio.Lock()
        # A query has been sent and its ResultMessage has not yet been seen.
        self._in_flight: bool = False
        # A send() generator body is currently the one consuming the stream.
        self._reader_active: bool = False
        self._job_events: asyncio.Queue[JobFinished] = asyncio.Queue()
        config.state_dir.mkdir(parents=True, exist_ok=True)
        self.jobs = JobManager(
            JobStore(config.state_dir / "jobs"),
            self._job_events,
            runner or claude_runner(config.cwd, config.allowed_tools, config.model),
            max_workers=config.max_workers,
            timeout_s=config.job_timeout_s,
        )

    def _require_client(self) -> ClientLike:
        if self._client is None:
            raise RuntimeError("brain not started")
        return self._client

    # ---- session persistence ----

    @property
    def _session_file(self) -> Path:
        return self.config.state_dir / "session.json"

    def _load_session(self) -> None:
        if not self._session_file.exists():
            return
        try:
            data = json.loads(self._session_file.read_text())
        except (OSError, ValueError) as exc:
            logger.warning("Could not read session file %s: %s", self._session_file, exc)
            return
        self.session_id = data.get("session_id")
        self._session_date = data.get("date")

    def _save_session(self) -> None:
        tmp = self._session_file.parent / f"{self._session_file.name}.tmp"
        tmp.write_text(json.dumps({"session_id": self.session_id, "date": self._session_date}))
        os.replace(tmp, self._session_file)

    def _options(self, resume: str | None, handover: str | None) -> ClaudeAgentOptions:
        return ClaudeAgentOptions(
            cwd=str(self.config.cwd),
            setting_sources=["user", "project", "local"],
            system_prompt=build_system_prompt(handover),
            skills="all",
            include_partial_messages=True,
            mcp_servers={"jobs": build_jobs_server(self.jobs)},
            allowed_tools=list(self.config.allowed_tools),
            permission_mode="default",
            can_use_tool=make_can_use_tool(self.confirm),
            model=self.config.model,
            resume=resume,
        )

    async def _open(self, resume: str | None, handover: str | None = None) -> None:
        self._client = self._factory(self._options(resume, handover))
        await self._client.connect()

    # ---- lifecycle ----

    async def start(self) -> None:
        self._load_session()
        await self._open(self.session_id)
        for rec in self.jobs.store.undelivered():
            self._job_events.put_nowait(JobFinished(rec))

    async def stop(self) -> None:
        await self.jobs.shutdown()
        if self._client is not None:
            await self._client.disconnect()
            self._client = None

    async def new_session(self, handover: str | None = None) -> None:
        if self._client is not None:
            await self._client.disconnect()
        self.session_id = None
        self._session_date = self._today().isoformat()
        self._save_session()
        await self._open(None, handover)

    async def _rollover_if_new_day(self) -> None:
        today = self._today().isoformat()
        if self._session_date == today or self.session_id is None:
            self._session_date = self._session_date or today
            return
        try:
            handover = await self._ask(HANDOVER_PROMPT)
        except Exception:
            logger.warning("Handover turn failed; rolling over without one", exc_info=True)
            handover = None
        logger.info("Session rollover to %s", today)
        await self.new_session(handover)

    # ---- turn draining ----

    async def _consume_until_result(self, client: ClientLike) -> None:
        async for message in client.receive_response():
            if isinstance(message, ResultMessage):
                self._note_result(message)
                return

    async def _drain_leftover(self) -> None:
        """Finish an abandoned or interrupted turn so the shared stream is clean
        for the next one."""
        async with self._drain_lock:
            # Re-check inside the lock: a concurrent drain may have already
            # finished this turn while we were waiting for the lock.
            if not self._in_flight:
                return
            client = self._require_client()
            try:
                await client.interrupt()
                await asyncio.wait_for(self._consume_until_result(client), DRAIN_TIMEOUT_S)
            except asyncio.TimeoutError:
                logger.warning("Timed out draining a leftover turn after %ss", DRAIN_TIMEOUT_S)
            finally:
                self._in_flight = False

    # ---- talking ----

    async def _ask(self, prompt: str) -> str:
        client = self._require_client()
        await self._drain_leftover()  # in case a previous turn was abandoned
        await client.query(prompt)
        self._in_flight = True
        self._reader_active = True
        parts: list[str] = []
        fallback = ""
        try:
            async for message in client.receive_response():
                text = _delta_text(message)
                if text:
                    parts.append(text)
                elif isinstance(message, ResultMessage):
                    self._in_flight = False
                    self._note_result(message)
                    fallback = message.result or ""
        finally:
            self._reader_active = False
            if self._in_flight:  # this turn ended abnormally (e.g. an exception)
                await self._drain_leftover()
        return "".join(parts) if parts else fallback

    def _note_result(self, message: ResultMessage) -> None:
        if message.session_id and message.session_id != self.session_id:
            self.session_id = message.session_id
        self._session_date = self._session_date or self._today().isoformat()
        self._save_session()

    async def send(self, text: str) -> AsyncIterator[str]:
        """Stream a reply to `text` as raw text deltas.

        Callers must fully consume this generator, or close it explicitly (e.g. via
        `contextlib.aclosing`), so the turn's ResultMessage gets drained and the
        shared stream stays clean for the next turn.
        """
        async with self._lock:
            await self._rollover_if_new_day()
            client = self._require_client()
            await self._drain_leftover()  # in case a previous turn was abandoned
            await client.query(text)
            self._in_flight = True
            self._reader_active = True
            streamed = False
            try:
                async for message in client.receive_response():
                    delta = _delta_text(message)
                    if delta:
                        streamed = True
                        yield delta
                    elif isinstance(message, ResultMessage):
                        self._in_flight = False
                        self._note_result(message)
                        if not streamed and message.result:
                            yield message.result
            finally:
                self._reader_active = False
                if self._in_flight:  # consumer abandoned us mid-turn
                    await self._drain_leftover()

    async def interrupt(self) -> None:
        if not self._in_flight:
            return
        client = self._require_client()
        if self._reader_active:
            # The live send() loop is still consuming the stream; it will pick up
            # the terminal ResultMessage itself, so don't start a second reader.
            await client.interrupt()
            return
        await self._drain_leftover()

    async def events(self) -> AsyncIterator[SpokenEvent]:
        while True:
            finished = await self._job_events.get()
            rec = finished.job
            prompt = f"[job event] {rec.name} finished ({rec.status}): {rec.summary}"
            try:
                async with self._lock:
                    await self._rollover_if_new_day()
                    text = await self._ask(prompt)
            except Exception:
                logger.exception("Failed to deliver job event for %s", rec.name)
                await self._job_events.put(finished)
                await asyncio.sleep(EVENT_RETRY_DELAY_S)
                continue
            rec.delivered = True
            self.jobs.store.save(rec)
            yield SpokenEvent(rec, text)
