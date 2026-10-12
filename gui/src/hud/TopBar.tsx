import { stamp } from "./format";
import type { FleetNode, UsageStats } from "./types";
import { Wordmark } from "./Wordmark";

const C = 113; // circumference of the r=18 ring

function Gauge({
  value,
  total,
  label,
  color,
  shown,
  title,
  fault,
}: {
  value: number;
  total: number;
  label: string;
  color: string;
  shown?: string;
  title?: string;
  fault?: boolean;
}) {
  const frac = total > 0 ? Math.min(1, value / total) : 0;
  return (
    <div className="gauge" title={title}>
      <svg viewBox="0 0 44 44" aria-hidden="true">
        <circle cx="22" cy="22" r="18" fill="none" stroke={fault ? "var(--red)" : "var(--line)"} strokeWidth="4" opacity={fault ? 0.5 : 1} />
        {frac > 0 && (
          <circle
            cx="22"
            cy="22"
            r="18"
            fill="none"
            stroke={color}
            strokeWidth="4"
            strokeLinecap="round"
            strokeDasharray={C}
            strokeDashoffset={C * (1 - frac)}
            transform="rotate(-90 22 22)"
          />
        )}
      </svg>
      <div>
        <b>{shown ?? value}</b>
        <span>{label}</span>
      </div>
    </div>
  );
}

export function TopBar({
  nodes,
  usage,
  now,
  preview,
}: {
  nodes: FleetNode[];
  usage: UsageStats | null;
  now: number;
  preview: boolean;
}) {
  const count = (s: FleetNode["status"]) => nodes.filter((n) => n.status === s).length;
  const total = nodes.length;
  const usageOk = usage !== null && !usage.error;
  return (
    <header className="top">
      <div className="mark">
        <i />
        <Wordmark />
      </div>
      <span className="clock">{stamp(now)}</span>
      {preview && <span className="example">PREVIEW DATA</span>}
      <div className="gauges">
        <Gauge value={count("working")} total={total} label="working" color="var(--blue)" />
        <Gauge value={count("needs-you")} total={total} label="need you" color="var(--amber)" />
        {usageOk ? (
          <Gauge
            value={usage.five_hour_pct}
            total={100}
            shown={`${Math.round(usage.five_hour_pct)}%`}
            label="Claude usage"
            color="var(--cyan)"
            title={usage.five_hour_resets_in ? `Resets in ${usage.five_hour_resets_in}` : undefined}
          />
        ) : (
          <Gauge value={0} total={100} shown={usage ? "!" : "…"} label={usage ? "Claude usage unavailable" : "Claude usage"} color="var(--cyan)" fault={usage !== null} title={usage?.error ?? undefined} />
        )}
      </div>
    </header>
  );
}
