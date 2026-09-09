"""synthia-brain entry point: text REPL for desktop testing, Telegram transport for the walk."""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from synthia.brain.concierge import Brain
from synthia.brain.config import BrainConfig, load_brain_config

logger = logging.getLogger(__name__)


def pull_repos(
    repos: list[Path], run: Callable[..., Any] = subprocess.run
) -> list[tuple[Path, bool]]:
    results: list[tuple[Path, bool]] = []
    for repo in repos:
        try:
            proc = run(
                ["git", "pull", "--ff-only"], cwd=repo, capture_output=True, text=True, timeout=120
            )
            ok = proc.returncode == 0
            if not ok:
                logger.warning("git pull failed in %s: %s", repo, proc.stderr.strip())
        except Exception as e:  # never block the brain on a pull
            logger.warning("git pull errored in %s: %s", repo, e)
            ok = False
        results.append((repo, ok))
    return results


async def _always_yes(question: str) -> bool:
    print(f"[confirm] {question}")
    answer = await asyncio.to_thread(input, "yes/no> ")
    return answer.strip().lower() in ("y", "yes")


async def repl(
    brain: Any,
    input_fn: Callable[[str], str] = input,
    print_fn: Callable[[str], None] = print,
) -> None:
    print_fn(
        "Synthia brain REPL. /stop interrupts, /new starts a session, /jobs lists, /quit exits."
    )
    while True:
        try:
            line = (await asyncio.to_thread(input_fn, "you> ")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if not line:
            continue
        if line == "/quit":
            return
        if line == "/stop":
            await brain.interrupt()
            print_fn("[interrupted]")
            continue
        if line == "/new":
            await brain.new_session()
            print_fn("[new session]")
            continue
        if line == "/jobs":
            jobs = brain.jobs.list_jobs()
            print_fn("No jobs." if not jobs else "\n".join(f"{j.name} {j.status}" for j in jobs))
            continue
        chunks = [c async for c in brain.send(line)]
        print_fn("brain> " + "".join(chunks))


async def _run_repl(cfg: BrainConfig) -> None:
    pull_repos(cfg.repos)
    brain = Brain(cfg, _always_yes)
    await brain.start()
    try:
        await repl(brain)
    finally:
        await brain.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="synthia-brain")
    parser.add_argument("command", choices=["repl", "telegram"])
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("-v", "--verbose", action="store_true")
    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return 2
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    cfg = load_brain_config(path=args.config)
    if args.command == "repl":
        asyncio.run(_run_repl(cfg))
        return 0
    from synthia.brain.transports.telegram import run_telegram

    return run_telegram(cfg)


if __name__ == "__main__":
    sys.exit(main())
