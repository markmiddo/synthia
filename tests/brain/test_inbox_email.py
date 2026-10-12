import base64
import io
import json
from email import message_from_bytes, policy
from types import SimpleNamespace

import pytest
from PIL import Image

from synthia import inbox
from synthia.brain import inbox_email
from synthia.brain.inbox_email import EmailError

PAYLOAD = {
    "title": "How to Sell Out a Doof",
    "excerpt": "A short excerpt.",
    "body": "Intro paragraph.\n\n## Why it works\n\n- point one\n- point two\n",
    "faq": [{"question": "Is it free?", "answer": "No, but it is cheap."}],
    "tags": ["doof"],
    "warnings": ["Check the fee line"],
}


@pytest.fixture
def item(tmp_path):
    job = tmp_path / "growth" / "jobs" / "2026-10-13-posts"
    out = job / "out"
    out.mkdir(parents=True)
    (out / "summary.md").write_text("# Summary\n\nTwo **posts** ready.\n")
    (out / "post.json").write_text(json.dumps(PAYLOAD))
    (out / "notes.md").write_text("## Editor notes\n\nAll fine.")
    img = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(img, "PNG")
    (out / "cover.png").write_bytes(img.getvalue())
    (out / "clip.mp4").write_bytes(b"0" * 2048)
    return inbox.create_from_squad(job, "growth", job.name, "growth-director", "Growth")


class Resp:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def scopes_get(scope):
    def get(url, **kw):
        return Resp(200, {"scope": scope})

    return get


