import json

from synthia.squads.events import EventTail


def line(n):
    return json.dumps({"text": f"e{n}"}) + "\n"


def tail(tmp_path):
    return EventTail(tmp_path / "events.jsonl", tmp_path / "state" / "off")


def test_missing_file_is_empty(tmp_path):
    assert tail(tmp_path).poll() == []


def test_reads_only_new_events_and_persists_offset(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text(line(1))
    assert [e["text"] for e in tail(tmp_path).poll()] == ["e1"]
    with open(f, "a") as fh:
        fh.write(line(2))
    fresh = tail(tmp_path)  # a restart: offset comes from disk
    assert [e["text"] for e in fresh.poll()] == ["e2"]
    assert fresh.poll() == []


def test_partial_line_waits(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text(line(1) + '{"text": "e')
    t = tail(tmp_path)
    assert len(t.poll()) == 1
    with open(f, "a") as fh:
        fh.write('2"}\n')
    assert [e["text"] for e in t.poll()] == ["e2"]


def test_truncation_restarts_from_zero(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text(line(1) + line(2))
    t = tail(tmp_path)
    t.poll()
    f.write_text(line(3))  # shorter than the saved offset
    assert [e["text"] for e in t.poll()] == ["e3"]


def test_replacement_and_deletion(tmp_path):
    f = tmp_path / "events.jsonl"
    f.write_text(line(1))
    t = tail(tmp_path)
    t.poll()
    f.unlink()
    assert t.poll() == []
    f.write_text(line(2))
    assert [e["text"] for e in t.poll()] == ["e2"]


def test_bad_lines_skipped(tmp_path):
    (tmp_path / "events.jsonl").write_text("garbage\n" + line(1) + "[1]\n")
    assert [e["text"] for e in tail(tmp_path).poll()] == ["e1"]


def test_corrupt_offset_file(tmp_path):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "off").write_text("not json")
    (tmp_path / "events.jsonl").write_text(line(1))
    assert len(tail(tmp_path).poll()) == 1


def test_event_record_carries_the_inbox_id_and_makes_one_for_old_events(tmp_path):
    from synthia import inbox
    from synthia.brain.squad_events import event_record

    assert event_record({"squad": "growth", "job": "j", "inbox_id": "abc"}).inbox_id == "abc"
    job = tmp_path / "growth" / "jobs" / "2026-10-13-x"
    (job / "out").mkdir(parents=True)
    (job / "out" / "summary.md").write_text("Done.")
    rec = event_record({"squad": "growth", "job": job.name, "desk": str(job)})
    assert inbox.get(rec.inbox_id)["summary_md"] == "Done."
