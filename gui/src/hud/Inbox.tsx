import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ago } from "./hive";
import { asPayload, coverFor, itemTime, squadLabel, STATE_LABEL, type InboxFile, type InboxItem, type Payload } from "./inbox";
import { Markdown } from "./markdown";
import { call, reasonOf } from "./tauri";

type Filter = "inbox" | "archived";

interface Toast {
  text: string;
  ok: boolean;
}

interface Undo {
  id: string;
  prev: { state: InboxItem["state"]; note: string | null; decided_at: string | null };
  until: number;
}

const UNDO_MS = 10_000;

function CloseIcon() {
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true">
      <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
    </svg>
  );
}

function sizeText(b: number): string {
  return b < 1024 ? `${b} B` : b < 1048576 ? `${Math.round(b / 1024)} KB` : `${(b / 1048576).toFixed(1)} MB`;
}

/** Loads one deliverable's text, once. */
function useFileText(id: string, f: InboxFile, wanted: boolean): { text: string | null; error: string | null } {
  const [s, setS] = useState<{ text: string | null; error: string | null }>({ text: null, error: null });
  useEffect(() => {
    if (!wanted) return;
    let alive = true;
    call<string>("inbox_read_file", { id, path: f.path })
      .then((t) => alive && setS({ text: t, error: null }))
      .catch((e) => alive && setS({ text: null, error: reasonOf(e) }));
    return () => {
      alive = false;
    };
  }, [id, f.path, wanted]);
  return s;
}

function useImage(id: string, f: InboxFile | null): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!f) return;
    let alive = true;
    call<string>("inbox_image", { id, path: f.path })
      .then((u) => alive && setUrl(u))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [id, f]);
  return url;
}

function Article({ id, p, cover }: { id: string; p: Payload; cover: InboxFile | null }) {
  const [raw, setRaw] = useState(false);
  const img = useImage(id, cover);
  return (
    <article className="article">
      {img && <img className="cover" src={img} alt="" />}
      <h1>{p.title}</h1>
      {p.excerpt && <p className="excerpt">{p.excerpt}</p>}
      <Markdown text={p.body} />
      {p.faq.length > 0 && (
        <section className="faq">
          <h4 className="md-h2">Questions</h4>
          {p.faq.map((f, i) => (
            <div key={i}>
              <b>{f.q}</b>
              <p>{f.a}</p>
            </div>
          ))}
        </section>
      )}
      {p.tags.length > 0 && (
        <div className="who">
          {p.tags.map((t) => (
            <span key={t} className="hchip">
              {t}
            </span>
          ))}
        </div>
      )}
      <button type="button" className="link-btn" onClick={() => setRaw((r) => !r)}>
        {raw ? "Hide raw JSON" : "View raw JSON"}
      </button>
      {raw && <pre className="journal">{JSON.stringify(p, null, 2)}</pre>}
    </article>
  );
}

function FileRow({ item, f }: { item: InboxItem; f: InboxFile }) {
  const [err, setErr] = useState<string | null>(null);
  return (
    <div className="frow">
      <span className="ficon">{f.kind === "other" ? "·" : f.kind.toUpperCase()}</span>
      <span className="fname" title={f.path}>
        {f.name}
      </span>
      <em>{sizeText(f.bytes)}</em>
      <button type="button" className="link-btn" onClick={() => call("inbox_open_file", { id: item.id, path: f.path }).catch((e) => setErr(reasonOf(e)))}>
        Open
      </button>
      {err && <p className="co-error">{err}</p>}
    </div>
  );
}

function Deliverable({ item, f, covers }: { item: InboxItem; f: InboxFile; covers: Set<string> }) {
  const isText = f.kind === "json" || f.kind === "md";
  const { text, error } = useFileText(item.id, f, isText);
  const isImage = f.kind === "png" || f.kind === "jpg";
  const img = useImage(item.id, isImage && !covers.has(f.path) ? f : null);
  if (isImage) {
    if (covers.has(f.path)) return null;
    return img ? <img className="dimg" src={img} alt={f.name} /> : <FileRow item={item} f={f} />;
  }
  if (f.kind === "md") {
    return error ? <FileRow item={item} f={f} /> : text === null ? <p className="co-quiet">Reading {f.name}…</p> : <Markdown text={text} />;
  }
  if (f.kind === "json") {
    if (error) return <FileRow item={item} f={f} />;
    if (text === null) return <p className="co-quiet">Reading {f.name}…</p>;
    const p = asPayload(text);
    if (p) return <Article id={item.id} p={p} cover={coverFor(p.slug, item.deliverables)} />;
    return (
      <details className="rawj">
        <summary>{f.name}</summary>
        <pre className="journal">{text.slice(0, 20000)}</pre>
      </details>
    );
  }
  return <FileRow item={item} f={f} />;
}

