import { byAttention, clock, statusColor, statusLabel, type Status } from "./format";
import type { DayChart, FleetNode, SubAgent } from "./types";

interface CardProps {
  title: string;
  meta: string;
  status: Status;
  label: string;
  kids: { key: string; text: string; live: boolean }[];
  onClick?: () => void;
}

function Card({ title, meta, status, label, kids, onClick }: CardProps) {
  const color = statusColor(status);
  const body = (
    <>
      <span className="dot" style={{ background: color }} aria-hidden="true" />
      <div>
        <b>{title}</b>
        <br />
        <span>{meta}</span>
      </div>
      <span className="st">{label}</span>
    </>
  );
  return (
    <li>
      {onClick ? (
        <button type="button" className="node mine" style={{ ["--c" as string]: color }} onClick={onClick}>
          {body}
        </button>
      ) : (
        <div className="node" style={{ ["--c" as string]: color }}>
          {body}
        </div>
      )}
      {kids.length > 0 && (
        <ul className="kids">
          {kids.map((k) => (
            <li key={k.key}>
              <span
                className="dot"
                style={{ background: k.live ? "var(--work)" : "var(--done)" }}
                aria-hidden="true"
              />
              {k.text}
              <span>{k.live ? "working" : "done"}</span>
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function kidsOf(subs: SubAgent[]) {
  return subs.map((s) => ({ key: s.id, text: s.description || s.agentType, live: s.live }));
}

function Root() {
  return (
    <div className="root">
      <i aria-hidden="true" />
      SYNTHIA
    </div>
  );
}

export function OrgTree({
  nodes,
  now,
  onFocus,
}: {
  nodes: FleetNode[];
  now: number;
  onFocus: (paneId: string) => void;
}) {
  if (nodes.length === 0) {
    return (
      <div>
        <Root />
        <p className="empty">No agents running. Start one in herdr or ask me.</p>
      </div>
    );
  }
  return (
    <div>
      <Root />
      <ul className="tree">
        {byAttention(nodes).map((n) => (
          <Card
            key={n.paneId}
            title={n.title}
            meta={`${n.repo} · your pane`}
            status={n.status}
            label={statusLabel(n.status, n.sinceMs, now)}
            kids={kidsOf(n.subagents)}
            onClick={n.status === "gone" ? undefined : () => onFocus(n.paneId)}
          />
        ))}
      </ul>
    </div>
  );
}

/** A past day, rebuilt from the saved record. Read-only: those panes are long gone. */
export function PastTree({ chart }: { chart: DayChart | null }) {
  const nodes = chart ? Object.entries(chart.nodes) : [];
  if (nodes.length === 0) {
    return (
      <div>
        <Root />
        <p className="empty">Nothing was recorded on this day.</p>
      </div>
    );
  }
  nodes.sort((a, b) => a[1].firstSeen - b[1].firstSeen);
  return (
    <div>
      <Root />
      <ul className="tree">
        {nodes.map(([key, n]) => (
          <Card
            key={key}
            title={n.title}
            meta={`${n.repo} · ${clock(n.firstSeen)} to ${clock(n.lastSeen)}`}
            status={n.lastStatus}
            label={n.lastStatus === "needs-you" ? "Was waiting" : n.lastStatus === "working" ? "Was working" : n.lastStatus === "gone" ? "Closed" : "Done"}
            kids={Object.entries(n.subagents).map(([id, s]) => ({
              key: id,
              text: s.description || s.agentType,
              live: false,
            }))}
          />
        ))}
      </ul>
    </div>
  );
}
