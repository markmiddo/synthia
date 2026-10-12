"""The HUD Inbox: finished work lands here, one JSON file per item.

Items live at `~/.local/share/synthia/inbox/items/<id>.json` (override the directory with
`SYNTHIA_INBOX_DIR`). The HUD owns `state`, `note` and `decided_at`; this module owns the
rest and never writes the HUD's fields: every write re-reads the file first and merges
only what Python owns. Writes are atomic (tmp + os.replace).
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

VERSION = 1
ARCHIVE_DAYS = 30
CHANNELS = ("desk", "telegram", "email")
KINDS = {
    ".json": "json",
    ".md": "md",
    ".png": "png",
    ".jpg": "jpg",
    ".jpeg": "jpg",
    ".pdf": "pdf",
    ".mp4": "mp4",
}
# Fields Python owns and may rewrite; everything else in an existing file is left alone.
_OWNED = ("title", "summary_md", "desk", "deliverables", "director")


def default_root() -> Path:
    env = os.environ.get("SYNTHIA_INBOX_DIR")
    if env:
        return Path(env)
    return Path.home() / ".local" / "share" / "synthia" / "inbox" / "items"


def _now() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-") or "item"


def _path(root: Path, item_id: str) -> Path:
    # Ids become file names: refuse anything that could leave the directory.
    if not re.fullmatch(r"[A-Za-z0-9._-]+", item_id) or item_id.startswith("."):
        raise ValueError(f"bad inbox id {item_id!r}")
    return root / f"{item_id}.json"


@contextlib.contextmanager
def _locked(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    with open(root / ".lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, item: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def _find(root: Path, source: str, squad: str | None, job: str) -> dict[str, Any] | None:
    for p in sorted(root.glob("*.json")):
        item = _read(p)
        if item and item.get("source") == source and item.get("job") == job:
            if item.get("squad") == squad:
                return item
    return None


def deliverables_of(job_path: Path) -> list[dict[str, Any]]:
    out_dir = job_path / "out"
    found: list[dict[str, Any]] = []
    try:
        files = sorted(p for p in out_dir.iterdir() if p.is_file())
    except OSError:
        return found
    for p in files:
        if p.name == "summary.md" or p.name.startswith("."):
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        kind = KINDS.get(p.suffix.lower(), "other")
        found.append({"path": str(p.resolve()), "name": p.name, "kind": kind, "bytes": size})
    return found


def _new_item(
    item_id: str, source: str, squad: str | None, job: str, title: str, summary: str
) -> dict[str, Any]:
    return {
        "version": VERSION,
        "id": item_id,
        "created_at": _now().isoformat(),
        "source": source,
        "squad": squad,
        "job": job,
        "title": title,
        "summary_md": summary,
        "desk": None,
        "deliverables": [],
        "director": None,
        "state": "new",
        "note": None,
        "decided_at": None,
        "notified": {c: False for c in CHANNELS},
    }


def _upsert(
    root: Path, fresh: dict[str, Any], source: str, squad: str | None, job: str
) -> dict[str, Any]:
    """Create `fresh`, or refresh the existing item for the same source+squad+job."""
    with _locked(root):
        existing = _find(root, source, squad, job)
        if existing is None:
            _write(_path(root, fresh["id"]), fresh)
            prune(root)
            return fresh
        if existing.get("state", "new") != "new":
            return existing  # decided by Mark: leave it exactly as the HUD left it
        merged = {**existing, **{k: fresh[k] for k in _OWNED}}
        if merged != existing:
            _write(_path(root, existing["id"]), merged)
        return merged


def create_from_squad(
    job_path: Path | str,
    squad: str,
    job: str,
    director: str | None,
    squad_name: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Item for a finished squad job: out/summary.md plus out/* as deliverables."""
    root = root or default_root()
    job_path = Path(job_path)
    try:
        summary = (job_path / "out" / "summary.md").read_text(errors="replace")
    except OSError:
        summary = ""
    name = squad_name or squad.replace("-", " ").capitalize()
    topic = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", job)
    topic = re.sub(r"-\d+$", "", topic).replace("-", " ").strip() or job
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    fresh = _new_item(f"{stamp}-{_slug(squad)}-{_slug(topic)}", "squad", squad, job, "", summary)
    fresh.update(
        title=f"{name}: {topic}",
        desk=str(job_path),
        deliverables=deliverables_of(job_path),
        director=director,
    )
    return _upsert(root, fresh, "squad", squad, job)


