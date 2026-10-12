"""The squad engine: start a job, hire specialists, talk to them, dismiss them, stop.

Importable without claude_agent_sdk. All herdr access goes through the injected `herdr`
module, so tests use a fake. Only panes in the registry are ever closed.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from synthia import herdr as _herdr
from synthia import inbox
from synthia.squads import desk
from synthia.squads.model import DEFAULT_CONFIG_DIR, Squad, SquadError, load_squad
from synthia.squads.registry import DEFAULT_ROOT, Member, Registry, now_iso

logger = logging.getLogger(__name__)

WORKSPACE = "squads"
EVENTS_FILE = "events.jsonl"
REVIEW_KIND = "review"
DEFAULT_WAIT_S = 120


@dataclass
class JobInfo:
    job: str
    path: Path
    agent_name: str
    pane_id: str


SUMMARY_DIGEST_CHARS = 2500


def _summary_digest(job_path: Path) -> str:
    """The head of the director's out/summary.md, so Synthia can say what the job found."""
    try:
        text = (job_path / "out" / "summary.md").read_text(errors="replace")
    except OSError:
        return ""
    if len(text) <= SUMMARY_DIGEST_CHARS:
        return text.strip()
    return text[:SUMMARY_DIGEST_CHARS].rsplit("\n", 1)[0].strip() + "\n[...]"


