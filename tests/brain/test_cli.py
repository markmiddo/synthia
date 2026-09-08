import subprocess
from pathlib import Path

from synthia.brain.cli import main, pull_repos, repl


def test_pull_repos_reports_per_repo(tmp_path):
    calls = []

    def fake_run(cmd, cwd, capture_output, text, timeout):
        calls.append((cmd, cwd))
        if "bad" in str(cwd):
            return subprocess.CompletedProcess(cmd, 1, "", "fatal")
        return subprocess.CompletedProcess(cmd, 0, "Already up to date.", "")

    good, bad = tmp_path / "good", tmp_path / "bad"
    results = pull_repos([good, bad], run=fake_run)
    assert results == [(good, True), (bad, False)]
    assert calls[0][0] == ["git", "pull", "--ff-only"]


def test_pull_repos_swallows_exceptions(tmp_path):
    def boom(*a, **k):
        raise FileNotFoundError("git")

    assert pull_repos([tmp_path], run=boom) == [(tmp_path, False)]


class FakeBrain:
    def __init__(self):
        self.sent = []
        self.interrupts = 0
        self.new_sessions = 0

        class Jobs:
            def list_jobs(self_inner):
                return []

        self.jobs = Jobs()

    async def send(self, text):
        self.sent.append(text)
        yield "echo: "
        yield text

    async def interrupt(self):
        self.interrupts += 1

    async def new_session(self, handover=None):
        self.new_sessions += 1


async def test_repl_routes_lines_and_commands():
    brain = FakeBrain()
    lines = iter(["hello", "/stop", "/new", "/jobs", "/quit"])
    out = []
    await repl(brain, input_fn=lambda _p="": next(lines), print_fn=out.append)
    assert brain.sent == ["hello"]
    assert brain.interrupts == 1
    assert brain.new_sessions == 1
    assert any("echo: hello" in o for o in out)
    assert any("No jobs" in o for o in out)


def test_main_unknown_subcommand_returns_2(capsys):
    assert main(["bogus"]) == 2
