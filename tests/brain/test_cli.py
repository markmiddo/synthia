import asyncio
import subprocess
import time
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


async def test_repl_input_does_not_block_loop():
    """Verify event loop keeps running while repl waits for input."""
    brain = FakeBrain()
    counter = {"ticks": 0}

    def slow_input(prompt):
        # Sleep 0.2s to simulate user thinking before responding
        time.sleep(0.2)
        return "/quit"

    async def tick_task():
        """Increment counter every 0.02s until cancelled."""
        try:
            while True:
                counter["ticks"] += 1
                await asyncio.sleep(0.02)
        except asyncio.CancelledError:
            pass

    # Start the background counter task
    task = asyncio.create_task(tick_task())
    try:
        # Run repl; it should not block the event loop during input
        await repl(brain, input_fn=slow_input, print_fn=lambda _: None)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # The counter should have advanced during the 0.2s sleep
    # With 0.02s sleep between increments, we expect ~10 ticks, but assert >= 5 for robustness
    assert (
        counter["ticks"] >= 5
    ), f"Event loop was blocked: only {counter['ticks']} ticks during 0.2s input wait"
