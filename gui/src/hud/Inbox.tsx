import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ago } from "./hive";
import { answerOf, asPayload, callsMade, coverFor, groupOf, isRequired, itemTime, needsMark, pillLabel, QUICK_PHRASES, questionsOf, revisedVersion, squadLabel, withoutSection, type FeedbackEntry, type Group, type InboxFile, type InboxItem, type Payload } from "./inbox";
import { Markdown } from "./markdown";
import { call, reasonOf } from "./tauri";
import type { Fleet } from "./types";

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

type ImageState = { status: "loading" } | { status: "ready"; url: string } | { status: "failed"; reason: string };

/** A downscaled preview of a delivered image (any size). */
function useImage(id: string, f: InboxFile | null): ImageState {
  const [s, setS] = useState<ImageState>({ status: "loading" });
  useEffect(() => {
    if (!f) return;
    let alive = true;
    setS({ status: "loading" });
    call<string>("inbox_image", { id, path: f.path })
      .then((u) => alive && setS({ status: "ready", url: u }))
      .catch((e) => alive && setS({ status: "failed", reason: reasonOf(e) }));
    return () => {
      alive = false;
    };
  }, [id, f]);
  return s;
}

function openFull(id: string, f: InboxFile): void {
  call("inbox_open_file", { id, path: f.path }).catch(() => {});
}

/** The preview, with an Open full size button; a failure is a clear row, never empty space. */
function PreviewImage({ id, f, className, alt }: { id: string; f: InboxFile; className?: string; alt: string }) {
  const img = useImage(id, f);
  if (img.status === "failed") {
    return (
      <div className="frow broken">
        <span className="ficon">IMG</span>
        <span className="fname">
          Couldn't preview this image ({f.name}, {sizeText(f.bytes)})
        </span>
        <span />
        <button type="button" className="link-btn" onClick={() => openFull(id, f)}>
          Open
        </button>
      </div>
    );
  }
  if (img.status === "loading") return <div className={`imgwait ${className ?? ""}`}>Preparing preview…</div>;
  return (
    <figure className="pimg">
      <img className={className} src={img.url} alt={alt} />
      <button type="button" className="link-btn" onClick={() => openFull(id, f)}>
        Open full size
      </button>
    </figure>
  );
}

