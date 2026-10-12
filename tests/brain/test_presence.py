import pytest

from synthia.brain import presence
from synthia.brain.presence import CachedSessionActive, graphical_session_id, session_active


def fake_run(sessions: str, props: str):
    def run(args):
        if args[1] == "list-sessions":
            return sessions
        return props

    return run


@pytest.fixture(autouse=True)
def user(monkeypatch):
    monkeypatch.setattr(presence.getpass, "getuser", lambda: "mark")


SESSIONS = "3 1000 mark - pts/0 active no -\n5 1000 mark seat0 tty1 active no -\n"


def test_picks_the_seat_session_not_ssh():
    assert graphical_session_id(fake_run(SESSIONS, "")) == "5"


def test_active_only_when_unlocked_and_not_idle():
    ok = "Active=yes\nLockedHint=no\nIdleHint=no\n"
    assert session_active(fake_run(SESSIONS, ok)) is True
    assert (
        session_active(fake_run(SESSIONS, ok.replace("LockedHint=no", "LockedHint=yes"))) is False
    )
    assert session_active(fake_run(SESSIONS, ok.replace("IdleHint=no", "IdleHint=yes"))) is False
    assert session_active(fake_run("3 1000 mark - pts/0 active no -\n", ok)) is False


def test_cache_and_failure_fall_back_to_false():
    calls = {"n": 0}
    now = {"t": 0.0}

    def probe():
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("no loginctl")
        return True

    c = CachedSessionActive(probe, clock=lambda: now["t"], ttl=30)
    assert c() is True and c() is True and calls["n"] == 1
    now["t"] = 31
    assert c() is False and calls["n"] == 2
