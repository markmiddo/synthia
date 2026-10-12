import { useEffect, useRef, useState } from "react";
import type { Fleet, FleetNode } from "./types";

export type Tone = "work" | "need" | "done";

export interface ActivityItem {
  id: number;
  at: number;
  tone: Tone;
  /** The agent or sub-agent the line is about (shown bold). */
  subject: string;
  /** The rest of the sentence. */
  what: string;
}

export const FEED_LIMIT = 30;

type Draft = Omit<ActivityItem, "id">;

function statusEvent(n: FleetNode, prev: FleetNode["status"] | null, at: number): Draft | null {
  switch (n.status) {
    case "working":
      return { at, tone: "work", subject: n.title, what: prev === null ? "started" : "is working again" };
    case "needs-you":
      return { at, tone: "need", subject: n.title, what: "needs you" };
    case "idle":
      return { at, tone: "done", subject: n.title, what: "went idle" };
    case "done":
      return { at, tone: "done", subject: n.title, what: "finished" };
    case "gone":
      return { at, tone: "done", subject: n.title, what: "was closed" };
  }
}

/** Pure: what changed between two fleet snapshots, oldest first. */
export function diffFleet(prev: Fleet, next: Fleet, at: number): Draft[] {
  const out: Draft[] = [];
  const before = new Map(prev.nodes.map((n) => [n.paneId, n]));
  for (const n of next.nodes) {
    const old = before.get(n.paneId);
    if (!old) {
      const e = statusEvent(n, null, at);
      if (e) out.push({ ...e, what: n.status === "working" ? "started" : "appeared" });
      continue;
    }
    if (old.status !== n.status) {
      const e = statusEvent(n, old.status, at);
      if (e) out.push(e);
    }
    const oldSubs = new Map(old.subagents.map((s) => [s.id, s]));
    for (const s of n.subagents) {
      const name = s.description || s.agentType;
      const was = oldSubs.get(s.id);
      if (!was && s.live) out.push({ at, tone: "work", subject: name, what: `started under ${n.title}` });
      else if (was && was.live && !s.live) out.push({ at, tone: "done", subject: name, what: "finished" });
    }
  }
  return out;
}

/** The last ~30 changes in the fleet, newest first. Memory only: it starts empty each launch. */
export function useActivity(fleet: Fleet | null): ActivityItem[] {
  const [items, setItems] = useState<ActivityItem[]>([]);
  const baseline = useRef<Fleet | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    // A herdr outage empties the fleet; coming back must not read as everything starting.
    if (!fleet || !fleet.herdrOk) return;
    const prev = baseline.current;
    baseline.current = fleet;
    if (!prev) return;
    const drafts = diffFleet(prev, fleet, Date.now());
    if (drafts.length === 0) return;
    const fresh = drafts.map((d) => ({ ...d, id: ++seq.current })).reverse();
    setItems((cur) => [...fresh, ...cur].slice(0, FEED_LIMIT));
  }, [fleet]);

  return items;
}
