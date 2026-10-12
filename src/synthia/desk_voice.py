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
import time
from typing import Any, Callable

from synthia.brain_client import BrainClient, BrainUnavailable, Frame

logger = logging.getLogger(__name__)

UNREACHABLE_LINE = "I can't reach my brain."
STILL_DOWN_LINE = "Still can't reach my brain."
# Between short "still down" reminders while the brain stays unreachable.
STILL_DOWN_INTERVAL_S = 30.0
ERROR_LINE = "Something went wrong on my side."
# Sentence end: . ! ? (optionally followed by a closing quote or bracket) then whitespace.
_BOUNDARY = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n+")
# Shorter than this and the "sentence" is probably an abbreviation or a stray fragment.
MIN_SENTENCE_CHARS = 12
# If the brain has not started answering this soon after the question, say a short
# acknowledgement so the silence does not feel like she missed it.
ACK_DELAY_S = 0.7
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


class _Ack:
    """A queued pre-rendered acknowledgement (a file path), played instead of synthesised."""

    def __init__(self, path: str) -> None:
        self.path = path


class DeskVoice:
    def __init__(
        self,
        client_factory: Callable[[Callable[[Frame], None]], BrainClient],
        speak: Callable[[str], Any],
        stop_speaking: Callable[[], Any],
        on_state: Callable[[str], None] | None = None,
        ack_source: Callable[[], str | None] | None = None,
        play_ack: Callable[[str], Any] | None = None,
        ack_delay_s: float = ACK_DELAY_S,
    ) -> None:
        self.client = client_factory(self._on_frame)
        self._speak = speak
        self._stop_speaking = stop_speaking
        self._on_state = on_state or (lambda state: None)
        self._buffer = SentenceBuffer()
        self._lines: queue.Queue[tuple[int, str | _Ack] | None] = queue.Queue()
        self._ack_source = ack_source
        self._play_ack = play_ack
        self._ack_delay_s = ack_delay_s
        self._ack_timer: threading.Timer | None = None
        # The brain has started answering this turn (no acknowledgement needed any more).
        self._reply_started = False
        # Timing of the current turn, for the one latency line per turn.
        self._timing: dict[str, float] = {}
        self._playing_reply = False
        # Lines queued or being spoken; the single truth for "is she still talking".
        self._outstanding = 0
        self._state_lock = threading.Lock()
        self._pending_confirm: str | None = None
        self._turn_active = False  # a turn is in flight at the brain
        self._down_announced = False
        self._last_down_notice = 0.0
        # Mark's key is down or his words are in flight: a state report from the previous
        # reply (reply_done, the speaker finishing) must not overwrite "recording".
        self._utterance_open = False
        self._emit_lock = threading.Lock()
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
        return self._turn_active or self._outstanding > 0

    @property
    def awaiting_confirmation(self) -> bool:
        return self._pending_confirm is not None

    # ---- outgoing ----

    def ask(self, text: str, released_at: float | None = None) -> None:
        """Send a transcript. If the brain asked a yes/no question, this is the answer.

        `released_at` is the time.monotonic() of the key release, for the latency log.
        """
        self._close_utterance()
        if self._pending_confirm is not None:
            confirm_id, self._pending_confirm = self._pending_confirm, None
            try:
                self.client.confirm_reply(confirm_id, bool(_YES.search(text)))
            except BrainUnavailable:
                self._fail_unreachable()
                return
            self._down_announced = False
            self._emit("thinking")
            return
        transcript_at = time.monotonic()
        with self._lock:
            self._reply_started = False
            self._timing = {"transcript": transcript_at}
            if released_at is not None:
                self._timing["release"] = released_at
            self._playing_reply = False
            epoch = self._epoch
        try:
            self.client.say(text)
        except BrainUnavailable as e:
            logger.warning("brain unreachable: %s", e)
            self._fail_unreachable()
            return
        self._down_announced = False
        self._turn_active = True
        self._emit("thinking")
        self._arm_ack(epoch)

    # ---- acknowledgement ----

    def _arm_ack(self, epoch: int) -> None:
        if self._ack_source is None or self._play_ack is None:
            return
        self._cancel_ack_timer()
        timer = threading.Timer(self._ack_delay_s, self._maybe_ack, args=(epoch,))
        timer.daemon = True
        self._ack_timer = timer
        timer.start()

    def _cancel_ack_timer(self) -> None:
        timer, self._ack_timer = self._ack_timer, None
        if timer is not None:
            timer.cancel()

    def _maybe_ack(self, epoch: int) -> None:
        """No answer yet: queue the acknowledgement ahead of whatever the reply says."""
        if self._ack_source is None:
            return
        with self._lock:
            if epoch != self._epoch or self._reply_started or not self._turn_active:
                return
            path = self._ack_source()
            if path is None:
                return
            self._timing["ack"] = time.monotonic()
            self._enqueue_locked(_Ack(path))

    def _mark_reply_started(self) -> None:
        """Called under self._lock when the brain's first frame of the turn arrives."""
        if not self._reply_started:
            self._reply_started = True
            self._timing.setdefault("first_delta", time.monotonic())

    def mark_audio_start(self) -> None:
        """The speaker started playing something: log the turn's latency on the first reply audio."""
        with self._lock:
            if not self._playing_reply or "first_audio" in self._timing:
                return
            t = self._timing
            t["first_audio"] = time.monotonic()
            parts = []
            if "release" in t:
                parts.append(f"release to transcript {t['transcript'] - t['release']:.2f}s")
            if "first_delta" in t:
                parts.append(f"transcript to first delta {t['first_delta'] - t['transcript']:.2f}s")
                parts.append(
                    f"first delta to first audio {t['first_audio'] - t['first_delta']:.2f}s"
                )
            parts.append("ack played" if "ack_played" in t else "no ack")
        logger.info("desk turn: %s", ", ".join(parts))

    def end_utterance(self) -> None:
        """The utterance was abandoned (nothing heard, or recording failed): resume state reports."""
        self._close_utterance()
        self._maybe_ready()

    def _close_utterance(self) -> None:
        with self._emit_lock:
            self._utterance_open = False

    def _emit(self, state: str) -> None:
        """Report a state, unless Mark is mid-utterance (his "recording" wins)."""
        with self._emit_lock:
            if self._utterance_open:
                return
            self._on_state(state)

    def _fail_unreachable(self) -> None:
        """A send failed: the turn is gone, so tell Mark and never leave the state on thinking."""
        self._turn_active = False
        self._announce_down()
        self._maybe_ready()

    def begin_utterance(self) -> None:
        """The assistant key went down: she stops talking so Mark can speak.

        While the brain is waiting for a yes or no, only the spoken question is cut off.
        The turn must stay alive (interrupting it would abort the permission request), and
        the next utterance is sent as the answer.
        """
        with self._emit_lock:
            self._utterance_open = True
        if not self.busy:
            return
        if self.awaiting_confirmation:
            with self._lock:
                self._drain_queue()
            self._stop_speaking()
            return
        self.interrupt()

    def interrupt(self) -> None:
        """Stop talking now and tell the brain to stop the turn."""
        self._cancel_ack_timer()
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
        self._pending_confirm = None

    def close(self) -> None:
        self._cancel_ack_timer()
        self._lines.put(None)
        self.client.close()

    # ---- incoming ----

    def _enqueue(self, text: str) -> None:
        self._enqueue_locked(text)

    def _enqueue_locked(self, item: str | _Ack) -> None:
        with self._state_lock:
            self._outstanding += 1
        self._lines.put((self._epoch, item))

    def _maybe_ready(self) -> None:
        """Report "ready" once the turn is over and nothing is left to say."""
        with self._state_lock:
            idle = not self._turn_active and self._outstanding == 0
        if idle:
            self._emit("ready")

    def _on_frame(self, frame: Frame) -> None:
        kind = frame.get("type")
        if self._discarding and kind in ("delta", "error"):
            return
        if kind in ("delta", "event", "confirm", "error", "reply_done"):
            with self._lock:
                self._mark_reply_started()
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
            self._maybe_ready()
        elif kind == "event":
            text = str(frame.get("text", "")).strip()
            if text:
                self._enqueue(text)
        elif kind == "confirm":
            self._pending_confirm = str(frame.get("id", ""))
            self._enqueue(f"I want to {frame.get('question', 'do something')}. Say yes to confirm.")
        elif kind == "confirm_done":
            # The question closed (answered anywhere, timed out, or cancelled): a stale
            # card must not swallow the next thing Mark says.
            if self._pending_confirm == str(frame.get("id", "")):
                self._pending_confirm = None
        elif kind == "error":
            logger.error("brain error: %s", frame.get("text"))
            self._enqueue(ERROR_LINE)
            self._maybe_ready()
        elif kind == "disconnected":
            was_active = self._turn_active
            with self._lock:
                self._buffer = SentenceBuffer()
            self._turn_active = False
            self._discarding = False
            self._pending_confirm = None
            if was_active:
                self._announce_down()
            self._maybe_ready()

    # ---- speech ----

    def _drain_queue(self) -> None:
        try:
            while True:
                item = self._lines.get_nowait()
                if item is not None:
                    with self._state_lock:
                        self._outstanding -= 1
        except queue.Empty:
            pass

    def _announce_down(self) -> None:
        """Say the full line the first time, a short reminder at most every 30 s after."""
        now = time.monotonic()
        if not self._down_announced:
            self._down_announced = True
            self._last_down_notice = now
            self._enqueue(UNREACHABLE_LINE)
        elif now - self._last_down_notice >= STILL_DOWN_INTERVAL_S:
            self._last_down_notice = now
            self._enqueue(STILL_DOWN_LINE)

    def _speak_loop(self) -> None:
        while True:
            item = self._lines.get()
            if item is None:
                return
            epoch, line = item
            try:
                if epoch == self._epoch:
                    self._emit("speaking")
                    if isinstance(line, _Ack):
                        self._timing["ack_played"] = time.monotonic()
                        self._playing_reply = False
                        if self._play_ack is not None:
                            self._play_ack(line.path)
                    else:
                        self._playing_reply = True
                        self._speak(line)
            except Exception:
                logger.exception("speaking failed")
            finally:
                with self._state_lock:
                    self._outstanding -= 1
            self._maybe_ready()
