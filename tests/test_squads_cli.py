from datetime import date

import pytest

from synthia.squads import cli
from synthia.squads.engine import Engine
from tests.fake_herdr import FakeHerdr, write_squad


@pytest.fixture
def env(tmp_path, monkeypatch):
    work = tmp_path / "repo"
    work.mkdir()
    write_squad(tmp_path / "cfg", work)
    fake = FakeHerdr()
    eng = Engine(tmp_path / "data", tmp_path / "cfg", fake, today=lambda: date(2026, 10, 13))
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)
    return eng, fake, tmp_path, monkeypatch


def test_start_then_director_commands(env, capsys):
    eng, fake, tmp, mp = env
    assert cli.main(["start", "growth", "Three posts", "--slug", "posts"], eng) == 0
    assert "2026-10-13-posts" in capsys.readouterr().out
    pane = eng.registry.find_live("growth-director").pane_id
    mp.setenv("HERDR_PANE_ID", pane)
    assert cli.main(["hire", "growth-writer", "Post one"], eng) == 0
    assert capsys.readouterr().out.strip() == "growth-writer-1"
    assert cli.main(["ask", "growth-writer-1", "how is it going"], eng) == 0
    assert fake.prompts[-1] == ("growth-writer-1", "how is it going")
    assert cli.main(["read", "growth-writer-1", "--lines", "5"], eng) == 0
    assert "output of growth-writer-1" in capsys.readouterr().out
    assert cli.main(["wait", "growth-writer-1", "--timeout", "3"], eng) == 0
    assert cli.main(["log", "reviewing"], eng) == 0
    f = tmp / "a.json"
    f.write_text("{}")
    assert cli.main(["deliver", str(f)], eng) == 0
    assert cli.main(["dismiss", "growth-writer-1"], eng) == 0
    assert cli.main(["done"], eng) == 0
    assert "ready for review" in capsys.readouterr().out
    assert cli.main(["status"], eng) == 0
    assert "review" in capsys.readouterr().out
    assert cli.main(["stop", "2026-10-13-posts"], eng) == 0


def test_caller_commands_need_a_registered_pane(env, capsys):
    eng, _, _, mp = env
    assert cli.main(["hire", "growth-writer", "x"], eng) == 1
    assert "not a live squad member" in capsys.readouterr().err
    mp.setenv("HERDR_PANE_ID", "w9:p9")
    assert cli.main(["dismiss", "anyone"], eng) == 1


def test_dismiss_refuses_unregistered_agent(env, capsys):
    eng, fake, _, mp = env
    cli.main(["start", "growth", "b"], eng)
    mp.setenv("HERDR_PANE_ID", eng.registry.find_live("growth-director").pane_id)
    fake.panes["w1:p77"] = {"name": "marks-agent", "cwd": "/x"}
    assert cli.main(["dismiss", "marks-agent"], eng) == 1
    assert "w1:p77" in fake.panes


def test_unknown_squad_is_an_error(env, capsys):
    eng, _, _, _ = env
    assert cli.main(["start", "nope", "b"], eng) == 1
    assert "no squad" in capsys.readouterr().err


def test_outside_caller_can_ask_and_read_registered_agents_only(env, capsys):
    eng, fake, _, mp = env
    cli.main(["start", "growth", "b"], eng)
    mp.setenv("HERDR_PANE_ID", "w1:p500")  # Mark's own pane, not in any squad
    assert cli.main(["ask", "growth-director", "update from Mark"], eng) == 0
    assert fake.prompts[-1] == ("growth-director", "update from Mark")
    assert cli.main(["read", "growth-director"], eng) == 0
    fake.panes["w1:p77"] = {"name": "marks-agent", "cwd": "/x"}
    assert cli.main(["ask", "marks-agent", "hi"], eng) == 1
    assert "not one of Synthia's agents" in capsys.readouterr().err


def test_squad_member_stays_scoped_to_its_own_job(env, capsys):
    eng, _, _, mp = env
    cli.main(["start", "growth", "one", "--slug", "one"], eng)
    cli.main(["start", "growth", "two", "--slug", "two"], eng)
    mp.setenv("HERDR_PANE_ID", eng.registry.find_live("growth-director").pane_id)
    assert cli.main(["ask", "growth-director-2", "hi"], eng) == 1
    assert "not part of job" in capsys.readouterr().err
