"""Email an inbox item to Mark as a readable HTML message, via the Gmail API.

The only recipient ever allowed is Mark's own address: Synthia must not be able to message
customers or anyone else from here. The access token comes from the email-triage helper
script and is never logged.
"""

from __future__ import annotations

import base64
import html
import io
import json
import logging
import re
import subprocess
from email.message import EmailMessage
from email.utils import make_msgid
from pathlib import Path
from typing import Any, Callable

import markdown

from synthia import inbox

logger = logging.getLogger(__name__)

ALLOWED_RECIPIENT = "mm@eventflo.io"
TOKEN_SCRIPT = Path.home() / ".claude" / "skills" / "email-triage" / "refresh-token.sh"
TOKEN_ACCOUNT = "eventflo"
MAX_IMAGE_BYTES = 2 * 1024 * 1024
GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
# Scopes under which messages.send is allowed, and those under which drafts.create is.
SEND_SCOPES = {
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://mail.google.com/",
}
DRAFT_SCOPES = SEND_SCOPES | {"https://www.googleapis.com/auth/gmail.compose"}
TEXT_LIMIT = 200_000

CSS = (
    "body{font:16px/1.55 -apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#1a1a1a;"
    "max-width:680px;margin:0 auto;padding:16px}h1{font-size:24px}h2{font-size:19px;"
    "margin-top:28px}.file{border-top:1px solid #ddd;margin-top:32px;padding-top:8px}"
    ".note{color:#777;font-size:13px}pre{background:#f4f4f4;padding:10px;overflow:auto;"
    "font-size:13px}dt{font-weight:600;margin-top:12px}dd{margin:4px 0 0 0}img{max-width:100%}"
)


class EmailError(RuntimeError):
    """The email could not be built or sent; the message is safe to read aloud."""


def md_html(text: str) -> str:
    return str(markdown.markdown(text, extensions=["extra", "sane_lists"]))


def _esc(text: Any) -> str:
    return html.escape(str(text))


def render_payload(data: dict[str, Any]) -> str:
    """A blog.Payload: title, excerpt, markdown body, FAQ, and the notes Mark must check."""
    parts = [f"<h1>{_esc(data.get('title', ''))}</h1>"]
    if data.get("excerpt"):
        parts.append(f"<p><em>{_esc(data['excerpt'])}</em></p>")
    if data.get("body"):
        parts.append(md_html(str(data["body"])))
    faq = [f for f in data.get("faq") or [] if isinstance(f, dict)]
    if faq:
        parts.append("<h2>FAQ</h2><dl>")
        for f in faq:
            parts.append(
                f"<dt>{_esc(f.get('question', ''))}</dt><dd>{_esc(f.get('answer', ''))}</dd>"
            )
        parts.append("</dl>")
    meta = []
    if data.get("tags"):
        meta.append(f"Tags: {', '.join(_esc(t) for t in data['tags'])}")
    if data.get("targetQuery"):
        meta.append(f"Target query: {_esc(data['targetQuery'])}")
    if meta:
        parts.append(f"<p class='note'>{' &middot; '.join(meta)}</p>")
    warnings = [w for w in data.get("warnings") or [] if w]
    if warnings:
        parts.append("<h2>Check before approving</h2><ul>")
        parts += [f"<li>{_esc(w)}</li>" for w in warnings]
        parts.append("</ul>")
    return "".join(parts)


def _is_payload(data: Any) -> bool:
    return isinstance(data, dict) and "title" in data and "body" in data


