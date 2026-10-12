"""Listen to Murmur (the speech-to-text daemon) for the desk assistant key.

With ``stt_source: murmur`` Murmur owns the assistant hotkey and the microphone. It
announces what happened on the session bus and this module turns those signals into
callbacks that mirror a key press and a key release in Synthia:

    AssistantStarted()            -> on_started()
    AssistantTranscribed(text)    -> on_transcribed(text, received_at)
    AssistantCancelled()          -> on_cancelled()

If Murmur is not running (or the session bus is unreachable) the listener says so once
per outage, keeps retrying, and picks the subscription up again when Murmur appears.
It never raises into the voice app.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Any, Callable, Optional, Protocol

logger = logging.getLogger(__name__)

# The bus name is the app id; the interface carries a version suffix (Murmur1).
BUS_NAME = "io.github.markmiddo.Murmur"
OBJECT_PATH = "/io/github/markmiddo/Murmur"
INTERFACE = "io.github.markmiddo.Murmur1"

UNAVAILABLE_LINE = "I can't hear you, Murmur isn't running."

RETRY_SECONDS = 5.0
POLL_SECONDS = 1.0

# Events handed back by a bus: (name, args). Names are the D-Bus signal members.
Event = tuple[str, tuple[Any, ...]]


class MurmurUnavailable(Exception):
    """Murmur is not on the bus (never was, or went away)."""


class MurmurBus(Protocol):
    """What the listener needs from a D-Bus connection (faked in tests)."""

    def has_owner(self) -> bool:
        """Whether Murmur currently owns its bus name."""

    def subscribe(self) -> None:
        """Start receiving Murmur's signals (and its going away)."""

    def hotkey(self) -> str:
        """Murmur's AssistantHotkey label ("" when the key is off)."""

    def next_event(self, timeout: float) -> Optional[Event]:
        """The next event, or None when nothing arrived within the timeout."""

    def close(self) -> None:
        """Drop the connection."""


class JeepneyBus:
    """A blocking session-bus connection built on jeepney (pure Python)."""

    def __init__(self) -> None:
        from jeepney.io.blocking import open_dbus_connection

        self._conn = open_dbus_connection(bus="SESSION")
        self._queue: deque[Any] = deque()
        self._handles: list[Any] = []

    def _call(self, msg: Any) -> Any:
        reply = self._conn.send_and_get_reply(msg, timeout=3.0)
        from jeepney import MessageType

        if reply.header.message_type == MessageType.error:
            raise MurmurUnavailable(str(reply.body))
        return reply.body

    def has_owner(self) -> bool:
        from jeepney import DBus

        return bool(self._call(DBus().NameHasOwner(BUS_NAME))[0])

    def subscribe(self) -> None:
        from jeepney import MatchRule, message_bus

        # Local filters first, so a signal that lands during setup is not lost. They match
        # on interface, member and path (the sender header is a unique name, not ours).
        local = [
            MatchRule(type="signal", interface=INTERFACE, path=OBJECT_PATH),
            MatchRule(
                type="signal",
                interface="org.freedesktop.DBus.Properties",
                member="PropertiesChanged",
                path=OBJECT_PATH,
            ),
            MatchRule(
                type="signal",
                interface="org.freedesktop.DBus",
                member="NameOwnerChanged",
                path="/org/freedesktop/DBus",
            ),
        ]
        for rule in local:
            handle = self._conn.filter(rule, queue=self._queue)
            handle.__enter__()
            self._handles.append(handle)

        bus_rules = [
            MatchRule(type="signal", sender=BUS_NAME, interface=INTERFACE, path=OBJECT_PATH),
            MatchRule(
                type="signal",
                sender=BUS_NAME,
                interface="org.freedesktop.DBus.Properties",
                member="PropertiesChanged",
                path=OBJECT_PATH,
            ),
        ]
        owner_rule = MatchRule(
            type="signal",
            sender="org.freedesktop.DBus",
            interface="org.freedesktop.DBus",
            member="NameOwnerChanged",
            path="/org/freedesktop/DBus",
        )
        owner_rule.add_arg_condition(0, BUS_NAME)
        for rule in [*bus_rules, owner_rule]:
            self._call(message_bus.AddMatch(rule))

    def hotkey(self) -> str:
        from jeepney import DBusAddress, Properties

        address = DBusAddress(OBJECT_PATH, bus_name=BUS_NAME, interface=INTERFACE)
        body = self._call(Properties(address).get("AssistantHotkey"))
        value = body[0][1] if body and isinstance(body[0], tuple) else ""
        return str(value or "")

    def next_event(self, timeout: float) -> Optional[Event]:
        try:
            msg = self._conn.recv_until_filtered(self._queue, timeout=timeout)
        except TimeoutError:
            return None
        member = msg.header.fields.get(_member_field())
        body = tuple(msg.body)
        if member == "NameOwnerChanged":
            # (name, old_owner, new_owner); only our own name is subscribed, but be sure.
            if body and body[0] != BUS_NAME:
                return None
            return ("OwnerChanged", (body[2] if len(body) > 2 else "",))
        if member == "PropertiesChanged":
            if body and body[0] != INTERFACE:
                return None
            return ("PropertiesChanged", body)
        return (str(member), body)

    def close(self) -> None:
        for handle in self._handles:
            try:
                handle.__exit__(None, None, None)
            except Exception:  # pragma: no cover - best effort
                pass
        self._handles.clear()
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - best effort
            pass


