from datetime import date, datetime
from pathlib import Path

from synthia.brain.journal import WalkJournal


def _clock(h=7, m=12):
    return lambda: datetime(2026, 9, 10, h, m)


def test_turn_creates_dated_file_with_header(tmp_path):
    j = WalkJournal(tmp_path / "walk", now=_clock())
    j.turn("what's on today", "Two meetings and a dentist at three.")
    p = tmp_path / "walk" / "2026-09-10.md"
    assert p.exists()
    text = p.read_text()
    assert text.startswith("# Walk journal 2026-09-10\n\n")
    assert "- 07:12 **Mark:** what's on today" in text
    assert "**Synthia:** Two meetings and a dentist at three." in text


def test_entries_append_and_flatten_newlines(tmp_path):
    j = WalkJournal(tmp_path, now=_clock())
    j.job_dispatched("morning", "/morning")
    j.job_finished("morning", "done", "Briefing:\nweather fine\ntwo meetings", "All sorted.")
    j.confirmation("run git push origin main", False)
    j.note("session rolled over")
    text = j.today_path().read_text()
    assert text.count("\n- ") == 4
    assert "**Job dispatched:** morning — /morning" in text
    assert "**Job done:** morning — Briefing: weather fine two meetings" in text
    assert "**Confirmation denied:** run git push origin main" in text
    assert "session rolled over" in text


def test_long_reply_truncated(tmp_path):
    j = WalkJournal(tmp_path, now=_clock())
    j.turn("hi", "x" * 2000)
    line = [l for l in j.today_path().read_text().splitlines() if "Synthia" in l][0]
    assert len(line) < 700 and line.endswith("…")


def test_write_failure_is_swallowed(tmp_path, caplog):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    j = WalkJournal(blocker / "walk", now=_clock())
    j.turn("hi", "there")  # must not raise
    assert "walk journal write failed" in caplog.text


def test_path_for_day(tmp_path):
    j = WalkJournal(tmp_path)
    assert j.path_for(date(2026, 1, 2)) == tmp_path / "2026-01-02.md"