def test_renders_payload_summary_and_cid_image(item):
    msg = inbox_email.build_message(item)
    assert msg["To"] == "mm@eventflo.io"
    assert msg["Subject"] == "Growth: posts — for review"
    body = msg.get_body(("html",)).get_content()
    assert "<h1>How to Sell Out a Doof</h1>" in body
    assert "<em>A short excerpt.</em>" in body
    assert "<h2>Why it works</h2>" in body and "<li>point one</li>" in body
    assert "<dt>Is it free?</dt><dd>No, but it is cheap.</dd>" in body
    assert "Check the fee line" in body
    assert "<strong>posts</strong>" in body  # summary_md rendered as HTML
    assert "<h2>Editor notes</h2>" in body  # an md deliverable rendered too
    assert "clip.mp4" in body  # non-renderable files are listed, not attached
    parsed = message_from_bytes(msg.as_bytes(), policy=policy.default)
    images = [p for p in parsed.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 1
    cid = images[0]["Content-ID"].strip("<>")
    assert f"src='cid:{cid}'" in body
    assert parsed.get_body(("plain",)) is not None


def test_oversize_image_is_recompressed_under_two_mb(item, tmp_path):
    import os

    big = Image.frombytes("RGB", (1800, 1800), os.urandom(1800 * 1800 * 3))
    buf = io.BytesIO()
    big.save(buf, "PNG")
    assert buf.tell() > inbox_email.MAX_IMAGE_BYTES
    from pathlib import Path

    p = Path(item["deliverables"][0]["path"]).parent / "huge.png"
    p.write_bytes(buf.getvalue())
    item = inbox.create_from_squad(item["desk"], "growth", item["job"], "d")
    rendered = inbox_email.render_item(item)
    sizes = {name: (len(raw), mime) for _, raw, mime, name in rendered.images}
    assert sizes["huge.png"][0] <= inbox_email.MAX_IMAGE_BYTES
    assert sizes["huge.png"][1] == "image/jpeg"


def test_oversize_image_without_pillow_is_skipped_with_a_note(item, monkeypatch):
    from pathlib import Path

    p = Path(item["deliverables"][0]["path"]).parent / "huge.png"
    p.write_bytes(b"0" * (inbox_email.MAX_IMAGE_BYTES + 1))
    item = inbox.create_from_squad(item["desk"], "growth", item["job"], "d")
    monkeypatch.setattr(inbox_email, "_shrink_image", lambda raw, mime: None)
    rendered = inbox_email.render_item(item)
    assert "huge.png" not in [n for _, _, _, n in rendered.images]
    assert "huge.png (image over 2 MB, not attached" in rendered.html


def test_recipient_guard_refuses_anyone_else(item):
    with pytest.raises(EmailError, match="only email"):
        inbox_email.build_message(item, to="customer@example.com")
    assert inbox_email.build_message(item, to="MM@eventflo.io")["To"] == "mm@eventflo.io"


def sent_raw(call):
    return base64.urlsafe_b64decode(call["json"]["raw"])


def test_send_uses_the_send_endpoint_and_marks_notified(item):
    calls = []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        return Resp(200, {"id": "m1"})

    out = inbox_email.send_item(
        item["id"],
        token_fn=lambda: "tok",
        http_get=scopes_get("https://www.googleapis.com/auth/gmail.modify"),
        http_post=post,
    )
    assert "Emailed" in out
    assert [c["url"] for c in calls] == [f"{inbox_email.GMAIL}/messages/send"]
    assert calls[0]["headers"] == {"Authorization": "Bearer tok"}
    sent = message_from_bytes(sent_raw(calls[0]), policy=policy.default)
    assert sent["To"] == "mm@eventflo.io"
    assert inbox.get(item["id"])["notified"]["email"] is True


def test_send_falls_back_to_a_draft_when_scope_lacks_send(item):
    calls = []

    def post(url, **kw):
        calls.append(url)
        return Resp(200, {"id": "d1"})

    out = inbox_email.send_item(
        item["id"],
        token_fn=lambda: "tok",
        http_get=scopes_get("https://www.googleapis.com/auth/gmail.compose"),
        http_post=post,
    )
    assert calls == [f"{inbox_email.GMAIL}/drafts"]
    assert "left a draft" in out
    assert inbox.get(item["id"])["notified"]["email"] is True


def test_send_403_falls_back_to_a_draft(item):
    calls = []

    def post(url, **kw):
        calls.append(url)
        return Resp(403 if url.endswith("/send") else 200)

    out = inbox_email.send_item(
        item["id"],
        token_fn=lambda: "tok",
        http_get=scopes_get("https://mail.google.com/"),
        http_post=post,
    )
    assert calls == [f"{inbox_email.GMAIL}/messages/send", f"{inbox_email.GMAIL}/drafts"]
    assert "draft" in out


def test_no_gmail_scope_sends_nothing(item):
    def post(url, **kw):
        raise AssertionError("must not post")

    with pytest.raises(EmailError, match="no permission"):
        inbox_email.send_item(
            item["id"],
            token_fn=lambda: "tok",
            http_get=scopes_get("https://www.googleapis.com/auth/drive"),
            http_post=post,
        )
    assert inbox.get(item["id"])["notified"]["email"] is False


def test_unknown_item_and_token_secret_never_in_errors(item):
    with pytest.raises(EmailError, match="no inbox item"):
        inbox_email.send_item("nope", token_fn=lambda: "SECRET")

    def post(url, **kw):
        return Resp(500)

    with pytest.raises(EmailError) as e:
        inbox_email.send_item(
            item["id"],
            token_fn=lambda: "SECRET",
            http_get=scopes_get("https://mail.google.com/"),
            http_post=post,
        )
    assert "SECRET" not in str(e.value)


async def test_email_tool_latest(item, monkeypatch):
    from synthia.brain.job_tools import make_tools

    seen = []
    monkeypatch.setattr(inbox_email, "send_item", lambda i: seen.append(i) or "Emailed it.")
    tools = {t.name: t for t in make_tools(SimpleNamespace())}
    out = await tools["email_inbox_item"].handler({"id": "latest"})
    assert seen == [item["id"]] and out["content"][0]["text"] == "Emailed it."
    listed = await tools["list_inbox"].handler({})
    assert item["id"] in listed["content"][0]["text"]


def test_plain_text_part_has_no_css():
    from synthia.brain.inbox_email import build_message

    item = {"title": "Growth: covers", "summary_md": "# Two posts\nReady.", "deliverables": []}
    msg = build_message(item)
    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert "font:" not in plain and "{" not in plain
    assert "Two posts" in plain
