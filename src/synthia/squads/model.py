"""Squad definitions, loaded from ~/.config/synthia/squads/<id>.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "synthia" / "squads"
DEFAULT_CAP = 4


class SquadError(RuntimeError):
    """A squad, role, job or registry problem that the caller should read out."""


@dataclass
class Role:
    id: str
    title: str
    model: str | None = None
    hires: list[str] = field(default_factory=list)


@dataclass
class Squad:
    id: str
    name: str
    director: str
    cap: int
    cwd: Path
    roles: dict[str, Role]

    def role(self, role_id: str) -> Role:
        try:
            return self.roles[role_id]
        except KeyError:
            raise SquadError(f"squad {self.id} has no role {role_id!r}") from None


def parse_squad(data: Any, source: str = "squad") -> Squad:
    if not isinstance(data, dict):
        raise SquadError(f"{source}: expected a mapping")
    try:
        squad_id = str(data["id"])
        director = str(data["director"])
        raw_roles = data["roles"]
    except KeyError as exc:
        raise SquadError(f"{source}: missing key {exc.args[0]}") from None
    if not isinstance(raw_roles, dict) or not raw_roles:
        raise SquadError(f"{source}: roles must be a non-empty mapping")
    roles: dict[str, Role] = {}
    for rid, body in raw_roles.items():
        body = body or {}
        if not isinstance(body, dict):
            raise SquadError(f"{source}: role {rid} must be a mapping")
        roles[str(rid)] = Role(
            id=str(rid),
            title=str(body.get("title") or rid),
            model=str(body["model"]) if body.get("model") else None,
            hires=[str(h) for h in body.get("hires") or []],
        )
    if director not in roles:
        raise SquadError(f"{source}: director {director!r} is not a role")
    for role in roles.values():
        for hire in role.hires:
            if hire not in roles:
                raise SquadError(f"{source}: {role.id} hires unknown role {hire!r}")
    try:
        cap = int(data.get("cap", DEFAULT_CAP))
    except (TypeError, ValueError):
        raise SquadError(f"{source}: cap must be a number") from None
    cwd = Path(str(data.get("cwd") or "~")).expanduser()
    return Squad(
        id=squad_id,
        name=str(data.get("name") or squad_id),
        director=director,
        cap=cap,
        cwd=cwd,
        roles=roles,
    )


def load_squad(squad_id: str, config_dir: Path = DEFAULT_CONFIG_DIR) -> Squad:
    if "/" in squad_id or squad_id.startswith("."):
        raise SquadError(f"bad squad id {squad_id!r}")
    path = config_dir / f"{squad_id}.yaml"
    if not path.is_file():
        raise SquadError(f"no squad {squad_id!r} installed (looked for {path})")
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SquadError(f"cannot read {path}: {exc}") from exc
    return parse_squad(data, str(path))
