import type { Fleet, FleetNode } from "./types";

export type Tone = "work" | "need" | "done";
export type Kind = "start" | "finish" | "need" | "close";

export interface ActivityItem {
  id: number;
  /** One line per key (an agent's pane): a new state replaces the old line. */
  key: string;
  kind: Kind;
  at: number;
  tone: Tone;
  /** The agent the line is about (shown bold). */
  subject: string;
  /** The rest of the sentence. */
  what: string;
  /** The line this one replaced, kept so a quick flip back can restore it. */
  prev: ActivityItem | null;
}

export type Draft = Omit<ActivityItem, "id" | "prev">;

export const FEED_LIMIT = 30;
/** A finish followed by new work sooner than this is a flap, not news. */
export const FLAP_MS = 20_000;

/** Squad members read by role ("Writer, Growth"); everyone else by their task title. */
export function subjectOf(n: FleetNode): string {
  if (n.squad && n.roleTitle) return `${n.roleTitle}, ${n.squad[0].toUpperCase()}${n.squad.slice(1)}`;
  return n.title;
}

function draft(n: FleetNode, kind: Kind, what: string, tone: Tone, at: number): Draft {
  return { key: n.paneId, kind, at, tone, subject: subjectOf(n), what };
}

function eventFor(n: FleetNode, prev: FleetNode["status"] | null, at: number): Draft | null {
  switch (n.status) {
    case "working":
      return draft(n, "start", "started", "work", at);
    case "needs-you":
      return draft(n, "need", "needs you", "need", at);
    case "done":
      return draft(n, "finish", "finished", "done", at);
    case "idle":
      // Idle only matters as the end of work; a pane that is merely sitting there is not news.
      return prev === "working" ? draft(n, "finish", "finished", "done", at) : null;
    case "gone":
      return draft(n, "close", "was closed", "done", at);
  }
}

/** Pure: the meaningful changes between two fleet snapshots, oldest first. */
export function diffFleet(prev: Fleet, next: Fleet, at: number): Draft[] {
  const out: Draft[] = [];
  const before = new Map(prev.nodes.map((n) => [n.paneId, n]));
  for (const n of next.nodes) {
    const old = before.get(n.paneId);
    if (old && old.status === n.status) continue;
    const e = eventFor(n, old?.status ?? null, at);
    if (e) out.push(e);
  }
  return out;
}

/** Pure: fold new events into the feed (newest first). One line per agent, updated in place, and a
 *  work/finish flip shorter than FLAP_MS disappears instead of adding lines. */
export function applyDrafts(items: ActivityItem[], drafts: Draft[], nextId: () => number): ActivityItem[] {
  let list = items;
  for (const d of drafts) {
    const existing = list.find((i) => i.key === d.key) ?? null;
    const rest = list.filter((i) => i.key !== d.key);
    if (d.kind === "start" && existing && existing.kind === "finish" && d.at - existing.at < FLAP_MS) {
      list = existing.prev ? [existing.prev, ...rest] : rest;
      continue;
    }
    if (existing && existing.kind === d.kind && existing.what === d.what) {
      list = [{ ...existing, at: d.at }, ...rest];
      continue;
    }
    const prev = existing && existing.kind === "start" ? existing : null;
    list = [{ ...d, id: nextId(), prev }, ...rest];
  }
  return list.slice(0, FEED_LIMIT);
}
