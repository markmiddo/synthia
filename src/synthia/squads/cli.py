"""`synthia-squad`: drive a squad from a director's pane, or start and stop jobs."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from synthia.herdr import HerdrError
from synthia.squads.engine import DEFAULT_WAIT_S, Engine
from synthia.squads.model import SquadError

REPO_SQUADS = Path(__file__).resolve().parents[3] / "squads"
AGENTS_DIR = Path.home() / ".claude" / "agents"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="synthia-squad", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name: str, *args: str) -> argparse.ArgumentParser:
        s = sub.add_parser(name)
        for a in args:
            s.add_argument(a)
        return s

    add("hire", "role", "brief")
    add("ask", "name", "text")
    s = add("read", "name")
    s.add_argument("--lines", type=int, default=80)
    s = add("wait", "name")
    s.add_argument("--timeout", type=float, default=DEFAULT_WAIT_S)
    add("dismiss", "name")
    add("log", "text")
    add("deliver", "file")
    sub.add_parser("done")
    s = add("start", "squad", "brief")
    s.add_argument("--slug")
    s = sub.add_parser("status")
    s.add_argument("job", nargs="?")
    add("stop", "job")
    s = add("install", "squad")
    s.add_argument("--force", action="store_true")
    s.add_argument("--source", type=Path, default=REPO_SQUADS)
    return p


def _caller_job(engine: Engine) -> tuple[str, str]:
    pane = os.environ.get("HERDR_PANE_ID", "")
    m = engine.member_for_pane(pane)
    if m.job is None:
        raise SquadError("the calling agent is not part of a squad job")
    return pane, m.job


def run(args: argparse.Namespace, engine: Engine) -> str:
    cmd = args.cmd
    pane = os.environ.get("HERDR_PANE_ID", "")
    if cmd == "hire":
        member = engine.member_for_pane(pane)
        return engine.hire(engine.job_path(member), args.role, args.brief, pane)
    if cmd == "ask":
        _, job = _caller_job(engine)
        engine.ask(args.name, args.text, job)
        return f"sent to {args.name}"
    if cmd == "read":
        _, job = _caller_job(engine)
        return engine.read(args.name, args.lines, job)
    if cmd == "wait":
        _, job = _caller_job(engine)
        return engine.wait(args.name, args.timeout, job)
    if cmd == "dismiss":
        _, job = _caller_job(engine)
        engine.dismiss(args.name, job)
        return f"dismissed {args.name}"
    if cmd == "log":
        engine.log(pane, args.text)
        return "logged"
    if cmd == "deliver":
        return f"delivered {engine.deliver(pane, Path(args.file).expanduser())}"
    if cmd == "done":
        return engine.done(pane)
    if cmd == "start":
        info = engine.start_job(args.squad, args.brief, args.slug)
        return f"{info.job} started; director {info.agent_name}; desk {info.path}"
    if cmd == "status":
        rows = engine.status(args.job)
        if not rows:
            return "no jobs"
        return "\n".join(
            f"{r['squad']}/{r['job']}  {r['state']}  live: {', '.join(r['live']) or '-'}"
            f"  {r['last']}"
            for r in rows
        )
    if cmd == "stop":
        return "stopped " + ", ".join(engine.stop_job(args.job))
    if cmd == "install":
        return engine.install(args.squad, args.source, AGENTS_DIR, args.force)
    raise SquadError(f"unknown command {cmd}")


def main(argv: list[str] | None = None, engine: Engine | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(run(args, engine or Engine()))
    except (SquadError, HerdrError) as exc:
        print(f"synthia-squad: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