class Engine:
    def __init__(
        self,
        root: Path = DEFAULT_ROOT,
        config_dir: Path = DEFAULT_CONFIG_DIR,
        herdr: ModuleType | Any = _herdr,
        today: Any = date.today,
    ) -> None:
        self.root = root
        self.config_dir = config_dir
        self.herdr = herdr
        self._today = today
        self.registry = Registry(root, live_panes=self._live_panes)

    def _live_panes(self) -> set[str]:
        return {a["pane_id"] for a in self.herdr.agent_list() if a.get("pane_id")}

    # ---- lookups ----

    def squad(self, squad_id: str) -> Squad:
        return load_squad(squad_id, self.config_dir)

    def _member(self, name: str, job: str | None = None) -> Member:
        m = self.registry.find_live(name)
        if m is None:
            raise SquadError(f"{name} is not one of Synthia's agents; refusing")
        if job is not None and m.job != job:
            raise SquadError(f"{name} is not part of job {job}")
        return m

    def job_path(self, member: Member) -> Path:
        if not member.squad or not member.job:
            raise SquadError(f"{member.agent_name} is not part of a squad job")
        return desk.job_dir(self.root, member.squad, member.job)

    def member_for_pane(self, pane_id: str) -> Member:
        m = self.registry.get(pane_id)
        if m is None or not m.live:
            raise SquadError(f"pane {pane_id or '(unset)'} is not a live squad member")
        return m

    def _live_names(self) -> set[str]:
        names = {m.agent_name for m in self.registry.live()}
        for agent in self.herdr.agent_list():
            n = agent.get("name") or agent.get("agent_name")
            if n:
                names.add(str(n))
        return names

    def _unique_name(self, base: str, numbered: bool) -> str:
        taken = self._live_names()
        base = base[:28]
        if not numbered and base not in taken:
            return base
        n = 1 if numbered else 2
        while f"{base}-{n}" in taken:
            n += 1
        return f"{base}-{n}"

    def _open_pane(self, cwd: str, near: str | None = None) -> str:
        """A fresh shell pane: next to `near`, or in the squads workspace."""
        if near is not None:
            return str(self.herdr.split(near, self.herdr.pick_direction(near), cwd))
        anchor = str(self.herdr.ensure_workspace(WORKSPACE, cwd))
        if anchor in self._live_panes():
            return str(self.herdr.split(anchor, self.herdr.pick_direction(anchor), cwd))
        return anchor

    def _launch(
        self,
        name: str,
        cwd: str,
        model: str | None,
        agent: str | None,
        near: str | None,
    ) -> str:
        pane = self._open_pane(cwd, near)
        try:
            self.herdr.start_claude(name, pane, model, agent)
        except Exception as exc:
            self._close_quietly(pane)
            if "agent_not_ready" in str(exc):
                # Usually Claude's "do you trust this folder?" prompt for a cwd it has not seen.
                raise SquadError(
                    f"{name} stopped at a startup question in {cwd} (often the folder-trust "
                    "prompt). Open Claude there once and trust the folder, then retry."
                ) from exc
            raise
        return pane

    def _close_quietly(self, pane: str) -> None:
        try:
            self.herdr.close_pane(pane)
        except Exception:
            pass

    # ---- plain agents (opened by Synthia, no squad) ----

    def open_agent(self, name: str, cwd: str, prompt: str, model: str | None = None) -> str:
        if not self.herdr.valid_name(name):
            raise SquadError(
                f"agent names look like [a-z][a-z0-9_-], up to 32 characters: {name!r}"
            )
        if name in self._live_names():
            raise SquadError(f"an agent called {name} is already running")
        directory = Path(cwd).expanduser()
        if not directory.is_dir():
            raise SquadError(f"{cwd} is not a folder")
        pane = self._launch(name, str(directory), model, None, None)
        self.registry.add(
            pane,
            Member(name, None, None, "agent", name, None, started_at=now_iso()),
        )
        try:
            self.herdr.agent_prompt(name, prompt)
        except Exception:
            self.close_agent(name)
            raise
        return name

    def close_agent(self, name: str) -> None:
        """Close an agent Synthia opened. Anything not in the registry is refused."""
        self._dismiss(self._member(name))

    # ---- jobs ----

    def start_job(self, squad_id: str, brief: str, slug: str | None = None) -> JobInfo:
        squad = self.squad(squad_id)
        job, path = desk.create(
            self.root, squad.id, brief, slug or " ".join(brief.split()[:4]), self._today()
        )
        director = squad.role(squad.director)
        name = self._unique_name(f"{squad.id}-director", numbered=False)
        try:
            pane = self._launch(name, str(squad.cwd), director.model, director.id, None)
        except Exception as exc:
            desk.set_state(path, "stopped", "synthia", f"director failed to start: {exc}")
            raise
        self.registry.add(
            pane,
            Member(name, squad.id, job, director.id, director.title, None, started_at=now_iso()),
        )
        try:
            self.herdr.rename(pane, f"{squad.name}: {director.title}")
        except Exception:
            pass
        desk.set_state(path, "working", "synthia", f"{name} started")
        prompt = (
            f"You are the {director.title} of the {squad.name} squad. Brief from Mark:\n\n"
            f"{brief.strip()}\n\n"
            f"Your job desk: {path}\n"
            "Deliverables go in out/ (use `synthia-squad deliver <file>`). Drive your team with "
            '`synthia-squad`: hire <role> "<brief>", ask <name> "<text>", read <name>, '
            'wait <name>, dismiss <name>, log "<text>", done. '
            f"Roles you may hire: {', '.join(director.hires) or 'none'}. "
            f"At most {squad.cap} specialists live at once."
        )
        try:
            self.herdr.agent_prompt(name, prompt)
        except Exception:
            self.stop_job(job)
            raise
        return JobInfo(job, path, name, pane)

    def hire(self, job_path: Path, role: str, brief: str, parent_pane: str) -> str:
        parent = self.member_for_pane(parent_pane)
        if parent.squad is None or parent.job is None:
            raise SquadError(f"{parent.agent_name} is not part of a squad job")
        if self.job_path(parent) != job_path:
            raise SquadError("that job desk does not belong to the caller")
        squad = self.squad(parent.squad)
        parent_role = squad.role(parent.role)
        if role not in parent_role.hires:
            allowed = ", ".join(parent_role.hires) or "nobody"
            raise SquadError(f"{parent.title} may not hire {role}; they can hire: {allowed}")
        spec = squad.role(role)
        with desk.locked(job_path, "hire.lock"):
            self.registry.prune()
            specialists = [m for m in self.registry.live(parent.job) if m.parent is not None]
            if len(specialists) >= squad.cap:
                raise SquadError(f"cap reached: {squad.cap} specialists already live in this job")
            name = self._unique_name(f"{role}", numbered=True)
            work = desk.work_dir(job_path, role)
            pane = self._launch(name, str(squad.cwd), spec.model, spec.id, parent_pane)
            self.registry.add(
                pane,
                Member(
                    name,
                    squad.id,
                    parent.job,
                    spec.id,
                    spec.title,
                    parent_pane,
                    started_at=now_iso(),
                ),
            )
        try:
            self.herdr.rename(pane, f"{squad.name}: {spec.title}")
        except Exception:
            pass
        desk.log(job_path, parent.agent_name, f"hired {name} ({spec.title})")
        prompt = (
            f"You are the {spec.title} in the {squad.name} squad, hired by {parent.agent_name}.\n\n"
            f"{brief.strip()}\n\n"
            f"Job desk: {job_path} (read brief.md for the overall brief).\n"
            f"Work in your folder: {work}\n"
            "When you are finished, say so in your final reply, naming the files you produced."
        )
        try:
            self.herdr.agent_prompt(name, prompt)
        except Exception:
            self._dismiss(self._member(name))
            raise
        return name

    def ask(self, name: str, text: str, job: str | None = None) -> None:
        self._member(name, job)
        self.herdr.agent_prompt(name, text)

    def read(self, name: str, lines: int = 80, job: str | None = None) -> str:
        self._member(name, job)
        return str(self.herdr.agent_read(name, lines))

    def wait(self, name: str, timeout_s: float = DEFAULT_WAIT_S, job: str | None = None) -> str:
        self._member(name, job)
        result = self.herdr.agent_wait(name, int(timeout_s * 1000))
        status = result.get("agent_status") or result.get("status")
        return str(status) if status else json.dumps(result)

    def _dismiss(self, member: Member) -> None:
        try:
            self.herdr.close_pane(member.pane_id)
        except _herdr.HerdrError:
            # Already gone is fine; a live pane that will not close is not.
            if member.pane_id in self.herdr.pane_ids():
                raise
        self.registry.end(member.pane_id)

    def dismiss(self, name: str, job: str | None = None) -> None:
        member = self._member(name, job)
        self._dismiss(member)
        if member.squad and member.job:
            desk.log(self.job_path(member), "synthia", f"dismissed {name}")

    def stop_job(self, job: str) -> list[str]:
        job = job.split("/")[-1]
        members = self.registry.live(job)
        if not members:
            raise SquadError(f"no live agents for job {job}")
        ordered = sorted(members, key=lambda m: (m.parent is None, m.started_at))
        stopped: list[str] = []
        for m in ordered:
            self._dismiss(m)
            stopped.append(m.agent_name)
        squad = members[0].squad
        if squad:
            path = desk.job_dir(self.root, squad, job)
            if path.is_dir():
                desk.set_state(path, "stopped", "synthia", "job stopped")
        return stopped

    # ---- from the director's pane ----

    def log(self, pane_id: str, text: str) -> None:
        m = self.member_for_pane(pane_id)
        desk.log(self.job_path(m), m.agent_name, text)

    def deliver(self, pane_id: str, source: Path) -> Path:
        m = self.member_for_pane(pane_id)
        return desk.deliver(self.job_path(m), source, m.agent_name)

    def done(self, pane_id: str) -> str:
        m = self.member_for_pane(pane_id)
        if m.parent is not None or m.squad is None or m.job is None:
            raise SquadError("only a squad director can mark a job done")
        squad = self.squad(m.squad)
        path = self.job_path(m)
        desk.set_state(path, "review", m.agent_name, "ready for review")
        text = f"{squad.name}'s {m.job[11:].replace('-', ' ')} is ready for review"
        event = {
            "at": now_iso(),
            "kind": REVIEW_KIND,
            "squad": squad.id,
            "job": m.job,
            "text": text,
            "desk": str(path),
            "digest": _summary_digest(path),
        }
        try:
            item = inbox.create_from_squad(path, squad.id, m.job, m.agent_name, squad.name)
            event["inbox_id"] = item["id"]
        except Exception:  # the done signal must still go out if the inbox is unwritable
            logger.exception("could not create the inbox item for %s/%s", squad.id, m.job)
        self.root.mkdir(parents=True, exist_ok=True)
        line = (json.dumps(event) + "\n").encode()
        fd = os.open(self.root / EVENTS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line)
        finally:
            os.close(fd)
        return text

    # ---- status ----

    def status(self, job: str | None = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        live = self.registry.live()
        for squad_dir in sorted(p for p in self.root.glob("*/jobs") if p.is_dir()):
            for jp in sorted(squad_dir.iterdir()):
                if not jp.is_dir() or (job and jp.name != job.split("/")[-1]):
                    continue
                st = desk.read_status(jp)
                members = [m.agent_name for m in live if m.job == jp.name]
                last = (st.get("log") or [{}])[-1].get("text", "")
                out.append(
                    {
                        "squad": squad_dir.parent.name,
                        "job": jp.name,
                        "state": st.get("state", ""),
                        "live": members,
                        "last": last,
                        "path": str(jp),
                    }
                )
        return out

    # ---- install ----

    @staticmethod
    def _yaml_role_ids(yaml_path: Path) -> list[str]:
        try:
            data = yaml.safe_load(yaml_path.read_text())
        except (OSError, yaml.YAMLError):
            return []
        roles = data.get("roles") if isinstance(data, dict) else None
        return [str(r) for r in roles] if isinstance(roles, dict) else []

    def install(self, squad_id: str, source: Path, agents_dir: Path, force: bool = False) -> str:
        src = source / squad_id
        yaml_src = src / "squad.yaml"
        if not yaml_src.is_file():
            raise SquadError(f"no squad files at {src}")
        pairs = [(yaml_src, self.config_dir / f"{squad_id}.yaml")]
        own = sorted((src / "agents").glob("*.md"))
        pairs += [(f, agents_dir / f.name) for f in own]
        # Roles the yaml references that the squad does not ship itself come from
        # source/shared/agents/ (one agent file serving several squads).
        have = {f.stem for f in own}
        for role_id in self._yaml_role_ids(yaml_src):
            shared = source / "shared" / "agents" / f"{role_id}.md"
            if role_id not in have and shared.is_file():
                pairs.append((shared, agents_dir / shared.name))
        report: list[str] = []
        for from_, to in pairs:
            data = from_.read_bytes()
            if to.exists():
                if to.read_bytes() == data:
                    report.append(f"unchanged {to}")
                    continue
                if not force:
                    report.append(f"SKIPPED {to} (differs; use --force)")
                    continue
            to.parent.mkdir(parents=True, exist_ok=True)
            to.write_bytes(data)
            report.append(f"installed {to}")
        return "\n".join(report)
