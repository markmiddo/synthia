"""Desk transport: a localhost websocket the Synthia HUD and the desktop voice app talk to.

Frames are JSON, one per websocket message. The first frame from a client must be
`{"type":"auth","token":...}` where the token is the one written to `desk.token` at start.

client to brain:
    {"type":"say","text":...}  {"type":"interrupt"}  {"type":"confirm_reply","id":...,"yes":bool}
    {"type":"presence","active":true|false}   (HUD window visible/focused; every 2 minutes)
brain to client (broadcast to every authenticated client):
    {"type":"state","value":"idle|thinking|speaking"}  {"type":"delta","text":...}
    {"type":"reply_done","text":...}  {"type":"event","text":...}
    {"type":"confirm","id":...,"question":...}  {"type":"error","text":...}
    {"type":"confirm_done","id":...,"approved":true|false|null}   (null: nobody answered)
    {"type":"inbox","id":...,"title":...}   (new item in the HUD Inbox; an "event" frame with
                                              the spoken line follows it)
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
AUTH_TIMEOUT_S = 5.0
# Mark counts as at his desk for this long after the HUD's last "active" presence frame,
# or after his last desk voice turn.
PRESENCE_TTL_S = 10 * 60
VOICE_TTL_S = 30 * 60
# Close codes in the private-use range.
CLOSE_UNAUTHORISED = 4401
# Frames from a client are tiny JSON; refuse anything large.
MAX_FRAME_BYTES = 1 << 20


def write_token(path: Path) -> str:
    """Create a fresh random token and write it to `path` with mode 600."""
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return token


class DeskTransport:
    def __init__(
        self,
        brain: Any,
        port: int,
        token_file: Path,
        confirm_timeout_s: int,
        host: str = HOST,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.brain = brain
        self._clock = clock
        self._presence_at: float | None = None
        self._voice_at: float | None = None
        self.port = port
        self.host = host
        self.token_file = token_file
        self.confirm_timeout_s = confirm_timeout_s
        self.token = ""
        self._server: Server | None = None
        self._clients: set[ServerConnection] = set()
        self._pending: dict[str, asyncio.Future[bool | None]] = {}
        # How the current question closed when another transport answered it first.
        self._resolution: bool | None = None
        self._turns: set[asyncio.Task[None]] = set()
        self.state = "idle"

    @property
    def has_clients(self) -> bool:
        return bool(self._clients)

    @property
    def is_present(self) -> bool:
        """Mark is at his desk: a client is connected and he showed up recently.

        Recently means an active presence frame within PRESENCE_TTL_S, or a desk voice turn
        within VOICE_TTL_S. A presence frame with active=false (window hidden or blurred)
        withdraws the presence claim; a recent voice turn still counts.
        """
        if not self._clients:
            return False
        now = self._clock()
        if self._presence_at is not None and now - self._presence_at <= PRESENCE_TTL_S:
            return True
        return self._voice_at is not None and now - self._voice_at <= VOICE_TTL_S

    @property
    def bound_port(self) -> int:
        """The port actually listening (differs from `port` when that was 0)."""
        if self._server is None:
            return self.port
        return int(next(iter(self._server.sockets)).getsockname()[1])

    # ---- lifecycle ----

    async def start(self) -> None:
        self.token = write_token(self.token_file)
        self._server = await serve(
            self._handle, self.host, self.port, max_size=MAX_FRAME_BYTES, ping_interval=20
        )
        logger.info("Synthia desk listening on ws://%s:%d", self.host, self.bound_port)

    async def stop(self) -> None:
        for task in list(self._turns):
            task.cancel()
        for task in list(self._turns):
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result(None)
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        with contextlib.suppress(OSError):
            self.token_file.unlink()

    # ---- sending ----

    async def broadcast(self, frame: dict[str, Any]) -> None:
        data = json.dumps(frame)
        for ws in list(self._clients):
            try:
                await ws.send(data)
            except ConnectionClosed:
                self._clients.discard(ws)

    async def _set_state(self, value: str) -> None:
        self.state = value
        await self.broadcast({"type": "state", "value": value})

    async def push_event(self, text: str) -> None:
        """Deliver a finished-job event to every connected client."""
        await self.broadcast({"type": "event", "text": text})

    async def push_inbox(self, item_id: str, title: str) -> None:
        """Tell every connected client a new item is waiting in the Inbox."""
        await self.broadcast({"type": "inbox", "id": item_id, "title": title})

    # ---- confirmation (Confirmer for the brain's gate) ----

    async def ask(self, question: str) -> bool | None:
        """Ask every connected client. True/False is an answer; None means nobody answered
        (no client, every client dropped, timed out, or the question was cancelled)."""
        if not self._clients:
            logger.warning("desk confirm with no client: %s", question)
            return None
        cid = uuid.uuid4().hex[:8]
        self._resolution = None
        fut: asyncio.Future[bool | None] = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        approved: bool | None = None
        try:
            await self.broadcast({"type": "confirm", "id": cid, "question": question})
            approved = await asyncio.wait_for(fut, self.confirm_timeout_s)
        except asyncio.TimeoutError:
            approved = None
        finally:
            self._pending.pop(cid, None)
            if approved is None and self._resolution is not None:
                # Another transport answered first: the card closes with the real answer.
                approved = self._resolution
            # Tell every client the question is closed, so a stale card cannot linger and
            # swallow the next utterance as its answer.
            await self.broadcast({"type": "confirm_done", "id": cid, "approved": approved})
        return approved

    def resolved(self, approved: bool | None) -> None:
        """The Router closed this question: another transport answered (None: nobody)."""
        self._resolution = approved

    async def confirm(self, question: str) -> bool:
        approved = bool(await self.ask(question))
        journal = getattr(self.brain, "journal", None)
        if journal is not None:
            journal.confirmation(question, approved)
        return approved

    # ---- connection handling ----

    async def _authenticate(self, ws: ServerConnection) -> bool:
        try:
            raw = await asyncio.wait_for(ws.recv(), AUTH_TIMEOUT_S)
            frame = json.loads(raw)
        except (asyncio.TimeoutError, ValueError, ConnectionClosed):
            return False
        supplied = frame.get("token") if isinstance(frame, dict) else None
        return (
            isinstance(frame, dict)
            and frame.get("type") == "auth"
            and isinstance(supplied, str)
            and hmac.compare_digest(supplied.encode(), self.token.encode())
        )

    async def _handle(self, ws: ServerConnection) -> None:
        if not await self._authenticate(ws):
            await ws.close(CLOSE_UNAUTHORISED, "unauthorised")
            return
        self._clients.add(ws)
        try:
            # The first state frame doubles as the "you are authenticated" ack.
            await ws.send(json.dumps({"type": "state", "value": self.state}))
            async for raw in ws:
                await self._on_frame(raw)
        except ConnectionClosed:
            pass
        finally:
            self._clients.discard(ws)
            if not self._clients:
                # Nobody is left who could answer: release the brain instead of making it
                # wait out the full timeout while holding its turn lock.
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_result(None)

    async def _on_frame(self, raw: str | bytes) -> None:
        try:
            frame = json.loads(raw)
        except ValueError:
            logger.warning("desk: dropped a non-JSON frame")
            return
        kind = frame.get("type") if isinstance(frame, dict) else None
        if kind == "say":
            text = str(frame.get("text", "")).strip()
            if text:
                self._voice_at = self._clock()
                task = asyncio.create_task(self._run_turn(text))
                self._turns.add(task)
                task.add_done_callback(self._turns.discard)
        elif kind == "presence":
            self._presence_at = self._clock() if frame.get("active") is True else None
        elif kind == "interrupt":
            await self.brain.interrupt("desk")
        elif kind == "confirm_reply":
            fut = self._pending.get(str(frame.get("id", "")))
            if fut is not None and not fut.done():
                fut.set_result(bool(frame.get("yes")))
        else:
            logger.warning("desk: ignored frame of type %r", kind)

    async def _run_turn(self, text: str) -> None:
        await self._set_state("thinking")
        chunks: list[str] = []
        started = time.monotonic()
        try:
            async with contextlib.aclosing(self.brain.send(text, origin="desk")) as stream:
                async for delta in stream:
                    if not chunks:
                        logger.info(
                            "desk turn: say to first delta %.2fs", time.monotonic() - started
                        )
                        await self._set_state("speaking")
                    chunks.append(delta)
                    await self.broadcast({"type": "delta", "text": delta})
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("desk turn failed")
            await self.broadcast({"type": "error", "text": f"The turn failed: {e}"})
        await self.broadcast({"type": "reply_done", "text": "".join(chunks).strip()})
        await self._set_state("idle")
