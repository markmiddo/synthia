"""Desk voice through the brain: stream the reply, speak it sentence by sentence.

`DeskVoice.ask(text)` sends the transcript to the brain. Reply deltas are buffered into
sentences and each one is spoken with the existing TTS as soon as it completes, so Synthia
starts talking while the rest of the answer is still being written.
"""

from __future__ import annotations

import logging
import queue
import re
import threading
from typing import Any, Callable

from synthia.brain_client import BrainClient, BrainUnavailable, Frame

logger = logging.getLogger(__name__)

UNREACHABLE_LINE = "I can't reach my brain."
ERROR_LINE = "Something went wrong on my side."
# Sentence end: . ! ? (optionally followed by a closing quote or bracket) then whitespace.
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")
# Shorter than this and the "sentence" is probably an abbreviation or a stray fragment.
MIN_SENTENCE_CHARS = 12
_YES = re.compile(r"\b(yes|yep|yeah|confirm|confirmed|go ahead|do it|approved)\b", re.IGNORECASE)


class SentenceBuffer:
    """Turn a stream of text deltas into complete sentences."""

    def __init__(self) -> None:
        self._buf = ""

    def push(self, delta: str) -> list[str]:
        self._buf += delta
        out: list[str] = []
        start = 0
        for m in _BOUNDARY.finditer(self._buf):
            sentence = self._buf[start : m.end()].strip()
            if len(sentence) < MIN_SENTENCE_CHARS and "\n" not in m.group():
                continue  # too short to stand alone: keep accumulating
            if sentence:
                out.append(sentence)
            start = m.end()
        self._buf = self._buf[start:]
        return out

    def flush(self) -> str | None:
        rest, self._buf = self._buf.strip(), ""
        return rest or None


class DeskVoice:
    def __init__(
        self,
        client_factory: Callable[[Callable[[Frame], None]], BrainClient],
        speak: Callable[[str], Any],
        stop_speaking: Callable[[], Any],
        on_state: Callable[[str], None] | None = None,
    ) -> None:
        self.client = client_factory(self._on_frame)
        self._speak = speak
        self._stop_speaking = stop_speaking
        self._on_state = on_state or (lambda state: None)
        self._buffer = SentenceBuffer()
        self._lines: queue.Queue[tuple[int, str] | None] = queue.Queue()
        self._pending_confirm: str | None = None
        self._turn_active = False  # a turn is in flight at the brain
        self._speaking = False  # a line is being spoken
        self._down_announced = False
        self._lock = threading.Lock()
        # Replies for turns that were interrupted must be dropped, not spoken.
        self._epoch = 0
        # After an interrupt the brain still sends the tail of the old reply; skip it.
        self._discarding = False
        self._worker = threading.Thread(target=self._speak_loop, daemon=True)
        self._worker.start()

    # ---- state ----

    @property
    def busy(self) -> bool:
        return self._turn_active or self._speaking or not self._lines.empty()

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_confirm is not None

    # ---- outgoing ----

    def ask(self, text: str) -> None:
        """Send a transcript. If the brain asked a yes/no question, this is the answer."""
        if self._pending_confirm is not None:
            confirm_id, self._pending_confirm = self._pending_confirm, None
            try:
                self.client.confirm_reply(confirm_id, bool(_YES.search(text)))
            except BrainUnavailable:
                self._announce_down()
            return
        try:
            self.client.say(text)
        except BrainUnavailable as e:
            logger.warning("brain unreachable: %s", e)
            self._announce_down()
            return
        self._down_announced = False
        self._turn_active = True

    def interrupt(self) -> None:
        """Stop talking now and tell the brain to stop the turn."""
        with self._lock:
            self._epoch += 1
            self._discarding = self._turn_active
            self._buffer = SentenceBuffer()
            self._drain_queue()
        self._stop_speaking()
        try:
            self.client.interrupt()
        except BrainUnavailable:
            pass
        self._turn_active = False

    def close(self) -> None:
        self._lines.put(None)
        self.client.close()

    # ---- incoming ----

    def _enqueue(self, text: str) -> None:
        self._lines.put((self._epoch, text))

    def _on_frame(self, frame: Frame) -> None:
        kind = frame.get("type")
        if self._discarding and kind in ("delta", "error"):
            return
        if kind == "delta":
            with self._lock:
                for sentence in self._buffer.push(str(frame.get("text", ""))):
                    self._enqueue(sentence)
        elif kind == "reply_done":
            with self._lock:
                rest = self._buffer.flush()
                if rest and not self._discarding:
                    self._enqueue(rest)
            self._discarding = False
            self._turn_active = False
        elif kind == "event":
            text = str(frame.get("text", "")).strip()
            if text:
                self._enqueue(text)
        elif kind == "confirm":
            self._pending_confirm = str(frame.get("id", ""))
            self._enqueue(f"I want to {frame.get('question', 'do something')}. Say yes to confirm.")
        elif kind == "error":
            logger.error("brain error: %s", frame.get("text"))
            self._enqueue(ERROR_LINE)
        elif kind == "disconnected":
            self._turn_active = False
            self._discarding = False

    # ---- speech ----

    def _drain_queue(self) -> None:
        try:
            while True:
                self._lines.get_nowait()
        except queue.Empty:
            pass

    def _announce_down(self) -> None:
        if self._down_announced:
            return
        self._down_announced = True
        self._enqueue(UNREACHABLE_LINE)

    def _speak_loop(self) -> None:
        while True:
            item = self._lines.get()
            if item is None:
                return
            epoch, line = item
            self._speaking = True
            self._on_state("speaking")
            try:
                if epoch == self._epoch:
                    self._speak(line)
            except Exception:
                logger.exception("speaking failed")
            finally:
                self._speaking = False
            if self._lines.empty() and not self._turn_active:
                self._on_state("ready")