/** Which image files are used as a post's cover, so they are not shown twice. */
function useCovers(item: InboxItem): Set<string> {
  const [covers, setCovers] = useState<Set<string>>(new Set());
  useEffect(() => {
    let alive = true;
    const jsons = item.deliverables.filter((d) => d.kind === "json");
    Promise.all(jsons.map((d) => call<string>("inbox_read_file", { id: item.id, path: d.path }).catch(() => "")))
      .then((texts) => {
        if (!alive) return;
        const set = new Set<string>();
        for (const t of texts) {
          const p = asPayload(t);
          const c = p ? coverFor(p.slug, item.deliverables) : null;
          if (c) set.add(c.path);
        }
        setCovers(set);
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [item]);
  return covers;
}

function Reader({
  item,
  now,
  onChanged,
  setToast,
  undo,
  setUndo,
}: {
  item: InboxItem;
  now: number;
  onChanged: () => void;
  setToast: (t: Toast | null) => void;
  undo: Undo | null;
  setUndo: (u: Undo | null) => void;
}) {
  const covers = useCovers(item);
  const [busy, setBusy] = useState(false);
  const [composing, setComposing] = useState(false);
  const [note, setNote] = useState("");
  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  useEffect(() => {
    setComposing(false);
    setNote("");
  }, [item.id]);
  useEffect(() => {
    if (composing) noteRef.current?.focus();
  }, [composing]);
  const readOnly = item.state === "approved" || item.state === "archived";
  const canUndo = undo !== null && undo.id === item.id && undo.until > now;

  const decide = (state: "approved" | "archived") => {
    setBusy(true);
    const prev = { state: item.state, note: item.note, decided_at: item.decided_at };
    call<InboxItem>("inbox_decide", { id: item.id, state, note: null })
      .then(() => {
        setUndo({ id: item.id, prev, until: Date.now() + UNDO_MS });
        setToast({ ok: true, text: state === "approved" ? "Approved." : "Archived." });
        onChanged();
      })
      .catch((e) => setToast({ ok: false, text: `I couldn't save that: ${reasonOf(e)}` }))
      .finally(() => setBusy(false));
  };
  const sendBack = () => {
    setBusy(true);
    call<{ how: string; detail: string }>("inbox_send_back", { id: item.id, note })
      .then((r) => {
        setToast({ ok: true, text: r.how === "asked" ? "Sent back. The director has your note." : "Sent back. A revision job is starting." });
        setComposing(false);
        setNote("");
      })
      .catch((e) => setToast({ ok: false, text: reasonOf(e) }))
      .finally(() => {
        setBusy(false);
        onChanged();
      });
  };
  const doUndo = () => {
    if (!undo) return;
    call("inbox_restore", { id: undo.id, state: undo.prev.state, note: undo.prev.note, decided_at: undo.prev.decided_at })
      .then(() => {
        setUndo(null);
        setToast({ ok: true, text: "Put back." });
        onChanged();
      })
      .catch((e) => setToast({ ok: false, text: `I couldn't undo that: ${reasonOf(e)}` }));
  };

  return (
    <div className="reader">
      <header className="rhead">
        <p className="lbl">
          {squadLabel(item).toUpperCase()} · {ago(itemTime(item), now)}
        </p>
        <h2>{item.title}</h2>
        <p className="rstate">
          <span className={`ipill s-${item.state}`}>{STATE_LABEL[item.state]}</span>
          {item.note && item.state === "sent_back" && <span className="rnote">“{item.note}”</span>}
        </p>
      </header>
      <div className="rbody">
        {item.summary_md && (
          <section className="rsummary">
            <Markdown text={item.summary_md} />
          </section>
        )}
        {item.deliverables.length > 0 && <p className="dsec">Deliverables</p>}
        {item.deliverables.map((d) => (
          <Deliverable key={d.path} item={item} f={d} covers={covers} />
        ))}
        {item.deliverables.length === 0 && !item.summary_md && <p className="co-quiet">Nothing was attached to this one.</p>}
      </div>
      <footer className="ractions">
        {composing ? (
          <div className="sendbox">
            <label className="lbl" htmlFor="sb-note">
              WHAT SHOULD CHANGE?
            </label>
            <textarea id="sb-note" ref={noteRef} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Tell the director what to fix. They get this note as written." />
            <div className="co-actions">
              <button type="button" className="primary" disabled={busy || note.trim() === ""} onClick={sendBack}>
                {busy ? "Sending…" : "Send back"}
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => setComposing(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : readOnly ? (
          <div className="ro">
            <span>
              {STATE_LABEL[item.state]}
              {item.decided_at ? ` ${ago(Date.parse(item.decided_at), now)}` : ""}
            </span>
            {canUndo && (
              <button type="button" className="link-btn" onClick={doUndo}>
                Undo
              </button>
            )}
          </div>
        ) : (
          <div className="co-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => decide("approved")}>
              Approve
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => setComposing(true)}>
              Send back
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => decide("archived")}>
              Archive
            </button>
          </div>
        )}
      </footer>
    </div>
  );
}

export function InboxDrawer({
  items,
  initialId,
  onClose,
  reload,
}: {
  items: InboxItem[];
  initialId: string | null;
  onClose: () => void;
  reload: () => void;
}) {
  const [filter, setFilter] = useState<Filter>("inbox");
  const [sel, setSel] = useState<string | null>(initialId);
  const [toast, setToast] = useState<Toast | null>(null);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const shown = useMemo(() => items.filter((i) => (filter === "archived" ? i.state === "archived" : i.state !== "archived")), [items, filter]);
  const current = items.find((i) => i.id === sel) ?? shown[0] ?? null;
  const newCount = items.filter((i) => i.state === "new").length;

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);
  useEffect(() => {
    if (undo && undo.until <= now) setUndo(null);
  }, [undo, now]);
  // Picking an archived filter or a different item keeps the reader on something that exists.
  useEffect(() => {
    if (current && current.id !== sel) setSel(current.id);
  }, [current, sel]);

  const changed = useCallback(() => reload(), [reload]);

  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer inbox" aria-label="Inbox">
        <div className="ilist">
          <div className="ihead">
            <div>
              <p className="eyebrow">Inbox</p>
              <h2>{newCount > 0 ? `${newCount} to review` : "All caught up"}</h2>
            </div>
          </div>
          <div className="dtabs" role="tablist">
            <button type="button" role="tab" aria-selected={filter === "inbox"} className={filter === "inbox" ? "on" : ""} onClick={() => setFilter("inbox")}>
              Inbox
            </button>
            <button type="button" role="tab" aria-selected={filter === "archived"} className={filter === "archived" ? "on" : ""} onClick={() => setFilter("archived")}>
              Archived
            </button>
          </div>
          <ul className="iitems">
            {shown.length === 0 && <li className="co-quiet pad">{filter === "archived" ? "Nothing archived." : "Nothing here yet. Finished work lands here."}</li>}
            {shown.map((i) => (
              <li key={i.id}>
                <button type="button" className={`iitem${current?.id === i.id ? " on" : ""}${i.state === "new" ? " fresh" : ""}`} onClick={() => setSel(i.id)}>
                  <b>{i.title}</b>
                  <span>
                    <em className="hchip">{squadLabel(i)}</em>
                    <time>{ago(itemTime(i), now)}</time>
                    <span className={`ipill s-${i.state}`}>{STATE_LABEL[i.state]}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="ipane">
          <button type="button" className="icon-btn iclose" onClick={onClose} aria-label="Close inbox">
            <CloseIcon />
          </button>
          {current ? (
            <Reader key={current.id} item={current} now={now} onChanged={changed} setToast={setToast} undo={undo} setUndo={setUndo} />
          ) : (
            <p className="co-quiet pad">Pick something on the left to read it.</p>
          )}
          {toast && (
            <div className={`toast ${toast.ok ? "ok" : "bad"}`} role="status">
              <span>{toast.text}</span>
              {undo && toast.ok && undo.until > now && (
                <button
                  type="button"
                  className="link-btn"
                  onClick={() => {
                    call("inbox_restore", { id: undo.id, state: undo.prev.state, note: undo.prev.note, decided_at: undo.prev.decided_at })
                      .then(() => {
                        setUndo(null);
                        setToast({ ok: true, text: "Put back." });
                        reload();
                      })
                      .catch((e) => setToast({ ok: false, text: reasonOf(e) }));
                  }}
                >
                  Undo
                </button>
              )}
            </div>
          )}
        </div>
      </aside>
    </>,
    document.body,
  );
}

export function InboxButton({ count, onClick }: { count: number; onClick: () => void }) {
  return (
    <button type="button" className={`inboxbtn${count > 0 ? " has" : ""}`} onClick={onClick} aria-label={count > 0 ? `Inbox, ${count} to review` : "Inbox"} title="Inbox">
      <svg viewBox="0 0 20 20" aria-hidden="true">
        <path d="M3 11l2-6h10l2 6M3 11v5h14v-5M3 11h4l1 2h4l1-2h4" />
      </svg>
      {count > 0 && <b>{count}</b>}
    </button>
  );
}
