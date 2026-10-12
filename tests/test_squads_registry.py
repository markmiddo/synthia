import json

from synthia.squads.registry import Member, Registry


def member(name="growth-writer-1", parent="w1:p1", job="2026-10-13-posts"):
    return Member(name, "growth", job, "growth-writer", "Writer", parent)


def test_add_get_and_file_shape(tmp_path):
    reg = Registry(tmp_path)
    reg.add("w1:p2", member())
    data = json.loads((tmp_path / "registry.json").read_text())
    assert data["version"] == 1
    body = data["members"]["w1:p2"]
    assert body["agent_name"] == "growth-writer-1" and body["ended_at"] is None
    assert body["opened_by"] == "synthia" and body["started_at"]
    assert "pane_id" not in body
    assert reg.get("w1:p2").agent_name == "growth-writer-1"


def test_end_and_live(tmp_path):
    reg = Registry(tmp_path)
    reg.add("w1:p2", member("a"))
    reg.add("w1:p3", member("b", job="other"))
    reg.end("w1:p2")
    assert [m.agent_name for m in reg.live()] == ["b"]
    assert [m.agent_name for m in reg.live("other")] == ["b"]
    assert reg.find_live("a") is None and reg.find_live("b") is not None
    assert reg.get("w1:p2").ended_at


def test_prune_marks_missing_panes_on_write(tmp_path):
    alive = {"w1:p3"}
    reg = Registry(tmp_path, live_panes=lambda: alive)
    reg.add("w1:p3", member("b"))
    alive.clear()
    reg.add("w1:p4", member("c"))  # next write prunes b; c is also not alive
    assert reg.get("w1:p3").ended_at
    alive.add("w1:p5")
    reg.add("w1:p5", member("d"))
    assert [m.agent_name for m in reg.live()] == ["d"]


def test_prune_survives_herdr_failure(tmp_path):
    def boom():
        raise RuntimeError("herdr down")

    reg = Registry(tmp_path, live_panes=boom)
    reg.add("w1:p2", member())
    assert reg.get("w1:p2").ended_at is None


def test_corrupt_file_reads_empty(tmp_path):
    (tmp_path / "registry.json").write_text("{nope")
    assert Registry(tmp_path).live() == []