def _member_field() -> Any:
    from jeepney import HeaderFields

    return HeaderFields.member


class MurmurListener:
    """Subscribes to Murmur's assistant signals on a background thread."""

    def __init__(
        self,
        on_started: Callable[[], None],
        on_transcribed: Callable[[str, float], None],
        on_cancelled: Callable[[], None],
        on_unavailable: Callable[[], None],
        on_hotkey: Optional[Callable[[Optional[str]], None]] = None,
        bus_factory: Callable[[], MurmurBus] = JeepneyBus,
        retry_seconds: float = RETRY_SECONDS,
        poll_seconds: float = POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._on_started = on_started
        self._on_transcribed = on_transcribed
        self._on_cancelled = on_cancelled
        self._on_unavailable = on_unavailable
        self._on_hotkey = on_hotkey
        self._bus_factory = bus_factory
        self._retry = retry_seconds
        self._poll = poll_seconds
        self._clock = clock
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._announced = False

    # -- lifecycle -----------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="murmur-listener", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=3.0)

    # -- loop ----------------------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._session()
            except MurmurUnavailable as e:
                self._unavailable(f"Murmur is not available ({e})")
            except Exception as e:  # never take the voice app down with us
                self._unavailable(f"Murmur listener error: {e}")
            self._stop.wait(self._retry)

    def _session(self) -> None:
        bus = self._bus_factory()
        try:
            if not bus.has_owner():
                raise MurmurUnavailable("name has no owner")
            bus.subscribe()
            self._recovered()
            self._publish_hotkey(bus)
            while not self._stop.is_set():
                event = bus.next_event(self._poll)
                if event is None:
                    continue
                self._dispatch(event, bus)
        finally:
            try:
                bus.close()
            except Exception:  # pragma: no cover - best effort
                pass

    def _dispatch(self, event: Event, bus: MurmurBus) -> None:
        name, args = event
        received_at = self._clock()
        if name == "OwnerChanged":
            if not (args and args[0]):
                raise MurmurUnavailable("Murmur went away")
            self._publish_hotkey(bus)  # restarted under a new owner
            return
        if name == "PropertiesChanged":
            self._publish_hotkey(bus)
            return
        try:
            if name == "AssistantStarted":
                self._on_started()
            elif name == "AssistantTranscribed":
                text = args[0] if args and isinstance(args[0], str) else ""
                self._on_transcribed(text, received_at)
            elif name == "AssistantCancelled":
                self._on_cancelled()
        except Exception as e:  # a bad handler must not drop the subscription
            logger.error("Murmur %s handler failed: %s", name, e)

    def _publish_hotkey(self, bus: MurmurBus) -> None:
        if self._on_hotkey is None:
            return
        try:
            label: Optional[str] = bus.hotkey()
        except Exception as e:
            logger.debug("Could not read Murmur's assistant key: %s", e)
            label = None
        self._on_hotkey(label)

    # -- outage bookkeeping --------------------------------------------------------

    def _unavailable(self, why: str) -> None:
        if self._announced:
            logger.debug("%s; retrying", why)
            return
        self._announced = True
        logger.warning("%s; will keep retrying every %.0fs", why, self._retry)
        if self._on_hotkey is not None:
            self._on_hotkey(None)
        try:
            self._on_unavailable()
        except Exception as e:
            logger.error("Murmur unavailable handler failed: %s", e)

    def _recovered(self) -> None:
        if self._announced:
            logger.info("Murmur is back; listening for the assistant key")
        else:
            logger.info("Listening to Murmur for the assistant key")
        self._announced = False
