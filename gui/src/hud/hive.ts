import { useEffect, useRef, useState } from "react";
import { call } from "./tauri";

export interface KindCount {
  kind: string;
  count: number;
}

export interface LastRecall {
  title: string;
  atMs: number;
  kind: "read" | "write";
}

export interface BrainOverview {
  total: number;
  kinds: KindCount[];
  recalledToday: number;
  writtenToday: number;
  vaultNotes: number;
  skills: number;
  roles: number;
  claudeMd: number;
  squads: number;
  connectors: number;
  lastByTeam: Record<string, LastRecall>;
}

export interface MemoryRow {
  path: string;
  name: string;
  description: string;
  kind: string;
  modifiedMs: number;
  recalls7d: number;
  recalledToday: number;
  teams7d: string[];
}

export interface MemoryBody {
  name: string;
  kind: string;
  description: string;
  body: string;
}

export interface RecallEntry {
  atMs: number;
  kind: "read" | "write";
  title: string;
  file: string;
  team: { key: string; label: string };
  who: string;
}

export interface SkillInfo {
  name: string;
  description: string;
}

export interface SkillsInfo {
  skills: SkillInfo[];
  roles: string[];
  claudeMd: number;
  squads: number;
}

export interface Connected {
  local: string[];
  claudeAi: string[];
}

export interface BrainNow {
  sessionId: string | null;
  sessionDate: string | null;
  sessionModifiedMs: number | null;
  journal: { name: string; text: string } | null;
  ledgerDone: number;
  ledgerCalls: number;
  ledgerWaiting: number;
}

export const EMPTY_OVERVIEW: BrainOverview = {
  total: 0,
  kinds: [],
  recalledToday: 0,
  writtenToday: 0,
  vaultNotes: 0,
  skills: 0,
  roles: 0,
  claudeMd: 0,
  squads: 0,
  connectors: 0,
  lastByTeam: {},
};

export function useOverview(everyMs = 30_000): BrainOverview {
  const [o, setO] = useState<BrainOverview>(EMPTY_OVERVIEW);
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<BrainOverview>("brain_overview")
        .then((v) => alive && v && setO(v))
        .catch(() => {});
    load();
    const t = setInterval(load, everyMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [everyMs]);
  return o;
}

/** New recall events as they are logged: the first poll sets the baseline (nothing replays), later
 *  polls hand back only entries newer than the last one seen. */
export function useRecallEvents(onEvents: (events: RecallEntry[]) => void, everyMs = 4000): void {
  const since = useRef<number>(Date.now());
  const cb = useRef(onEvents);
  cb.current = onEvents;
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<RecallEntry[]>("brain_recalls", { since: since.current + 1 })
        .then((v) => {
          if (!alive || !v || v.length === 0) return;
          since.current = Math.max(since.current, ...v.map((e) => e.atMs));
          cb.current(v);
        })
        .catch(() => {});
    load();
    const t = setInterval(load, everyMs);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [everyMs]);
}

/** "just now", "3m ago", "2h ago", "yesterday", or a short date. */
export function ago(ms: number, now: number): string {
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  return new Date(ms).toLocaleDateString([], { day: "numeric", month: "short" });
}

export const KIND_COLORS: Record<string, string> = {
  reference: "var(--violet)",
  project: "var(--blue)",
  feedback: "var(--amber)",
  bug: "#ef7d7d",
  user: "var(--green)",
  other: "var(--muted)",
};

export const KIND_BLURB: Record<string, string> = {
  reference: "How things work: endpoints, configs, gotchas",
  project: "What is in flight and why",
  feedback: "Mark's rules and corrections",
  bug: "Known failure patterns",
  user: "Who Mark is and how he works",
  other: "Handovers, walk notes and the rest",
};
