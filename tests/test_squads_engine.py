import json
from datetime import date

import pytest

from synthia.squads.engine import Engine
from synthia.squads.model import SquadError, parse_squad
from tests.fake_herdr import FakeHerdr, write_squad


@pytest.fixture
def env(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    write_squad(tmp_path / "cfg", work)
    fake = FakeHerdr()
    eng = Engine(tmp_path / "data", tmp_path / "cfg", fake, today=lambda: date(2026, 10, 13))
    return eng, fake, tmp_path


def start(eng):
    return eng.start_job("growth", "Write three posts", "week of posts")


def test_model_validation():
    with pytest.raises(SquadError, match="not a role"):
        parse_squad({"id": "x", "director": "d", "roles": {"a": {}}})
    with pytest.raises(SquadError, match="unknown role"):
        parse_squad({"id": "x", "director": "a", "roles": {"a": {"hires": ["zz"]}}})


def test_start_job_makes_desk_registers_and_prompts(env):
    eng, fake, tmp = env
    info = start(eng)
    assert info.job == "2026-10-13-week-of-posts"
    assert info.agent_name == "growth-director"
    assert (info.path / "brief.md").read_text().strip() == "Write three posts"
    assert (info.path / "work").is_dir() and (info.path / "out").is_dir()
    status = json.loads((info.path / "status.json").read_text())
    assert status["state"] == "working"
    start_call = [c for c in fake.calls if c[0] == "start_claude"][0][1]
    assert start_call == ("growth-director", info.pane_id, "claude-opus-5-5", "growth-director")
    member = eng.registry.get(info.pane_id)
    assert member.parent is None and member.squad == "growth" and member.job == info.job
    target, prompt = fake.prompts[0]
    assert target == "growth-director"
    assert "Write three posts" in prompt and str(info.path) in prompt
    assert "growth-seo, growth-writer" in prompt


def test_start_failure_closes_pane_and_registers_nothing(env):
    eng, fake, _ = env
    fake.fail_start = True
    with pytest.raises(SquadError, match="startup question"):
        start(eng)
    assert fake.closed and eng.registry.live() == []
    job = eng.root / "growth" / "jobs" / "2026-10-13-week-of-posts" / "status.json"
    assert json.loads(job.read_text())["state"] == "stopped"


def test_second_job_gets_unique_director_name(env):
    eng, _, _ = env
    a, b = start(eng), start(eng)
    assert a.agent_name == "growth-director" and b.agent_name == "growth-director-2"
    assert b.job.endswith("-2")


def test_hire_opens_next_to_parent_and_registers(env):
    eng, fake, _ = env
    info = start(eng)
    name = eng.hire(info.path, "growth-writer", "Write post one", info.pane_id)
    assert name == "growth-writer-1"
    split = [c for c in fake.calls if c[0] == "split"][-1][1]
    assert split[0] == info.pane_id
    m = eng.registry.find_live(name)
    assert m.parent == info.pane_id and m.role == "growth-writer"
    assert (info.path / "work" / "growth-writer").is_dir()
    target, prompt = fake.prompts[-1]
    assert target == name and "Write post one" in prompt and "work/growth-writer" in prompt


def test_hire_refuses_role_outside_hires_list(env):
    eng, fake, _ = env
    info = start(eng)
    with pytest.raises(SquadError, match="may not hire growth-editor"):
        eng.hire(info.path, "growth-editor", "x", info.pane_id)
    with pytest.raises(SquadError, match="may not hire ghost"):
        eng.hire(info.path, "ghost", "x", info.pane_id)
    assert len(eng.registry.live()) == 1


def test_hire_refuses_unregistered_caller(env):
    eng, _, _ = env
    info = start(eng)
    with pytest.raises(SquadError, match="not a live squad member"):
        eng.hire(info.path, "growth-writer", "x", "w9:p9")


def test_cap_enforced_and_freed_by_dismiss(env):
    eng, fake, _ = env
    info = start(eng)  # cap is 2 in the fixture
    eng.hire(info.path, "growth-seo", "a", info.pane_id)
    w1 = eng.hire(info.path, "growth-writer", "b", info.pane_id)
    with pytest.raises(SquadError, match="cap reached"):
        eng.hire(info.path, "growth-writer", "c", info.pane_id)
    panes_before = len(fake.panes)
    eng.dismiss(w1)
    assert len(fake.panes) == panes_before - 1
    assert eng.hire(info.path, "growth-writer", "c", info.pane_id) == "growth-writer-1"


def test_director_not_counted_and_dead_panes_free_slots(env):
    eng, fake, _ = env
    info = start(eng)
    eng.hire(info.path, "growth-seo", "a", info.pane_id)
    eng.hire(info.path, "growth-writer", "b", info.pane_id)
    seo_pane = eng.registry.find_live("growth-seo-1").pane_id
    del fake.panes[seo_pane]  # the pane died on its own
    assert eng.hire(info.path, "growth-writer", "c", info.pane_id) == "growth-writer-2"


def test_dismiss_only_registered(env):
    eng, fake, _ = env
    fake.panes["w1:p99"] = {"name": "marks-agent", "cwd": "/x"}
    with pytest.raises(SquadError, match="not one of Synthia's agents"):
        eng.dismiss("marks-agent")
    with pytest.raises(SquadError):
        eng.close_agent("marks-agent")
    assert "w1:p99" in fake.panes and fake.closed == []


def test_ask_read_wait_scoped_to_job(env):
    eng, fake, _ = env
    a, b = start(eng), start(eng)
    w = eng.hire(a.path, "growth-writer", "x", a.pane_id)
    eng.ask(w, "status?", a.job)
    assert fake.prompts[-1] == (w, "status?")
    assert eng.read(w, 5, a.job) == f"output of {w}"
    assert eng.wait(w, 3, a.job) == "idle"
    with pytest.raises(SquadError, match="not part of job"):
        eng.ask(w, "hi", b.job)
    with pytest.raises(SquadError, match="not one of Synthia's"):
        eng.read("someone-else", 5, a.job)


def test_stop_job_dismisses_specialists_then_director(env):
    eng, fake, _ = env
    info = start(eng)
    eng.hire(info.path, "growth-seo", "a", info.pane_id)
    eng.hire(info.path, "growth-writer", "b", info.pane_id)
    names = eng.stop_job(info.job)
    assert names[-1] == "growth-director" and set(names[:2]) == {"growth-seo-1", "growth-writer-1"}
    assert fake.closed[-1] == info.pane_id and fake.panes == {}
    assert eng.registry.live() == []
    assert json.loads((info.path / "status.json").read_text())["state"] == "stopped"


def test_done_writes_review_state_and_event(env):
    eng, _, tmp = env
    info = start(eng)
    (info.path / "out" / "summary.md").write_text("# Posts\nTwo posts ready.\n")
    text = eng.done(info.pane_id)
    assert "ready for review" in text
    assert json.loads((info.path / "status.json").read_text())["state"] == "review"
    lines = (tmp / "data" / "events.jsonl").read_text().splitlines()
    ev = json.loads(lines[0])
    assert ev["squad"] == "growth" and ev["job"] == info.job and ev["text"] == text
    assert ev["digest"] == "# Posts\nTwo posts ready." and ev["desk"] == str(info.path)


def test_done_refused_for_specialist(env):
    eng, _, _ = env
    info = start(eng)
    eng.hire(info.path, "growth-writer", "x", info.pane_id)
    pane = eng.registry.find_live("growth-writer-1").pane_id
    with pytest.raises(SquadError, match="only a squad director"):
        eng.done(pane)


def test_log_and_deliver(env):
    eng, _, tmp = env
    info = start(eng)
    eng.log(info.pane_id, "hello")
    src = tmp / "post.json"
    src.write_text("{}")
    eng.deliver(info.pane_id, src)
    assert (info.path / "out" / "post.json").read_text() == "{}"
    texts = [e["text"] for e in json.loads((info.path / "status.json").read_text())["log"]]
    assert "hello" in texts and "delivered post.json" in texts


def test_open_and_close_plain_agent(env):
    eng, fake, tmp = env
    assert eng.open_agent("helper", str(tmp), "do a thing") == "helper"
    m = eng.registry.find_live("helper")
    assert m.squad is None and m.opened_by == "synthia"
    assert fake.prompts[-1] == ("helper", "do a thing")
    eng.close_agent("helper")
    assert eng.registry.find_live("helper") is None
    with pytest.raises(SquadError, match="Bad"):
        eng.open_agent("Bad", str(tmp), "x")
    with pytest.raises(SquadError, match="not a folder"):
        eng.open_agent("other", str(tmp / "nope"), "x")


def test_status_lists_jobs(env):
    eng, _, _ = env
    info = start(eng)
    rows = eng.status()
    assert rows[0]["job"] == info.job and rows[0]["state"] == "working"
    assert rows[0]["live"] == ["growth-director"]
    assert eng.status("nope") == []


def test_install_never_overwrites_without_force(env):
    eng, _, tmp = env
    src = tmp / "repo_squads" / "growth"
    (src / "agents").mkdir(parents=True)
    (src / "squad.yaml").write_text("id: growth\n")
    (src / "agents" / "growth-writer.md").write_text("new")
    agents = tmp / "agents"
    agents.mkdir()
    (agents / "growth-writer.md").write_text("mine")
    report = eng.install("growth", tmp / "repo_squads", agents)
    assert "SKIPPED" in report and (agents / "growth-writer.md").read_text() == "mine"
    fresh = tmp / "agents2"
    assert "installed" in eng.install("growth", tmp / "repo_squads", fresh)
    eng.install("growth", tmp / "repo_squads", agents, force=True)
    assert (agents / "growth-writer.md").read_text() == "new"


def _shared_repo(tmp):
    repo = tmp / "repo_squads"
    (repo / "office" / "agents").mkdir(parents=True)
    (repo / "shared" / "agents").mkdir(parents=True)
    (repo / "office" / "squad.yaml").write_text(
        "id: office\ndirector: chief\nroles:\n  chief: {hires: [pm, studio-designer]}\n"
        "  pm: {}\n  studio-designer: {}\n"
    )
    (repo / "office" / "agents" / "chief.md").write_text("chief")
    (repo / "office" / "agents" / "pm.md").write_text("pm")
    (repo / "shared" / "agents" / "studio-designer.md").write_text("designer v1")
    (repo / "shared" / "agents" / "unrelated.md").write_text("nope")
    return repo


def test_install_adds_referenced_shared_agents_only(env):
    eng, _, tmp = env
    repo = _shared_repo(tmp)
    agents = tmp / "agents"
    report = eng.install("office", repo, agents)
    assert (agents / "studio-designer.md").read_text() == "designer v1"
    assert (agents / "chief.md").is_file() and (agents / "pm.md").is_file()
    assert not (agents / "unrelated.md").exists()
    assert "installed" in report and str(agents / "studio-designer.md") in report


def test_install_shared_agent_never_overwrites_without_force(env):
    eng, _, tmp = env
    repo = _shared_repo(tmp)
    agents = tmp / "agents"
    agents.mkdir()
    (agents / "studio-designer.md").write_text("mine")
    report = eng.install("office", repo, agents)
    assert "SKIPPED" in report and (agents / "studio-designer.md").read_text() == "mine"
    eng.install("office", repo, agents, force=True)
    assert (agents / "studio-designer.md").read_text() == "designer v1"
    assert "unchanged" in eng.install("office", repo, agents)


def test_squad_own_agent_wins_over_shared(env):
    eng, _, tmp = env
    repo = _shared_repo(tmp)
    (repo / "office" / "agents" / "studio-designer.md").write_text("office version")
    agents = tmp / "agents"
    eng.install("office", repo, agents)
    assert (agents / "studio-designer.md").read_text() == "office version"


def test_shipped_squads_are_consistent():
    """Every shipped squad parses, and every role has an agent file (own or shared)."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[1] / "squads"
    shared = {f.stem for f in (root / "shared" / "agents").glob("*.md")}
    squads = [d for d in sorted(root.iterdir()) if (d / "squad.yaml").is_file()]
    assert {d.name for d in squads} >= {"growth", "office", "release"}
    for d in squads:
        squad = parse_squad(yaml.safe_load((d / "squad.yaml").read_text()), d.name)
        own = {f.stem for f in (d / "agents").glob("*.md")}
        assert squad.cap == 4
        for rid in squad.roles:
            assert rid in own | shared, f"{d.name}: no agent file for {rid}"
            text = next(
                f
                for f in [d / "agents" / f"{rid}.md", root / "shared" / "agents" / f"{rid}.md"]
                if f.is_file()
            ).read_text()
            assert f"name: {rid}\n" in text
    assert (
        "studio-designer"
        in parse_squad(yaml.safe_load((root / "growth" / "squad.yaml").read_text()))
        .role("growth-director")
        .hires
    )
    for sid, hires in {
        "office": {"office-pm", "office-dev-release", "studio-designer"},
        "release": {"release-faq", "release-video", "studio-designer"},
    }.items():
        sq = parse_squad(yaml.safe_load((root / sid / "squad.yaml").read_text()))
        assert set(sq.role(sq.director).hires) == hires


def test_engine_imports_without_the_sdk():
    import subprocess
    import sys

    code = (
        "import sys; import synthia.squads.cli, synthia.squads.engine, synthia.squads.events; "
        "sys.exit(1 if any(m.startswith('claude_agent_sdk') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0
