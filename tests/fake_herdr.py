"""A fake `synthia.herdr` module for engine and tool tests. Nothing touches a real herdr."""

from __future__ import annotations

from typing import Any

from synthia.herdr import HerdrError, valid_name


class FakeHerdr:
    HerdrError = HerdrError

    def __init__(self) -> None:
        self.panes: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.prompts: list[tuple[str, str]] = []
        self.closed: list[str] = []
        self.fail_start = False
        self._n = 0
        self.workspace_created = False

    def _new(self) -> str:
        self._n += 1
        return f"w1:p{self._n}"

    def valid_name(self, name: str) -> bool:
        return valid_name(name)

    def agent_list(self) -> list[dict[str, Any]]:
        return [
            {"pane_id": p, "name": a["name"], "cwd": a["cwd"], "agent_status": "idle"}
            for p, a in self.panes.items()
            if a.get("name")
        ]

    def ensure_workspace(self, label: str, cwd: str | None = None) -> str:
        self.calls.append(("ensure_workspace", (label, cwd)))
        for p, a in self.panes.items():
            if not a.get("name"):
                return p
        if not self.panes:
            self.workspace_created = True
        pane = self._new()
        self.panes[pane] = {"name": None, "cwd": cwd}
        return pane

    def pick_direction(self, pane_id: str) -> str:
        return "right"

    def split(self, pane_id: str, direction: str, cwd: str) -> str:
        self.calls.append(("split", (pane_id, direction, cwd)))
        pane = self._new()
        self.panes[pane] = {"name": None, "cwd": cwd}
        return pane

    def start_claude(self, name: str, pane_id: str, model: str | None, agent: str | None) -> dict:
        self.calls.append(("start_claude", (name, pane_id, model, agent)))
        if self.fail_start:
            raise HerdrError("agent_not_ready")
        self.panes[pane_id]["name"] = name
        return {}

    def agent_prompt(self, target: str, text: str, wait: bool = False, timeout_ms=None) -> dict:
        self.prompts.append((target, text))
        return {}

    def agent_read(self, target: str, lines: int = 80) -> str:
        return f"output of {target}"

    def agent_wait(self, target: str, timeout_ms: int = 0) -> dict:
        return {"agent_status": "idle"}

    def close_pane(self, pane_id: str) -> None:
        self.closed.append(pane_id)
        self.panes.pop(pane_id, None)

    def pane_ids(self) -> set[str]:
        return set(self.panes)

    def rename(self, pane_id: str, title: str) -> None:
        self.calls.append(("rename", (pane_id, title)))


SQUAD_YAML = """
id: growth
name: Growth
director: growth-director
cap: 2
cwd: {cwd}
roles:
  growth-director: {{title: Marketing Director, model: claude-opus-5-5, hires: [growth-seo, growth-writer]}}
  growth-seo: {{title: SEO Strategist, model: claude-sonnet-5-5}}
  growth-writer: {{title: Writer, model: claude-sonnet-5-5}}
  growth-editor: {{title: Editor}}
"""


def write_squad(config_dir, cwd) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "growth.yaml").write_text(SQUAD_YAML.format(cwd=cwd))
