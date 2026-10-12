import { useEffect, useRef, useState } from "react";
import { applyDrafts, diffFleet, type ActivityItem } from "./activityLogic";
import type { Fleet } from "./types";

export type { ActivityItem, Tone } from "./activityLogic";

/** The meaningful recent changes in the fleet, newest first. Memory only: it starts empty each launch. */
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
    setItems((cur) => applyDrafts(cur, drafts, () => ++seq.current));
  }, [fleet]);

  return items;
}
