import { useState } from "react";
import { clock } from "./format";
import { NeedsYou } from "./Left";
import type { BrainView } from "./brain";
import { agentsToday, countdown, releaseLabel, type AgentsToday, type DueItem, type LedgerItem, type Today } from "./today";
import { call } from "./tauri";
import type { FleetNode } from "./types";

const MORE = 8;

type Open = "done" | "calls" | "shipped" | "agents" | null;

function Pop({ item, at, onClose }: { item: LedgerItem; at: { x: number; y: number }; onClose: () => void }) {
  return (
    <div className="pop" style={{ left: at.x, top: at.y }} role="dialog" aria-label={item.title}>
      <div className="pop-head">
        <b>{item.title}</b>
        <button type="button" className="icon-btn" onClick={onClose} aria-label="Close details">
          <svg viewBox="0 0 12 12" aria-hidden="true">
            <path d="M2.5 2.5l7 7M9.5 2.5l-7 7" />
          </svg>
        </button>
      </div>
      <time>{clock(item.createdAt)}</time>
      {item.detail && <p>{item.detail}</p>}
      {item.recommendation && (
        <p>
          <em>Recommended</em> {item.recommendation}
        </p>
      )}
      {item.undo && (
        <p>
          <em>To undo</em> {item.undo}
        </p>
      )}
    </div>
  );
}

function Tile({ n, label, sub, active, onClick }: { n: number | null; label: string; sub?: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={`tile${active ? " on" : ""}`} aria-expanded={active} onClick={onClick}>
      <b>{n === null ? "–" : n}</b>
      <span>{label}</span>
      {sub && <small>{sub}</small>}
    </button>
  );
}

function List({ children, total }: { children: React.ReactNode[]; total: number }) {
  const [all, setAll] = useState(false);
  const shown = all ? children : children.slice(0, MORE);
  return (
    <ul className="tlist">
      {shown.map((c, i) => (
        <li key={i}>{c}</li>
      ))}
      {!all && total > MORE && (
        <li className="more">
          <button type="button" className="link-btn" onClick={() => setAll(true)}>
            +{total - MORE} more
          </button>
        </li>
      )}
    </ul>
  );
}

function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const max = Math.max(...points, 0.1);
  const w = 90;
  const h = 22;
  const d = points.map((p, i) => `${(i / (points.length - 1)) * w},${h - (p / max) * (h - 3) - 1.5}`).join(" ");
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} width={w} height={h} aria-hidden="true">
      <polyline points={d} />
    </svg>
  );
}

const SEG_COLORS: Record<string, string> = {
  Done: "var(--green)",
  "Ready for Prod": "var(--cyan)",
  Testing: "var(--blue)",
  "In review": "var(--amber)",
  "In progress": "var(--blue)",
  Ready: "var(--soft)",
  Backlog: "var(--slate)",
};