function Article({ id, p, cover }: { id: string; p: Payload; cover: InboxFile | null }) {
  const [raw, setRaw] = useState(false);
  return (
    <article className="article">
      {cover && <PreviewImage id={id} f={cover} className="cover" alt="" />}
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
  if (isImage) {
    if (covers.has(f.path)) return null;
    return <PreviewImage id={item.id} f={f} className="dimg" alt={f.name} />;
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

/** Which image files are a post's cover (so they are not shown twice), and each post's title. */
function useInfo(item: InboxItem): { covers: Set<string>; titles: Map<string, string> } {
  const [info, setInfo] = useState<{ covers: Set<string>; titles: Map<string, string> }>({ covers: new Set(), titles: new Map() });
  useEffect(() => {
    let alive = true;
    const jsons = item.deliverables.filter((d) => d.kind === "json");
    Promise.all(jsons.map((d) => call<string>("inbox_read_file", { id: item.id, path: d.path }).catch(() => "")))
      .then((texts) => {
        if (!alive) return;
        const covers = new Set<string>();
        const titles = new Map<string, string>();
        texts.forEach((t, i) => {
          const p = asPayload(t);
          if (!p) return;
          titles.set(jsons[i].path, p.title);
          const c = coverFor(p.slug, item.deliverables);
          if (c) {
            covers.add(c.path);
            titles.set(c.path, `Cover: ${p.title}`);
          }
        });
        setInfo({ covers, titles });
      })
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [item]);
  return info;
}

/** The questions a report needs answered, as a highlighted box with Yes / No on each. */
function NeedsBox({ item, busy, onAnswer }: { item: InboxItem; busy: boolean; onAnswer: (question: string, answer: "yes" | "no", note: string) => void }) {
  const questions = questionsOf(item.summary_md);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [open, setOpen] = useState<Record<string, boolean>>({});
  if (questions.length === 0) return null;
  return (
    <section className="needsbox" aria-label="Needs you">
      <p className="lbl">NEEDS YOU</p>
      {questions.map((q) => {
        const done = answerOf(item, q);
        return (
          <div className="nq" key={q}>
            <p>{q}</p>
            {done ? (
              <p className="nans">
                Answered <b>{done.answer}</b>
                {done.note ? ` · ${done.note}` : ""}
              </p>
            ) : (
              <>
                <div className="nbtns">
                  <button type="button" className="primary sm" disabled={busy} onClick={() => onAnswer(q, "yes", notes[q] ?? "")}>
                    Yes
                  </button>
                  <button type="button" className="ghost sm" disabled={busy} onClick={() => onAnswer(q, "no", notes[q] ?? "")}>
                    No
                  </button>
                  {!open[q] && (
                    <button type="button" className="link-btn" onClick={() => setOpen((o) => ({ ...o, [q]: true }))}>
                      Add a note
                    </button>
                  )}
                </div>
                {open[q] && (
                  <input
                    className="nnote"
                    value={notes[q] ?? ""}
                    placeholder="Optional note for the squad"
                    onChange={(e) => setNotes((n) => ({ ...n, [q]: e.target.value }))}
                    aria-label={`Note for: ${q}`}
                  />
                )}
              </>
            )}
          </div>
        );
      })}
    </section>
  );
}

const hhmm = (iso: string) => {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? "" : new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
};

function Thread({ item, items, onOpenItem, onOpenJob }: { item: InboxItem; items: InboxItem[]; onOpenItem: (id: string) => void; onOpenJob: (squad: string, job: string) => void }) {
  const thread = item.feedback ?? [];
  if (thread.length === 0) return null;
  return (
    <section className="thread" aria-label="Feedback so far">
      <p className="lbl">FEEDBACK</p>
      {thread.map((fb: FeedbackEntry, i) => {
        const revised = revisedVersion(item, fb, items);
        return (
          <div className="fb" key={`${fb.at}-${i}`}>
            <p>
              <b>You</b> · {hhmm(fb.at)} · on {fb.target?.path ? fb.target.title : "the whole job"}: {fb.note}
            </p>
            <p className="route">
              {fb.routed_to === "revision job" && fb.job ? (
                <>
                  → Revision job {fb.job} started{" "}
                  <button type="button" className="link-btn" onClick={() => onOpenJob(item.squad, fb.job as string)}>
                    Open job
                  </button>
                </>
              ) : fb.routed_to === "not delivered" ? (
                <>→ Saved, but the squad could not be reached</>
              ) : (
                <>→ Sent to {fb.routed_to}</>
              )}
              {revised && (
                <>
                  {" · "}
                  <button type="button" className="link-btn" onClick={() => onOpenItem(revised.id)}>
                    Revised version available →
                  </button>
                </>
              )}
            </p>
          </div>
        );
      })}
    </section>
  );
}

interface Target {
  key: string;
  label: string;
  path: string | null;
  title: string;
}

function Reader({
  item,
  items,
  fleet,
  now,
  onChanged,
  setToast,
  undo,
  setUndo,
  onOpenItem,
  onOpenJob,
}: {
  item: InboxItem;
  items: InboxItem[];
  fleet: Fleet | null;
  now: number;
  onChanged: () => void;
  setToast: (t: Toast | null) => void;
  undo: Undo | null;
  setUndo: (u: Undo | null) => void;
  onOpenItem: (id: string) => void;
  onOpenJob: (squad: string, job: string) => void;
}) {
  const { covers, titles } = useInfo(item);
  const [busy, setBusy] = useState(false);
  const [composing, setComposing] = useState(false);
  const [note, setNote] = useState("");
  const [targetKey, setTargetKey] = useState("job");
  const [mode, setMode] = useState<"revise" | "call">("revise");
  const noteRef = useRef<HTMLTextAreaElement | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    setComposing(false);
    setNote("");
    setTargetKey("job");
  }, [item.id]);
  useEffect(() => {
    if (composing) noteRef.current?.focus();
  }, [composing]);
  const required = isRequired(item);
  const calls = useMemo(() => callsMade(item.summary_md), [item.summary_md]);
  const readOnly = item.state === "approved" || item.state === "archived";
  const canUndo = undo !== null && undo.id === item.id && undo.until > now;

  const targets: Target[] = useMemo(
    () =>
      mode === "call"
        ? [
            ...calls.map((c) => ({ key: c, label: c.length > 60 ? `${c.slice(0, 58)}…` : c, path: null, title: c })),
            { key: "job", label: "Something else", path: null, title: "Something else" },
          ]
        : [
      { key: "job", label: "Whole job", path: null, title: item.title },
      ...item.deliverables.map((d) => {
        const title = titles.get(d.path) ?? d.name;
        return { key: d.path, label: title, path: d.path, title };
      }),
    ],
    [item, titles, mode, calls],
  );
  const target = targets.find((t) => t.key === targetKey) ?? targets[0];

  /** The deliverable under the reader's top edge becomes the default target. */
  const openComposer = (m: "revise" | "call" = "revise") => {
    setMode(m);
    const box = bodyRef.current;
    let pick = "job";
    if (m === "call") pick = calls[0] ?? "job";
    else if (box) {
      const line = box.getBoundingClientRect().top + 120;
      for (const el of Array.from(box.querySelectorAll<HTMLElement>("[data-path]"))) {
        const r = el.getBoundingClientRect();
        if (r.top <= line && r.bottom >= line) {
          pick = el.dataset.path ?? "job";
          break;
        }
      }
    }
    setTargetKey(pick);
    setComposing(true);
  };

  const liveDirector = (fleet?.nodes ?? []).find((n) => n.squad === item.squad && n.parent === null && n.status !== "gone");
  const routeText = liveDirector
    ? `Goes to ${liveDirector.roleTitle ?? "the director"} (live)`
    : `Starts a revision job for ${squadLabel(item)} (director has finished)`;

  const addPhrase = (phrase: string) => {
    setNote((n) => (n.trim() === "" ? phrase : `${n.replace(/\s+$/, "")}\n${phrase}`));
    noteRef.current?.focus();
  };

  const decide = (state: "approved" | "archived") => {
    setBusy(true);
    const prev = { state: item.state, note: item.note, decided_at: item.decided_at };
    call<InboxItem>("inbox_decide", { id: item.id, state, note: null })
      .then(() => {
        setUndo({ id: item.id, prev, until: Date.now() + UNDO_MS });
        setToast({ ok: true, text: state === "approved" ? "Approved." : required ? "Archived." : "Got it." });
        onChanged();
      })
      .catch((e) => setToast({ ok: false, text: `I couldn't save that: ${reasonOf(e)}` }))
      .finally(() => setBusy(false));
  };
  const sendBack = () => {
    setBusy(true);
    call<{ how: string; job: string | null }>("inbox_send_back", { id: item.id, note, target: { path: target.path, title: target.title }, mode })
      .then((r) => {
        setToast({ ok: true, text: r.how === "asked" ? "Sent. The director has your note." : `Sent. A revision job is starting${r.job ? ` (${r.job})` : ""}.` });
        setComposing(false);
        setNote("");
      })
      .catch((e) => setToast({ ok: false, text: reasonOf(e) }))
      .finally(() => {
        setBusy(false);
        onChanged();
      });
  };
  const answer = (question: string, ans: "yes" | "no", qnote: string) => {
    setBusy(true);
    call<{ how: string }>("inbox_send_back", { id: item.id, note: qnote, target: { path: null, title: question }, mode: "answer", answer: ans })
      .then(() => setToast({ ok: true, text: `Answered ${ans}. The squad has it.` }))
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
          <span className={`ipill s-${item.state}${item.state === "new" && !required ? " rep" : ""}`}>{pillLabel(item)}</span>
        </p>
      </header>
      <div className="rbody" ref={bodyRef}>
        <NeedsBox item={item} busy={busy} onAnswer={answer} />
        {item.summary_md && (
          <section className="rsummary">
            <Markdown text={withoutSection(item.summary_md, "Needs you")} />
          </section>
        )}
        {item.deliverables.length > 0 && <p className="dsec">Deliverables</p>}
        {item.deliverables.map((d) => (
          <div className="dwrap" key={d.path} data-path={d.path}>
            <Deliverable item={item} f={d} covers={covers} />
          </div>
        ))}
        {item.deliverables.length === 0 && !item.summary_md && <p className="co-quiet">Nothing was attached to this one.</p>}
      </div>
      <footer className="ractions">
        {composing ? (
          <div className="sendbox">
            <p className="lbl">{mode === "call" ? "WHICH CALL SHOULD CHANGE?" : "WHAT SHOULD CHANGE?"}</p>
            <div className="targets" role="radiogroup" aria-label="What is this about?">
              {targets.map((t) => (
                <button key={t.key} type="button" role="radio" aria-checked={t.key === target.key} className={`toggle${t.key === target.key ? " on" : ""}`} onClick={() => setTargetKey(t.key)} title={t.path ?? undefined}>
                  {t.label}
                </button>
              ))}
            </div>
            <div className="quick">
              {mode === "revise" && QUICK_PHRASES.map(([label, phrase]) => (
                <button key={label} type="button" className="qchip" onClick={() => addPhrase(phrase)}>
                  {label}
                </button>
              ))}
            </div>
            <textarea
              id="sb-note"
              ref={noteRef}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              aria-label={mode === "call" ? "Which call should change?" : "What should change?"}
              placeholder={mode === "call" ? "Say what you would rather it did. Example: Keep the stale cards open until I have looked at them." : "The bush doof post reads too formal. Make it sound like a mate who goes, keep the checklist."}
            />
            <p className="routeline">{routeText}</p>
            <div className="co-actions">
              <button type="button" className="primary" disabled={busy || note.trim() === ""} onClick={sendBack}>
                {busy ? "Sending…" : mode === "call" ? "Send" : "Send back"}
              </button>
              <button type="button" className="ghost" disabled={busy} onClick={() => setComposing(false)}>
                Cancel
              </button>
            </div>
          </div>
        ) : readOnly ? (
          <div className="ro">
            <span>
              {pillLabel(item)}
              {item.decided_at ? ` ${ago(Date.parse(item.decided_at), now)}` : ""}
            </span>
            {canUndo && (
              <button type="button" className="link-btn" onClick={doUndo}>
                Undo
              </button>
            )}
          </div>
        ) : required ? (
          <div className="co-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => decide("approved")}>
              Approve
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => openComposer("revise")}>
              Send back
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => decide("archived")}>
              Archive
            </button>
          </div>
        ) : (
          <div className="co-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => decide("archived")}>
              Got it
            </button>
            <button type="button" className="ghost" disabled={busy} onClick={() => openComposer("call")}>
              Change a call
            </button>
          </div>
        )}
        <Thread item={item} items={items} onOpenItem={onOpenItem} onOpenJob={onOpenJob} />
      </footer>
    </div>
  );
}

