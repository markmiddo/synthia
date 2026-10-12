import { useEffect, useState } from "react";
import { lastSevenDays, stamp } from "./format";
import { MOCK } from "./tauri";
import { InboxButton } from "./Inbox";
import { resetsText } from "./today";
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
  lead,
  tip,
}: {
  /** Put the label before the number ("5h 7%"). */
  lead?: boolean;
  /** A hover tooltip with several lines. */
  tip?: string[];
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
    <div className="gauge" title={title} tabIndex={tip ? 0 : undefined}>
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
        {lead && <span className="lead">{label}</span>}
        <b>{shown ?? value}</b>
        {!lead && <span>{label}</span>}
      </div>
      {tip && tip.length > 0 && (
        <div className="tip" role="tooltip">
          {tip.map((l) => (
            <span key={l}>{l}</span>
          ))}
        </div>
      )}
    </div>
  );
}

/** Window controls for the undecorated main window. The close button asks to close; the
 *  backend turns that into hide-to-tray. */
function WindowControls() {
  const [maxed, setMaxed] = useState(false);
  const win = async () => {
    const { getCurrentWindow } = await import("@tauri-apps/api/window");
    return getCurrentWindow();
  };
  useEffect(() => {
    if (MOCK) return;
    let off: (() => void) | undefined;
    let alive = true;
    win()
      .then(async (w) => {
        setMaxed(await w.isMaximized());
        const un = await w.onResized(async () => alive && setMaxed(await w.isMaximized()));
        if (alive) off = un;
        else un();
      })
      .catch(() => {});
    return () => {
      alive = false;
      off?.();
    };
  }, []);
  const run = (f: (w: Awaited<ReturnType<typeof win>>) => Promise<unknown>) => () => {
    if (MOCK) return;
    win().then(f).catch(() => {});
  };
  return (
    <div className="winctl">
      <button type="button" aria-label="Minimise window" title="Minimise" onClick={run((w) => w.minimize())}>
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 6.5h8" /></svg>
      </button>
      <button type="button" aria-label={maxed ? "Restore window" : "Maximise window"} title={maxed ? "Restore" : "Maximise"} onClick={run((w) => w.toggleMaximize())}>
        {maxed ? (
          <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4 4V2.5h5.5V8H8M2.5 4H8v5.5H2.5z" /></svg>
        ) : (
          <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 2.5h7v7h-7z" /></svg>
        )}
      </button>
      <button type="button" className="close" aria-label="Close window" title="Close" onClick={run((w) => w.close())}>
        <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7" /></svg>
      </button>
    </div>
  );
}

function DayMenu({ day, today, onDay }: { day: string; today: string; onDay: (d: string) => void }) {
  const [open, setOpen] = useState(false);
  const days = lastSevenDays(new Date());
  const current = days.find((d) => d.date === day)?.label ?? day;
  useEffect(() => {
    if (!open) return;
    const close = (e: Event) => {
      if (!(e.target as HTMLElement).closest(".daymenu")) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return (
    <div className="daymenu">
      <button type="button" className={`daychip${day !== today ? " past" : ""}`} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {current}
        <svg viewBox="0 0 10 10" aria-hidden="true"><path d="M2 3.5l3 3 3-3" /></svg>
      </button>
      {open && (
        <div className="daylist" role="menu">
          {days.map((d) => (
            <button
              key={d.date}
              type="button"
              role="menuitem"
              className={d.date === day ? "on" : ""}
              onClick={() => {
                setOpen(false);
                onDay(d.date);
              }}
            >
              {d.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export type View = "constellation" | "company";

function ViewToggle({ view, onView }: { view: View; onView: (v: View) => void }) {
  return (
    <div className="views" role="group" aria-label="View">
      {(["constellation", "company"] as const).map((v) => (
        <button key={v} type="button" aria-pressed={view === v} className={view === v ? "on" : ""} onClick={() => onView(v)}>
          {v === "constellation" ? "Constellation" : "Company"}
        </button>
      ))}
    </div>
  );
}

export function TopBar({
  nodes,
  usage,
  now,
  preview,
  view,
  onView,
  day,
  today,
  onDay,
  inboxNew,
  inboxReports,
  onInbox,
}: {
  nodes: FleetNode[];
  usage: UsageStats | null;
  now: number;
  preview: boolean;
  view: View;
  onView: (v: View) => void;
  day: string;
  today: string;
  onDay: (d: string) => void;
  inboxNew: number;
  inboxReports: number;
  onInbox: () => void;
}) {
  const count = (s: FleetNode["status"]) => nodes.filter((n) => n.status === s).length;
  const total = nodes.length;
  const usageOk = usage !== null && !usage.error;
  return (
    <header
      className="top"
      data-tauri-drag-region
      onDoubleClick={(e) => {
        if (MOCK || (e.target as HTMLElement).closest("button")) return;
        import("@tauri-apps/api/window").then(({ getCurrentWindow }) => getCurrentWindow().toggleMaximize()).catch(() => {});
      }}
    >
      <div className="mark" data-tauri-drag-region>
        <i data-tauri-drag-region />
        <Wordmark size={26} />
      </div>
      <span className="clock" data-tauri-drag-region>{stamp(now)}</span>
      {preview && <span className="example">PREVIEW DATA</span>}
      <ViewToggle view={view} onView={onView} />
      <DayMenu day={day} today={today} onDay={onDay} />
      <InboxButton count={inboxNew} reports={inboxReports} onClick={onInbox} />
      <div className="gauges" data-tauri-drag-region>
        <Gauge value={count("working")} total={total} label="working" color="var(--blue)" />
        <Gauge value={count("needs-you")} total={total} label="need you" color="var(--amber)" />
        {usageOk ? (
          <>
            <Gauge
              lead
              value={usage.five_hour_pct}
              total={100}
              shown={`${Math.round(usage.five_hour_pct)}%`}
              label="5h"
              color="var(--cyan)"
              tip={[`5-hour limit ${Math.round(usage.five_hour_pct)}%`, resetsText(usage.five_hour_resets_at, usage.five_hour_resets_in, Date.now())].filter(Boolean)}
            />
            <Gauge
              lead
              value={usage.seven_day_pct}
              total={100}
              shown={`${Math.round(usage.seven_day_pct)}%`}
              label="Week"
              color="var(--blue)"
              tip={[
                `Weekly limit ${Math.round(usage.seven_day_pct)}%`,
                resetsText(usage.seven_day_resets_at, usage.seven_day_resets_in, Date.now()),
                ...(usage.seven_day_opus_pct != null ? [`Opus ${Math.round(usage.seven_day_opus_pct)}% this week`] : []),
                ...(usage.seven_day_sonnet_pct != null ? [`Sonnet ${Math.round(usage.seven_day_sonnet_pct)}% this week`] : []),
              ].filter(Boolean)}
            />
          </>
        ) : (
          <Gauge value={0} total={100} shown={usage ? "!" : "…"} label={usage ? "Claude usage unavailable" : "Claude usage"} color="var(--cyan)" fault={usage !== null} title={usage?.error ?? undefined} />
        )}
      </div>
      <WindowControls />
    </header>
  );
}
