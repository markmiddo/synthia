import { useEffect, useState } from "react";
import { isPlainShell } from "./format";
import { call } from "./tauri";
import type { DayChart, Fleet } from "./types";

export interface LedgerItem {
  id: string;
  title: string;
  detail: string;
  recommendation: string | null;
  undo: string | null;
  createdAt: number;
  links: string[];
}

export interface LedgerSummary {
  doneCount: number;
  callCount: number;
  waitingCount: number;
  done: LedgerItem[];
  calls: LedgerItem[];
  waiting: LedgerItem[];
}

export interface DueItem {
  id: string;
  kind: string;
  title: string;
  due: string;
  overdue: boolean;
}

export interface ShippedPr {
  number: number;
  title: string;
  repo: string;
  url: string;
}

export interface Shipped {
  ok: boolean;
  items: ShippedPr[];
}

export interface SquadOutput {
  deliverables: number;
  jobsFinished: number;
}

export interface StatusCount {
  status: string;
  count: number;
}

export interface ReleaseStatus {
  ok: boolean;
  title: string;
  url: string;
  total: number;
  counts: StatusCount[];
}

export interface NextMeeting {
  state: "ok" | "not_connected" | "unavailable";
  next: { title: string; startMs: number; link: string } | null;
  moreToday: number;
}

export interface SpendToday {
  ok: boolean;
  percent: number;
  points: number[];
  firstAt: number;
  distinct: number;
}

export interface BugStatus {
  ok: boolean;
  asOf: string;
  leftToFix: number;
  high: number;
  noFix: number;
  planned: number;
  fixInProgress: number;
  awaitingQa: number;
  awaitingRelease: number;
}

export interface Today {
  ledger: LedgerSummary | null;
  due: DueItem[] | null;
  shipped: Shipped | null;
  squad: SquadOutput | null;
  release: ReleaseStatus | null;
  meeting: NextMeeting | null;
  spend: SpendToday | null;
  bugs: BugStatus | null;
}

/** Poll one read-only command; a failure leaves the last good value (or null) in place. */
function usePolled<T>(cmd: string, everyMs: number): T | null {
  const [value, setValue] = useState<T | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<T>(cmd)
        .then((v) => alive && setValue(v))
        .catch(() => {});
    load();
    const t = setInterval(load, everyMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [cmd, everyMs]);
  return value;
}

export function useToday(): Today {
  return {
    ledger: usePolled<LedgerSummary>("today_ledger", 15_000),
    due: usePolled<DueItem[]>("today_inbox", 60_000),
    shipped: usePolled<Shipped>("today_shipped", 120_000),
    squad: usePolled<SquadOutput>("today_squad_output", 60_000),
    release: usePolled<ReleaseStatus>("today_release", 120_000),
    meeting: usePolled<NextMeeting>("today_meeting", 60_000),
    spend: usePolled<SpendToday>("today_spend", 60_000),
    bugs: usePolled<BugStatus>("today_bugs", 300_000),
  };
}

export interface AgentsToday {
  agents: number;
  subagents: number;
  titles: { title: string; subs: number }[];
}

/** Agents run today: the day record plus anything live that the record has not caught up with yet. */
export function agentsToday(chart: DayChart | null, fleet: Fleet | null): AgentsToday {
  const seen = new Map<string, { title: string; subs: number }>();
  for (const [key, n] of Object.entries(chart?.nodes ?? {})) {
    if (isPlainShell({ agent: n.agent, title: n.title, squad: null })) continue;
    seen.set(n.session ?? n.paneId ?? key, { title: n.title, subs: Object.keys(n.subagents).length });
  }
  for (const n of fleet?.nodes ?? []) {
    const key = n.session ?? n.paneId;
    const cur = seen.get(key);
    seen.set(key, { title: n.roleTitle ?? n.title, subs: Math.max(cur?.subs ?? 0, n.subagents.length) });
  }
  const titles = [...seen.values()];
  return { agents: titles.length, subagents: titles.reduce((t, x) => t + x.subs, 0), titles };
}

export function useTodayChart(fleet: Fleet | null, today: string): DayChart | null {
  const [chart, setChart] = useState<DayChart | null>(null);
  const key = fleet ? fleet.nodes.length : -1;
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<DayChart>("fleet_day", { date: today })
        .then((c) => alive && setChart(c))
        .catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [today, key]);
  return chart;
}

/** "in 23m", "in 1h 5m", "now". */
export function countdown(startMs: number, nowMs: number): string {
  const mins = Math.ceil((startMs - nowMs) / 60_000);
  if (mins <= 0) return "now";
  if (mins < 60) return `in ${mins}m`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return m === 0 ? `in ${h}h` : `in ${h}h ${m}m`;
}

/** "v3.2 release" from a title like "Version 3.2 Release". */
export function releaseLabel(title: string): string {
  const m = /(\d+(?:\.\d+)+)/.exec(title);
  return m ? `v${m[1]} release` : title;
}

/** "resets in 2h 46m" for soon, "resets Thu 9:00" for a later day. */
export function resetsText(iso: string | undefined, inText: string | undefined, nowMs: number): string {
  const t = iso ? Date.parse(iso) : NaN;
  if (Number.isNaN(t)) return inText ? `resets in ${inText}` : "";
  if (t - nowMs < 24 * 3_600_000) return inText ? `resets in ${inText}` : "resets soon";
  const d = new Date(t);
  const day = d.toLocaleDateString([], { weekday: "short" });
  const time = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: false });
  return `resets ${day} ${time}`;
}

/** What to print for today's spend: "<1%" under a point, "—" until two different readings exist. */
export function spendText(s: SpendToday): { value: string; note: string | null } {
  const first = new Date(s.firstAt);
  const late = first.getHours() * 60 + first.getMinutes() > 6 * 60;
  const since = first.toLocaleTimeString([], { hour: "numeric", minute: "2-digit", hour12: false });
  if (s.distinct < 2) return { value: "—", note: `tracking since ${since}` };
  const value = s.percent > 0 && s.percent < 1 ? "<1%" : `${s.percent < 10 ? s.percent.toFixed(1) : Math.round(s.percent)}%`;
  return { value, note: late ? `since ${since}` : null };
}

/** "as of Mon 12" when a snapshot is not from today. */
export function staleLabel(asOf: string, today: string): string | null {
  if (!asOf || asOf === today) return null;
  const d = new Date(`${asOf}T12:00:00`);
  if (Number.isNaN(d.getTime())) return `as of ${asOf}`;
  return `as of ${d.toLocaleDateString([], { weekday: "short", day: "numeric" })}`;
}
