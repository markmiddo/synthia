/** Small pure helpers shared by the HUD components. */

export function formatSince(sinceMs: number, nowMs: number): string {
  const mins = Math.floor(Math.max(0, nowMs - sinceMs) / 60_000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  const rest = mins % 60;
  return rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
}

export type Status = "working" | "needs-you" | "done" | "idle" | "gone";

export function statusLabel(status: Status, sinceMs: number, nowMs: number): string {
  const d = formatSince(sinceMs, nowMs);
  switch (status) {
    case "working":
      return `Working · ${d}`;
    case "needs-you":
      return d === "now" ? "Needs you" : `Needs you · ${d}`;
    case "done":
      return `Done · ${d}`;
    case "idle":
      return `Idle · ${d}`;
    case "gone":
      return "Gone";
  }
}

/** Blue working, amber needs you, slate everything else (red is kept for faults). */
export function statusColor(status: Status): string {
  switch (status) {
    case "working":
      return "var(--blue)";
    case "needs-you":
      return "var(--amber)";
    default:
      return "var(--slate)";
  }
}

/** "Mon 12 Oct · 18:46" */
export function stamp(ms: number): string {
  const d = new Date(ms);
  const part = (o: Intl.DateTimeFormatOptions, t: string) =>
    new Intl.DateTimeFormat([], o).formatToParts(d).find((p) => p.type === t)?.value ?? "";
  const day = `${part({ weekday: "short" }, "weekday")} ${part({ day: "numeric" }, "day")} ${part({ month: "short" }, "month")}`;
  return `${day} · ${clock(ms)}`;
}

const RANK: Record<Status, number> = { "needs-you": 0, working: 1, idle: 2, done: 3, gone: 4 };

/** Needs-you first, then working, then the rest; herdr's own order within a group. */
export function byAttention<T extends { status: Status }>(nodes: T[]): T[] {
  return nodes
    .map((n, i) => ({ n, i }))
    .sort((a, b) => RANK[a.n.status] - RANK[b.n.status] || a.i - b.i)
    .map((x) => x.n);
}

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
}

/** YYYY-MM-DD in local time, for the day picker. */
export function localDate(d: Date): string {
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

export function lastSevenDays(now: Date): { date: string; label: string }[] {
  const out: { date: string; label: string }[] = [];
  for (let i = 0; i < 7; i++) {
    const d = new Date(now.getFullYear(), now.getMonth(), now.getDate() - i);
    out.push({
      date: localDate(d),
      label: i === 0 ? "Today" : d.toLocaleDateString([], { weekday: "short", day: "numeric" }),
    });
  }
  return out;
}