export function InboxDrawer({
  items,
  initialId,
  onClose,
  reload,
  fleet,
  onOpenJob,
}: {
  items: InboxItem[];
  initialId: string | null;
  onClose: () => void;
  reload: () => void;
  fleet: Fleet | null;
  onOpenJob: (squad: string, job: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>("inbox");
  const [sel, setSel] = useState<string | null>(initialId);
  const [toast, setToast] = useState<Toast | null>(null);
  const [undo, setUndo] = useState<Undo | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const shown = useMemo(() => items.filter((i) => (filter === "archived" ? i.state === "archived" : i.state !== "archived")), [items, filter]);
  const current = items.find((i) => i.id === sel) ?? shown[0] ?? null;
  const newCount = items.filter(needsMark).length;
  const reportCount = items.filter((i) => groupOf(i) === "reports").length;

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

  // A toast belongs to the item it was about.
  useEffect(() => {
    setToast(null);
  }, [current?.id]);

  const changed = useCallback(() => reload(), [reload]);

  return createPortal(
    <>
      <div className="scrim" onClick={onClose} />
      <aside className="drawer inbox" aria-label="Inbox">
        <div className="ilist">
          <div className="ihead">
            <div>
              <p className="eyebrow">Inbox</p>
              <h2>{newCount > 0 ? `${newCount} need${newCount === 1 ? "s" : ""} you` : "Nothing needs you"}</h2>
              {reportCount > 0 && <p className="isub">{reportCount} {reportCount === 1 ? "report" : "reports"} to skim</p>}
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
            {(["needs", "reports", "decided"] as Group[]).map((g) => {
              const rows = shown.filter((i) => (filter === "archived" ? g === "decided" : groupOf(i) === g));
              if (rows.length === 0) return null;
              return (
                <li key={g} className="igroup">
                  {filter === "inbox" && <p className="lbl">{g === "needs" ? "NEEDS YOU" : g === "reports" ? "REPORTS" : "DECIDED"}</p>}
                  <ul>
                    {rows.map((i) => (
                      <li key={i.id}>
                        <button type="button" className={`iitem${current?.id === i.id ? " on" : ""}${g === "needs" ? " fresh" : ""}`} onClick={() => setSel(i.id)}>
                          <b>{i.title}</b>
                          <span>
                            <em className="hchip">{squadLabel(i)}</em>
                            <time>{ago(itemTime(i), now)}</time>
                            <span className={`ipill s-${i.state}${g === "reports" ? " rep" : ""}${g === "needs" && !isRequired(i) ? " ask" : ""}`}>{pillLabel(i)}</span>
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </li>
              );
            })}
          </ul>
        </div>
        <div className="ipane">
          <button type="button" className="icon-btn iclose" onClick={onClose} aria-label="Close inbox">
            <CloseIcon />
          </button>
          {current ? (
            <Reader
              key={current.id}
              item={current}
              items={items}
              fleet={fleet}
              now={now}
              onChanged={changed}
              setToast={setToast}
              undo={undo}
              setUndo={setUndo}
              onOpenItem={(id) => {
                setFilter("inbox");
                setSel(id);
              }}
              onOpenJob={(squad, job) => {
                onClose();
                onOpenJob(squad, job);
              }}
            />
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

/** A chip like the Today chip: "Inbox" and, when something needs Mark, an amber count pill inside it.
 *  Plain reports are a quiet muted note beside it, never amber. */
export function InboxButton({ count, reports, onClick }: { count: number; reports: number; onClick: () => void }) {
  return (
    <span className="inboxwrap">
      <button
        type="button"
        className={`inboxchip${count > 0 ? " has" : ""}`}
        onClick={onClick}
        aria-label={count > 0 ? `Inbox, ${count} need${count === 1 ? "s" : ""} you` : "Inbox"}
      >
        Inbox
        {count > 0 && <b>{count}</b>}
      </button>
      {reports > 0 && (
        <button type="button" className="inboxreports" onClick={onClick}>
          · {reports} {reports === 1 ? "report" : "reports"}
        </button>
      )}
    </span>
  );
}
