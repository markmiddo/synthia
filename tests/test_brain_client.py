"""brain_client against a real DeskTransport on a background event loop."""

import asyncio
import threading
import time

import pytest

from synthia.brain.transports.desk import DeskTransport
from synthia.brain_client import BrainClient, BrainUnavailable


class FakeBrain:
    def __init__(self):
        self.interrupts = 0
        self.journal = None

    async def send(self, text, origin=None):
        yield "You said "
        yield text

    async def interrupt(self):
        self.interrupts += 1


class ServerThread:
    def __init__(self, tmp_path):
        self.brain = FakeBrain()
        self.desk = DeskTransport(self.brain, 0, tmp_path / "desk.token", confirm_timeout_s=1)
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self.loop.run_forever, daemon=True)

    def start(self):
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self.desk.start(), self.loop).result(5)

    def stop(self):
        asyncio.run_coroutine_threadsafe(self.desk.stop(), self.loop).result(5)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(5)


@pytest.fixture
def server(tmp_path):
    s = ServerThread(tmp_path)
    s.start()
    yield s
    s.stop()


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_say_streams_frames_back(server, tmp_path):
    frames = []
    client = BrainClient(
        frames.append, port=server.desk.bound_port, token_file=tmp_path / "desk.token"
    )
    client.say("hello")
    assert _wait(lambda: any(f["type"] == "reply_done" for f in frames))
    assert "".join(f["text"] for f in frames if f["type"] == "delta") == "You said hello"
    client.close()


def test_interrupt_is_sent(server, tmp_path):
    client = BrainClient(
        lambda f: None, port=server.desk.bound_port, token_file=tmp_path / "desk.token"
    )
    client.ensure_connected()
    client.interrupt()
    assert _wait(lambda: server.brain.interrupts == 1)
    client.close()


def test_missing_token_file_is_a_clear_error(tmp_path):
    client = BrainClient(lambda f: None, port=1, token_file=tmp_path / "nope.token", backoff=(0.0,))
    with pytest.raises(BrainUnavailable, match="no desk token"):
        client.say("hi")


def test_brain_down_raises_after_backoff(tmp_path):
    token = tmp_path / "desk.token"
    token.write_text("x")
    client = BrainClient(lambda f: None, port=1, token_file=token, backoff=(0.0, 0.0))
    with pytest.raises(BrainUnavailable, match="cannot reach"):
        client.say("hi")


def test_wrong_token_is_refused(server, tmp_path):
    bad = tmp_path / "bad.token"
    bad.write_text("wrong")
    client = BrainClient(lambda f: None, port=server.desk.bound_port, token_file=bad, backoff=())
    with pytest.raises(BrainUnavailable):
        client.say("hi")


def test_reconnects_after_the_server_drops(server, tmp_path):
    frames = []
    client = BrainClient(
        frames.append,
        port=server.desk.bound_port,
        token_file=tmp_path / "desk.token",
        backoff=(0.1,),
    )
    client.ensure_connected()
    assert client.connected
    client.close()
    client.say("again")
    assert _wait(lambda: any(f["type"] == "reply_done" for f in frames))
    client.close()
