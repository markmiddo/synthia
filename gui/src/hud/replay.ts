import type { Status } from "./format";
import type { DayChart, Fleet } from "./types";

/** A past day's record as a fleet, so the constellation can draw it. Nothing in it is live. */
export function fleetFromDay(chart: DayChart): Fleet {
  const nodes = Object.entries(chart.nodes)
    .map(([key, n]) => ({
      paneId: n.paneId || key,
      agent: n.agent,
      status: (n.lastStatus === "working" || n.lastStatus === "needs-you" ? "idle" : n.lastStatus) as Status,
      title: n.title,
      repo: n.repo,
      cwd: "",
      session: n.session,
      sinceMs: n.lastSeen,
      subagents: Object.entries(n.subagents).map(([id, s]) => ({
        id,
        description: s.description,
        agentType: s.agentType,
        model: s.model,
        live: false,
      })),
      squad: null,
      job: null,
      role: null,
      roleTitle: null,
      parent: null,
    }))
    .sort((a, b) => a.sinceMs - b.sinceMs);
  return { nodes, herdrOk: true, error: null };
}
