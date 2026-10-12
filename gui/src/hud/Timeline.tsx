import { clock, statusColor } from "./format";
import type { DayChart } from "./types";

export type DayState =
  | { status: "loading" }
  | { status: "error"; reason: string }
  | { status: "ready"; chart: DayChart };

const HOUR = 3_600_000;

/** Lane range: whole hours around the day's activity (and "now" for today), at least six hours. */
export function range(chart: DayChart, now: number | null): { start: number; end: number; ticks: number[] } {
  const spans = Object.values(chart.nodes);
  const lo = Math.min(...spans.map((n) => n.firstSeen), now ?? Infinity);
  const hi = Math.max(...spans.map((n) => n.lastSeen), now ?? 0);
  const start = Math.floor(lo / HOUR) * HOUR;
  let end = Math.ceil(hi / HOUR) * HOUR;
  if (end - start < 6 * HOUR) end = start + 6 * HOUR;
  const hours = (end - start) / HOUR;
  const step = hours <= 6 ? 1 : hours <= 12 ? 2 : hours <= 24 ? 4 : 6;
  end = start + Math.ceil(hours / step) * step * HOUR;
  const ticks: number[] = [];
  for (let t = start; t <= end; t += step * HOUR) ticks.push(t);
  return { start, end, ticks };
}

export function Timeline({ day, now, today }: { day: DayState; now: number; today: boolean }) {
  let body;
  if (day.status !== "ready") {
    body = (
      <p className="quiet-note">{day.status === "loading" ? "Loading…" : `Couldn't read that day: ${day.reason}`}</p>
    );
  } else if (Object.keys(day.chart.nodes).length === 0) {
    body = <p className="quiet-note">{today ? "Nothing recorded yet today." : "Nothing was recorded on this day."}</p>;
  } else {
    const { start, end, ticks } = range(day.chart, today ? now : null);
    const pct = (t: number) => `${Math.max(0, Math.min(100, ((t - start) / (end - start)) * 100))}%`;
    const span = (a: number, b: number) => ({ left: pct(a), width: `max(3px, calc(${pct(b)} - ${pct(a)}))` });
    const nodes = Object.entries(day.chart.nodes).sort((a, b) => a[1].firstSeen - b[1].firstSeen);
    body = (
      <div className="lanes">
        <div />
        <div className="axis">
          {ticks.map((t) => (
            <span key={t}>{new Date(t).getHours()}:00</span>
          ))}
        </div>
        {nodes.map(([key, n]) => {
          const live = today && n.lastStatus === "working";
          return (
            <LaneRow key={key} title={n.title}>
              <span
                className={`seg${live ? "" : " done"}`}
                style={{ ["--c" as string]: statusColor(n.lastStatus), ...span(n.firstSeen, live ? now : n.lastSeen) }}
                title={`${clock(n.firstSeen)} to ${clock(n.lastSeen)}`}
              />
              {Object.entries(n.subagents).map(([id, s]) => (
                <span key={id} className="seg sub" style={span(s.firstSeen, s.lastSeen)} title={s.description || s.agentType} />
              ))}
              {today && <span className="now" style={{ left: pct(now) }} />}
            </LaneRow>
          );
        })}
      </div>
    );
  }
  return <>{body}</>;
}

function LaneRow({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <>
      <div className="who" title={title}>
        {title}
      </div>
      <div className="lane">{children}</div>
    </>
  );
}