def create_from_job(rec: Any, root: Path | None = None) -> dict[str, Any]:
    """Item for a finished brain background job (a JobRecord)."""
    root = root or default_root()
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    fresh = _new_item(
        f"{stamp}-job-{_slug(rec.name)}-{_slug(rec.id)[-8:]}",
        "job",
        None,
        rec.id,
        rec.name,
        rec.summary or "",
    )
    return _upsert(root, fresh, "job", None, rec.id)


def get(item_id: str, root: Path | None = None) -> dict[str, Any] | None:
    try:
        return _read(_path(root or default_root(), item_id))
    except ValueError:
        return None


def list_items(state: str | None = None, root: Path | None = None) -> list[dict[str, Any]]:
    """Newest first, optionally only one state."""
    items = [i for p in (root or default_root()).glob("*.json") if (i := _read(p)) is not None]
    if state is not None:
        items = [i for i in items if i.get("state") == state]
    return sorted(items, key=lambda i: str(i.get("created_at", "")), reverse=True)


def mark_notified(item_id: str, channel: str, root: Path | None = None) -> bool:
    """Flip one `notified` flag, re-reading first so a HUD decision is never clobbered."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    root = root or default_root()
    with _locked(root):
        path = _path(root, item_id)
        item = _read(path)
        if item is None:
            return False
        notified = dict(item.get("notified") or {})
        if notified.get(channel):
            return True
        notified[channel] = True
        item["notified"] = {**{c: False for c in CHANNELS}, **notified}
        _write(path, item)
    return True


def prune(root: Path | None = None) -> int:
    """Delete archived items older than 30 days (by decision time, else creation time)."""
    root = root or default_root()
    cutoff = _now() - timedelta(days=ARCHIVE_DAYS)
    removed = 0
    for p in root.glob("*.json"):
        item = _read(p)
        if not item or item.get("state") != "archived":
            continue
        stamp = item.get("decided_at") or item.get("created_at")
        try:
            when = datetime.fromisoformat(str(stamp))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.astimezone()
        if when < cutoff:
            with contextlib.suppress(OSError):
                p.unlink()
                removed += 1
    return removed


# ---- the short lines routing speaks or texts ----


def _topic(item: dict[str, Any]) -> tuple[str, str]:
    title = str(item.get("title") or "A job")
    head, sep, tail = title.partition(": ")
    return (head, tail) if sep else ("", title)


def desk_line(item: dict[str, Any], ok: bool = True) -> str:
    """One spoken sentence for Mark at his desk."""
    head, topic = _topic(item)
    if not ok:
        return f"{topic or head} ran into trouble. Details are in your inbox."
    if head:
        return f"{head}'s {topic} is ready in your inbox."
    return f"{topic} is done. It's in your inbox."


def _first_sentence(md: str, limit: int = 140) -> str:
    for line in md.splitlines():
        line = re.sub(r"[#*_`>\-\s]+", " ", line, count=1).strip()
        line = re.sub(r"[*_`]", "", line)
        if len(line) > 20:
            cut = re.split(r"(?<=[.!?])\s", line, maxsplit=1)[0]
            return cut if len(cut) <= limit else cut[: limit - 1].rstrip() + "…"
    return ""


def away_line(item: dict[str, Any], ok: bool = True) -> str:
    """The one short text message sent to Telegram when Mark is away from the desk."""
    head, topic = _topic(item)
    label = f"{head}: {topic}" if head else topic
    n = len(item.get("deliverables") or [])
    detail = _first_sentence(str(item.get("summary_md") or ""))
    if not ok:
        text = f"{label} failed."
    else:
        text = f"{label} is ready for review"
        if n:
            text += f" ({n} file{'s' if n != 1 else ''})"
        text += "."
    if detail:
        text += f" {detail}"
    return f"{text} Say 'email it' to read it on your phone."