function Due({ items }: { items: DueItem[] }) {
  return (
    <section aria-label="Due today">
      <p className="lbl">DUE TODAY</p>
      {items.length === 0 ? (
        <p className="quiet-note">Nothing due.</p>
      ) : (
        <ul className="due">
          {items.map((d) => (
            <li key={d.id}>
              <span>{d.title}</span>
              {d.overdue && <em>overdue</em>}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function Scorecard({
  today,
  nodes,
  chart,
  fleet,
  confirms,
  now,
  onFocus,
  onConfirm,
}: {
  today: Today;
  nodes: FleetNode[];
  chart: import("./types").DayChart | null;
  fleet: import("./types").Fleet | null;
  confirms: BrainView["confirms"];
  now: number;
  onFocus: (paneId: string) => void;
  onConfirm: (id: string, yes: boolean) => void;
}) {
  const [open, setOpen] = useState<Open>(null);
  const [pop, setPop] = useState<{ item: LedgerItem; x: number; y: number } | null>(null);
  const toggle = (k: Exclude<Open, null>) => setOpen((o) => (o === k ? null : k));
  const detail = (item: LedgerItem, el: HTMLElement) => {
    const r = el.getBoundingClientRect();
    setPop({ item, x: Math.min(r.right + 12, window.innerWidth - 340), y: Math.max(48, Math.min(r.top - 8, window.innerHeight - 280)) });
  };
  const ledger = today.ledger;
  const agents: AgentsToday = agentsToday(chart, fleet);
  const meeting = today.meeting;
  const soon = meeting?.next ? meeting.next.startMs - now < 10 * 60_000 : false;
  const release = today.release;

  return (
    <div className="scorecard">
      <NeedsYou nodes={nodes} confirms={confirms} now={now} onFocus={onFocus} onConfirm={onConfirm} ledger={ledger?.waiting ?? []} onDetail={detail} />

      <section aria-label="Next meeting">
        <p className="lbl">NEXT MEETING</p>
        {meeting === null ? (
          <p className="quiet-note">Checking your calendar…</p>
        ) : meeting.state === "not_connected" ? (
          <p className="quiet-note">Calendar not connected</p>
        ) : meeting.state === "unavailable" ? (
          <p className="quiet-note">Calendar unavailable</p>
        ) : meeting.next === null ? (
          <p className="quiet-note">No more meetings today.</p>
        ) : (
          <>
            <button type="button" className="meeting" onClick={() => meeting.next?.link && call("open_url", { url: meeting.next.link }).catch(() => {})}>
              <b title={meeting.next.title}>{meeting.next.title}</b>
              <span>
                {clock(meeting.next.startMs)} · <em className={soon ? "soon" : ""}>{countdown(meeting.next.startMs, now)}</em>
              </span>
            </button>
            {meeting.moreToday > 0 && <p className="quiet-note">then {meeting.moreToday} more today</p>}
          </>
        )}
      </section>

      <section aria-label="Today">
        <p className="lbl">TODAY</p>
        <div className="tiles">
          <Tile n={ledger ? ledger.doneCount : null} label="Done" active={open === "done"} onClick={() => toggle("done")} />
          <Tile n={ledger ? ledger.callCount : null} label="Calls made" active={open === "calls"} onClick={() => toggle("calls")} />
          <Tile n={today.shipped?.ok ? today.shipped.items.length : null} label="PRs shipped" active={open === "shipped"} onClick={() => toggle("shipped")} />
          <Tile n={agents.agents} label="Agents" sub={agents.subagents > 0 ? `${agents.subagents} sub-agents` : undefined} active={open === "agents"} onClick={() => toggle("agents")} />
        </div>
        {open === "done" && ledger && (
          <List total={ledger.doneCount}>
            {ledger.done.map((i) => (
              <button type="button" className="row-btn" onClick={(e) => detail(i, e.currentTarget)}>
                {i.title}
              </button>
            ))}
          </List>
        )}
        {open === "calls" && ledger && (
          <List total={ledger.callCount}>
            {ledger.calls.map((i) => (
              <button type="button" className="row-btn" onClick={(e) => detail(i, e.currentTarget)}>
                {i.title}
              </button>
            ))}
          </List>
        )}
        {open === "shipped" && today.shipped?.ok && (
          <List total={today.shipped.items.length}>
            {today.shipped.items.map((p) => (
              <button type="button" className="row-btn" onClick={() => call("open_url", { url: p.url }).catch(() => {})}>
                <small>{p.repo}</small> {p.title}
              </button>
            ))}
          </List>
        )}
        {open === "agents" && (
          <List total={agents.titles.length}>
            {agents.titles.map((a) => (
              <span className="row-plain">
                {a.title}
                {a.subs > 0 && <small> · {a.subs} sub</small>}
              </span>
            ))}
          </List>
        )}
        {today.squad && (today.squad.deliverables > 0 || today.squad.jobsFinished > 0) && (
          <p className="squad-line">
            Squads: {today.squad.deliverables} {today.squad.deliverables === 1 ? "file" : "files"} delivered · {today.squad.jobsFinished}{" "}
            {today.squad.jobsFinished === 1 ? "job" : "jobs"} finished
          </p>
        )}
      </section>

      {release?.ok && release.total > 0 && (
        <section aria-label="Release status">
          <p className="lbl">{releaseLabel(release.title).toUpperCase()}</p>
          <button type="button" className="release" onClick={() => call("open_url", { url: release.url }).catch(() => {})}>
            <span className="bar" aria-hidden="true">
              {release.counts.map((c) => (
                <i key={c.status} style={{ flex: c.count, background: SEG_COLORS[c.status] ?? "var(--slate)" }} />
              ))}
            </span>
            <span className="rcounts">
              {release.counts
                .slice()
                .reverse()
                .map((c) => (
                  <span key={c.status}>
                    {c.status} <b>{c.count}</b>
                  </span>
                ))}
            </span>
          </button>
        </section>
      )}

      {today.due !== null && <Due items={today.due} />}

      {today.spend?.ok && (
        <section aria-label="Claude spend today">
          <p className="lbl">SPEND TODAY</p>
          <div className="spend">
            <span>
              <b>{today.spend.percent < 0.05 ? "0" : today.spend.percent.toFixed(today.spend.percent < 10 ? 1 : 0)}%</b> of the week
            </span>
            <Spark points={today.spend.points} />
          </div>
        </section>
      )}

      {pop && <Pop item={pop.item} at={pop} onClose={() => setPop(null)} />}
    </div>
  );
}