def _shrink_image(raw: bytes, mime: str) -> tuple[bytes, str] | None:
    """Fit an oversize image under the cap with Pillow; None when that is not possible."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        opened = Image.open(io.BytesIO(raw))
        opened.load()
        img = opened.convert("RGB")
        for max_side, quality in ((1600, 85), (1200, 80), (900, 70), (600, 60)):
            work = img.copy()
            work.thumbnail((max_side, max_side))
            buf = io.BytesIO()
            work.save(buf, "JPEG", quality=quality, optimize=True)
            if buf.tell() <= MAX_IMAGE_BYTES:
                return buf.getvalue(), "image/jpeg"
    except Exception:
        logger.warning("could not recompress an inbox image", exc_info=True)
    return None


class Rendered:
    def __init__(self) -> None:
        self.html = ""
        # (cid without angle brackets, bytes, mime type, file name)
        self.images: list[tuple[str, bytes, str, str]] = []


def render_item(item: dict[str, Any]) -> Rendered:
    """Build the HTML body, with CID references for images, from an inbox item."""
    out = Rendered()
    body = [f"<h1>{_esc(item.get('title', ''))}</h1>", md_html(str(item.get("summary_md") or ""))]
    other: list[str] = []
    for d in item.get("deliverables") or []:
        path, name, kind = Path(d.get("path", "")), str(d.get("name", "")), d.get("kind")
        if kind in ("md", "json"):
            try:
                text = path.read_text(errors="replace")[:TEXT_LIMIT]
            except OSError:
                other.append(f"{_esc(name)} (could not be read)")
                continue
            if kind == "md":
                section = md_html(text)
            else:
                try:
                    data = json.loads(text)
                except ValueError:
                    data = None
                if _is_payload(data):
                    section = render_payload(data)
                else:
                    pretty = json.dumps(data, indent=2) if data is not None else text
                    section = f"<pre>{_esc(pretty)}</pre>"
            body.append(f"<div class='file'><p class='note'>{_esc(name)}</p>{section}</div>")
        elif kind in ("png", "jpg"):
            try:
                raw = path.read_bytes()
            except OSError:
                other.append(f"{_esc(name)} (could not be read)")
                continue
            mime = "image/png" if kind == "png" else "image/jpeg"
            if len(raw) > MAX_IMAGE_BYTES:
                shrunk = _shrink_image(raw, mime)
                if shrunk is None:
                    other.append(f"{_esc(name)} (image over 2 MB, not attached; see it in the HUD)")
                    continue
                raw, mime = shrunk
            cid = make_msgid(domain="synthia.local")[1:-1]
            out.images.append((cid, raw, mime, name))
            body.append(
                f"<div class='file'><p class='note'>{_esc(name)}</p>"
                f"<img src='cid:{cid}' alt='{_esc(name)}'></div>"
            )
        else:
            size = d.get("bytes")
            other.append(f"{_esc(name)}" + (f" ({int(size) // 1024} KB)" if size else ""))
    if other:
        body.append(
            "<div class='file'><p class='note'>Also on the desk, not in this email:</p><ul>"
        )
        body += [f"<li>{o}</li>" for o in other]
        body.append("</ul></div>")
    out.html = f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>{''.join(body)}</body></html>"
    return out


def build_message(item: dict[str, Any], to: str = ALLOWED_RECIPIENT) -> EmailMessage:
    if to.strip().lower() != ALLOWED_RECIPIENT:
        raise EmailError(f"I only email {ALLOWED_RECIPIENT}; refusing to send to anyone else.")
    rendered = render_item(item)
    msg = EmailMessage()
    msg["To"] = ALLOWED_RECIPIENT
    msg["Subject"] = f"{item.get('title') or 'Synthia'} — for review"
    plain = re.sub(r"<[^>]+>", "", re.sub(r"</(p|h\d|li|div|dd|dt)>", "\n", rendered.html))
    msg.set_content(html.unescape(re.sub(r"<style.*?</style>", "", plain, flags=re.S)).strip())
    msg.add_alternative(rendered.html, subtype="html")
    html_part = msg.get_payload()[1]  # type: ignore[index]
    for cid, raw, mime, name in rendered.images:
        maintype, _, subtype = mime.partition("/")
        html_part.add_related(  # type: ignore[union-attr]
            raw, maintype, subtype, cid=f"<{cid}>", filename=name
        )
    return msg


def fetch_token() -> str:
    try:
        res = subprocess.run(
            [str(TOKEN_SCRIPT), TOKEN_ACCOUNT], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise EmailError("I could not get a Gmail token.") from exc
    token = res.stdout.strip()
    if res.returncode != 0 or not token:
        raise EmailError("I could not get a Gmail token.")
    return token


def token_scopes(token: str, http_get: Callable[..., Any]) -> set[str]:
    resp = http_get(TOKENINFO, params={"access_token": token}, timeout=15)
    if resp.status_code != 200:
        raise EmailError("Gmail did not accept the token.")
    return set(str(resp.json().get("scope", "")).split())


def send_item(
    item_id: str,
    root: Path | None = None,
    token_fn: Callable[[], str] = fetch_token,
    http_get: Callable[..., Any] | None = None,
    http_post: Callable[..., Any] | None = None,
) -> str:
    """Email the item to Mark (or leave a draft if sending is not allowed). Returns a sentence."""
    import requests

    http_get = http_get or requests.get
    http_post = http_post or requests.post
    item = inbox.get(item_id, root)
    if item is None:
        raise EmailError(f"There is no inbox item {item_id}.")
    msg = build_message(item)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    token = token_fn()
    headers = {"Authorization": f"Bearer {token}"}
    scopes = token_scopes(token, http_get)
    if not scopes & DRAFT_SCOPES:
        raise EmailError("The Gmail token has no permission to send or draft.")
    if scopes & SEND_SCOPES:
        resp = http_post(f"{GMAIL}/messages/send", headers=headers, json={"raw": raw}, timeout=60)
        if resp.status_code in (200, 201):
            inbox.mark_notified(item["id"], "email", root)
            return f"Emailed {item.get('title')} to {ALLOWED_RECIPIENT}."
        if resp.status_code != 403:
            raise EmailError(f"Gmail refused the send (status {resp.status_code}).")
    # No send permission (or a 403 on send): leave it as a draft instead.
    resp = http_post(f"{GMAIL}/drafts", headers=headers, json={"message": {"raw": raw}}, timeout=60)
    if resp.status_code not in (200, 201):
        raise EmailError(f"Gmail refused the draft (status {resp.status_code}).")
    inbox.mark_notified(item["id"], "email", root)
    return (
        f"I could not send it, so I left a draft in your Gmail for {item.get('title')}. "
        "Open Drafts to send it."
    )
