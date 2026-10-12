import { useCallback, useEffect, useState } from "react";
import { formatSince, statusColor } from "./format";
import { Markdown } from "./markdown";
import { CloseButton } from "./RolePanel";
import { call, reasonOf } from "./tauri";
import type { Fleet, FleetNode, JobDetail, SquadInfo } from "./types";

const REFRESH_MS = 3000;

function clock(at: string): string {
  const t = Date.parse(at);
  return Number.isNaN(t) ? at.slice(0, 16) : new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** What a member is doing, in the words used on the chart. */
export function memberStatus(s: FleetNode["status"]): string {
  switch (s) {
    case "working":
      return "Working";
    case "needs-you":
    case "idle":
      return "Waiting";
    case "done":
      return "Done";
    case "gone":
      return "Gone";
  }
}

export function JobPanel({
  squad,
  jobId,
  fleet,
  now,
  onClose,
  onFocus,
}: {
  squad: SquadInfo;
  jobId: string;
  fleet: Fleet | null;
  now: number;
  onClose: () => void;
  onFocus: (paneId: string) => void;
}) {
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(() => {
    call<JobDetail>("squad_job_detail", { squad: squad.id, job: jobId })
      .then((d) => {
        setDetail(d);
        setError(null);
      })
      .catch((e) => setError(reasonOf(e)));
  }, [squad.id, jobId]);
  useEffect(() => {
    load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [load]);

  const members = (fleet?.nodes ?? [])
    .filter((n) => n.squad === squad.id && n.job === jobId)
    .sort((a, b) => Number(a.parent !== null) - Number(b.parent !== null));
  const live = detail !== null && !["done", "stopped"].includes(detail.state);

  const stop = () => {
    setBusy(true);
    setNote(null);
    call("squad_stop_job", { job: jobId })
      .then(() => {
        setNote({ ok: true, text: "Stopped." });
        setConfirming(false);
        load();
      })
      .catch((e) => setNote({ ok: false, text: `I couldn't stop it: ${reasonOf(e)}` }))
      .finally(() => setBusy(false));
  };

  return (
    <aside className="co-panel wide" aria-label={`Job ${jobId}`}>
      <div className="co-panel-head">
        <div>
          <p className="lbl">{squad.name.toUpperCase()} SQUAD · JOB</p>
          <h2 className="job-title">{jobId}</h2>
        </div>
        <CloseButton onClick={onClose} label="Close job" />
      </div>
      {error && <p className="co-error" role="status">I can't read that job: {error}</p>}
      {detail && (
        <>
          <p className="job-line">
            <span className={`job-state s-${detail.state}`}>{detail.state}</span>
            <button type="button" className="link-btn" onClick={() => call("squad_open_job", { path: detail.path }).catch((e) => setNote({ ok: false, text: `I couldn't open that folder: ${reasonOf(e)}` }))}>
              Open folder
            </button>
          </p>

          <section className="field">
            <span className="lbl">BRIEF</span>
            <div className="prompt-read short">
              <Markdown text={detail.brief} />
            </div>
          </section>

          <section className="field">
            <span className="lbl">TEAM</span>
            {members.length === 0 ? (
              <p className="co-quiet">Nobody from this job is running right now.</p>
            ) : (
              <ul className="members">
                {members.map((m) => (
                  <li key={m.paneId} style={{ ["--c" as string]: statusColor(m.status) }}>
                    <i className="mdot" />
                    <div>
                      <b>{m.roleTitle ?? m.role ?? m.title}</b>
                      <span>
                        <em>{memberStatus(m.status)}</em> · {formatSince(m.sinceMs, now)}
                      </span>
                      {m.title && m.title !== m.roleTitle && <span className="last-line" title={m.title}>{m.title}</span>}
                    </div>
                    <button type="button" className="ghost" disabled={m.status === "gone"} onClick={() => onFocus(m.paneId)}>
                      Watch
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="field">
            <span className="lbl">ACTIVITY</span>
            {detail.log.length === 0 ? (
              <p className="co-quiet">Nothing logged yet.</p>
            ) : (
              <ol className="log">
                {detail.log.map((l, i) => (
                  <li key={`${l.at}-${i}`}>
                    <time>{clock(l.at)}</time>
                    <div>
                      <b>{l.who}</b>
                      <span>{l.text}</span>
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className="field">
            <span className="lbl">DELIVERABLES</span>
            {detail.deliverables.length === 0 ? (
              <p className="co-quiet">Nothing delivered yet.</p>
            ) : (
              <ul className="files">
                {detail.deliverables.map((f) => {
                  const open = () =>
                    call("squad_open_file", { squad: squad.id, job: jobId, name: f.name }).catch((e) =>
                      setNote({ ok: false, text: `I couldn't open ${f.name}: ${reasonOf(e)}` }),
                    );
                  return (
                    <li key={f.name}>
                      {f.thumb ? <img src={f.thumb} alt="" /> : <i className="ficon">{f.kind === "md" ? "MD" : f.kind === "json" ? "{}" : "·"}</i>}
                      <span title={f.name}>{f.name}</span>
                      <em>{sizeLabel(f.size)}</em>
                      {f.kind !== "other" && (
                        <button type="button" className="link-btn" onClick={open}>
                          Open
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </section>

          {live && (
            <div className="stopper">
              {confirming ? (
                <>
                  <span>Stop this job and close its panes?</span>
                  <button type="button" className="danger" disabled={busy} onClick={stop}>
                    {busy ? "Stopping…" : "Yes, stop it"}
                  </button>
                  <button type="button" className="ghost" disabled={busy} onClick={() => setConfirming(false)}>
                    Keep going
                  </button>
                </>
              ) : (
                <button type="button" className="ghost warn" onClick={() => setConfirming(true)}>
                  Stop job
                </button>
              )}
            </div>
          )}
        </>
      )}
      {note && <p className={note.ok ? "co-ok" : "co-error"} role="status">{note.text}</p>}
    </aside>
  );
}
