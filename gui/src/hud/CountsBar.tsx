import type { FleetNode, UsageStats } from "./types";

export function CountsBar({ nodes, usage }: { nodes: FleetNode[]; usage: UsageStats | null }) {
  const count = (s: FleetNode["status"]) => nodes.filter((n) => n.status === s).length;
  const idle = count("idle");
  return (
    <div className="bar">
      <span>
        <b>{count("working")}</b>working
      </span>
      <span>
        <b>{count("needs-you")}</b>needs you
      </span>
      <span>
        <b>{count("done")}</b>done
      </span>
      {idle > 0 && (
        <span>
          <b>{idle}</b>idle
        </span>
      )}
      <span className="sp">
        {usage && !usage.error
          ? `Claude usage ${Math.round(usage.five_hour_pct)}%${usage.five_hour_resets_in ? ` · resets in ${usage.five_hour_resets_in}` : ""}`
          : "Claude usage unavailable"}
      </span>
    </div>
  );
}
