import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from synthia import inbox


@pytest.fixture
def desk_job(tmp_path):
    job = tmp_path / "growth" / "jobs" / "2026-10-13-week-of-posts"
    (job / "out").mkdir(parents=True)
    (job / "out" / "summary.md").write_text("# Posts\nTwo posts ready, one cut.\n")
    (job / "out" / "a.json").write_text('{"title": "A", "body": "b"}')
    (job / "out" / "cover.png").write_bytes(b"\x89PNG")
    (job / "out" / "notes.txt").write_text("x")
    return job


def test_create_from_squad_fills_the_contract(desk_job):
    item = inbox.create_from_squad(desk_job, "growth", desk_job.name, "growth-director", "Growth")
    assert item["version"] == 1 and item["source"] == "squad"
    assert item["title"] == "Growth: week of posts"
    assert item["id"].endswith("-growth-week-of-posts")
    assert item["summary_md"].startswith("# Posts")
    assert item["state"] == "new" and item["note"] is None and item["decided_at"] is None
    assert item["notified"] == {"desk": False, "telegram": False, "email": False}
    kinds = {d["name"]: d["kind"] for d in item["deliverables"]}
    assert kinds == {"a.json": "json", "cover.png": "png", "notes.txt": "other"}
    assert all(os.path.isabs(d["path"]) and d["bytes"] > 0 for d in item["deliverables"])
    on_disk = json.loads((inbox.default_root() / f"{item['id']}.json").read_text())
    assert on_disk == item
    assert not list(inbox.default_root().glob("*.tmp"))


def test_create_is_idempotent_and_refreshes_while_new(desk_job):
    first = inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    (desk_job / "out" / "summary.md").write_text("Updated summary")
    (desk_job / "out" / "b.md").write_text("more")
    second = inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    assert second["id"] == first["id"]
    assert len(inbox.list_items()) == 1
    assert second["summary_md"] == "Updated summary"
    assert {d["name"] for d in second["deliverables"]} >= {"b.md"}


def test_refresh_never_clobbers_a_hud_decision(desk_job):
    item = inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    path = inbox.default_root() / f"{item['id']}.json"
    # The HUD approves with a note; later the squad re-signals done.
    data = json.loads(path.read_text())
    data.update(state="approved", note="ship it", decided_at="2026-10-13T09:00:00+11:00")
    path.write_text(json.dumps(data))
    (desk_job / "out" / "summary.md").write_text("Changed after approval")
    again = inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    assert again["state"] == "approved" and again["note"] == "ship it"
    assert again["summary_md"].startswith("# Posts")  # decided items are left alone
    inbox.mark_notified(item["id"], "desk")
    final = inbox.get(item["id"])
    assert final["state"] == "approved" and final["note"] == "ship it"
    assert final["decided_at"] == "2026-10-13T09:00:00+11:00"
    assert final["notified"]["desk"] is True


def test_mark_notified_rereads_so_a_decision_made_in_between_survives(desk_job):
    item = inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    stale = inbox.get(item["id"])  # what Python read earlier
    path = inbox.default_root() / f"{item['id']}.json"
    data = json.loads(path.read_text())
    data.update(state="sent_back", note="redo", decided_at="2026-10-13T10:00:00+11:00")
    path.write_text(json.dumps(data))
    assert stale["state"] == "new"
    assert inbox.mark_notified(item["id"], "telegram") is True
    final = inbox.get(item["id"])
    assert final["state"] == "sent_back" and final["note"] == "redo"
    assert final["notified"]["telegram"] is True


def test_mark_notified_rejects_unknown_channel_and_missing_item():
    with pytest.raises(ValueError):
        inbox.mark_notified("x", "pigeon")
    assert inbox.mark_notified("nope", "desk") is False


def test_create_from_job_is_idempotent():
    rec = SimpleNamespace(id="abc12345", name="morning briefing", summary="Two meetings.")
    a = inbox.create_from_job(rec)
    b = inbox.create_from_job(rec)
    assert a["id"] == b["id"] and a["source"] == "job"
    assert a["squad"] is None and a["desk"] is None and a["deliverables"] == []
    assert a["title"] == "morning briefing" and a["summary_md"] == "Two meetings."


def test_list_items_filters_by_state_and_orders_newest_first(desk_job):
    inbox.create_from_job(SimpleNamespace(id="j1", name="one", summary=""))
    inbox.create_from_squad(desk_job, "growth", desk_job.name, "d")
    items = inbox.list_items()
    assert len(items) == 2
    assert items == sorted(items, key=lambda i: i["created_at"], reverse=True)
    assert inbox.list_items(state="archived") == []


def test_ids_cannot_escape_the_directory():
    assert inbox.get("../../etc/passwd") is None


def test_prune_removes_only_old_archived_items():
    root = inbox.default_root()
    root.mkdir(parents=True)

    def put(name, state, days_old):
        when = (datetime.now().astimezone() - timedelta(days=days_old)).isoformat()
        (root / f"{name}.json").write_text(
            json.dumps({"id": name, "state": state, "created_at": when, "decided_at": None})
        )

    put("old-archived", "archived", 40)
    put("new-archived", "archived", 5)
    put("old-new", "new", 90)
    put("old-approved", "approved", 90)
    assert inbox.prune() == 1
    left = {p.stem for p in root.glob("*.json")}
    assert left == {"new-archived", "old-new", "old-approved"}


def test_short_lines():
    item = {
        "title": "Growth: week of posts",
        "summary_md": "# Posts\n\n**Two** blog drafts ready, one cut. More text here.",
        "deliverables": [{}, {}],
    }
    assert inbox.desk_line(item) == "Growth's week of posts is ready in your inbox."
    away = inbox.away_line(item)
    assert away.startswith("Growth: week of posts is ready for review (2 files).")
    assert "Two blog drafts ready, one cut." in away and "More text" not in away
    assert away.endswith("Say 'email it' to read it on your phone.")
    assert "failed" in inbox.away_line({"title": "morning", "summary_md": ""}, ok=False)
    assert inbox.desk_line({"title": "morning"}) == "morning is done. It's in your inbox."
