"""Synchronous client for the brain's desk websocket (see brain/transports/desk.py).

Used by the voice app on Right Alt release. A reader thread hands every frame the brain
sends to `on_frame`; `say`, `interrupt` and `confirm_reply` are plain blocking calls.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_PORT = 8766
DEFAULT_TOKEN_FILE = Path.home() / ".local" / "share" / "synthia" / "brain" / "desk.token"
# Wait this long between reconnect attempts (seconds); one entry per retry.
DEFAULT_BACKOFF = (0.5, 1.0, 2.0)
CONNECT_TIMEOUT_S = 3.0

Frame = dict[str, Any]


class BrainUnavailable(Exception):
    """The brain is not running, not reachable, or refused the token."""


class BrainClient:
    def __init__(
        self,
        on_frame: Callable[[Frame], None],
        port: int = DEFAULT_PORT,
        token_file: Path = DEFAULT_TOKEN_FILE,
        backoff: tuple[float, ...] = DEFAULT_BACKOFF,
        host: str = "127.0.0.1",
    ) -> None:
        self.on_frame = on_frame
        self.url = f"ws://{host}:{port}"
        self.token_file = token_file
        self.backoff = backoff
        self._ws: Any = None
        self._reader: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def connected(self) -> bool:
        return self._ws is not None

    def _connect_once(self) -> None:
        try:
            from websockets.exceptions import WebSocketException
            from websockets.sync.client import connect
        except ImportError as e:
            raise BrainUnavailable("websockets is not installed") from e

        try:
            token = self.token_file.read_text().strip()
        except OSError as e:
            raise BrainUnavailable(f"no desk token at {self.token_file}") from e
        try:
            ws = connect(self.url, open_timeout=CONNECT_TIMEOUT_S)
            ws.send(json.dumps({"type": "auth", "token": token}))
            first = json.loads(ws.recv(timeout=CONNECT_TIMEOUT_S))
        except (OSError, WebSocketException, ValueError, TimeoutError) as e:
            raise BrainUnavailable(f"cannot reach the brain at {self.url}: {e}") from e
        self._ws = ws
        self._reader = threading.Thread(target=self._read_loop, args=(ws,), daemon=True)
        self._reader.start()
        self._dispatch(first)

    def ensure_connected(self) -> None:
        """Connect if needed, retrying with backoff; raise BrainUnavailable if it stays down."""
        with self._lock:
            if self._ws is not None:
                return
            last: BrainUnavailable | None = None
            for delay in (0.0, *self.backoff):
                if delay:
                    time.sleep(delay)
                try:
                    self._connect_once()
                    return
                except BrainUnavailable as e:
                    last = e
            assert last is not None
            raise last

    def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.close()
            except Exception:  # closing a dead socket is not worth reporting
                pass

    def _dispatch(self, frame: Frame) -> None:
        try:
            self.on_frame(frame)
        except Exception:
            logger.exception("brain frame handler failed")

    def _read_loop(self, ws: Any) -> None:
        try:
            for raw in ws:
                try:
                    frame = json.loads(raw)
                except ValueError:
                    continue
                if isinstance(frame, dict):
                    self._dispatch(frame)
        except Exception as e:
            logger.info("brain connection closed: %s", e)
        finally:
            if self._ws is ws:
                self._ws = None
                self._dispatch({"type": "disconnected"})

    def _send(self, frame: Frame) -> None:
        ws = self._ws
        if ws is None:
            raise BrainUnavailable("not connected to the brain")
        try:
            ws.send(json.dumps(frame))
        except Exception as e:
            # Close, don't null: the reader thread owns the connection state and will
            # dispatch "disconnected" exactly once when the socket ends.
            try:
                ws.close()
            except Exception:
                pass
            raise BrainUnavailable(f"lost the brain connection: {e}") from e

    def say(self, text: str) -> None:
        self.ensure_connected()
        self._send({"type": "say", "text": text})

    def interrupt(self) -> None:
        if self._ws is not None:
            self._send({"type": "interrupt"})

    def confirm_reply(self, confirm_id: str, yes: bool) -> None:
        self._send({"type": "confirm_reply", "id": confirm_id, "yes": yes})
