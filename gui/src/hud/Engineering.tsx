import { useState, type ComponentType, type ReactNode } from "react";
import { byAttention, statusColor, statusLabel } from "./format";
import { modelName, type Fleet, type FleetNode, type SubAgent } from "./types";

export interface RepoGroup {
  repo: string;
  nodes: FleetNode[];
}

/** Developers are every agent that is not a squad member. eventflo repos get their own group; the rest share "Other". */
export function groupByRepo(nodes: FleetNode[]): RepoGroup[] {
  const dev = byAttention(nodes.filter((n) => !n.squad));
  const groups = new Map<string, FleetNode[]>();
  for (const n of dev) {
    const key = n.cwd.includes("/dev/eventflo/") ? n.repo : "Other";
    groups.set(key, [...(groups.get(key) ?? []), n]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => (a === "Other" ? 1 : b === "Other" ? -1 : a.localeCompare(b)))
    .map(([repo, ns]) => ({ repo, nodes: ns }));
}

export function kindName(agent: string): string {
  const a = agent.toLowerCase();
  return a === "claude" ? "Claude" : a === "codex" ? "Codex" : a === "kimi" ? "Kimi" : agent || "Agent";
}

function SubRow({ s }: { s: SubAgent }) {
  return (
    <li className={s.live ? "live" : "done"}>
      <b>{s.agentType || "agent"}</b>
      <span title={s.description}>{s.description}</span>
      {s.model && <em className="chip">{modelName(s.model)}</em>}
      <i>{s.live ? "live" : "done"}</i>
    </li>
  );
}

function Developer({ n, now, onFocus }: { n: FleetNode; now: number; onFocus: (id: string) => void }) {
  const [showDone, setShowDone] = useState(false);
  const live = n.subagents.filter((s) => s.live);
  const done = n.subagents.filter((s) => !s.live);
  const gone = n.status === "gone";
  return (
    <div className="dev" style={{ ["--c" as string]: statusColor(n.status) }}>
      <button type="button" className="devcard" disabled={gone} onClick={() => onFocus(n.paneId)} aria-label={`Go to ${n.title}`}>
        <span className="role-dot" />
        <b title={n.title}>{n.title}</b>
        <span className="role-meta">
          <span className="chip">{n.repo}</span>
          <em>{statusLabel(n.status, n.sinceMs, now)}</em>
        </span>
        <span className="kind">{kindName(n.agent)}</span>
      </button>
      {n.subagents.length > 0 && (
        <ul className="subtree">
          {live.map((s) => (
            <SubRow key={s.id} s={s} />
          ))}
          {done.length > 0 && !showDone && (
            <li className="more">
              <button type="button" className="link-btn" onClick={() => setShowDone(true)}>
                +{done.length} done
              </button>
            </li>
          )}
          {showDone && done.map((s) => <SubRow key={s.id} s={s} />)}
          {showDone && (
            <li className="more">
              <button type="button" className="link-btn" onClick={() => setShowDone(false)}>
                Hide done
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

export function Engineering({
  fleet,
  now,
  onFocus,
  Dept,
}: {
  fleet: Fleet | null;
  now: number;
  onFocus: (paneId: string) => void;
  Dept: ComponentType<{ name: string; counts: string; children: ReactNode }>;
}) {
  const groups = groupByRepo(fleet?.nodes ?? []);
  const all = groups.flatMap((g) => g.nodes);
  const working = all.filter((n) => n.status === "working").length;
  const subs = all.reduce((t, n) => t + n.subagents.filter((s) => s.live).length, 0);
  const counts =
    all.length === 0 ? "none running" : `${working} working · ${subs} sub-agent${subs === 1 ? "" : "s"}`;
  return (
    <Dept name="Engineering" counts={counts}>
      {fleet === null ? (
        <p className="co-quiet">Looking for your developers…</p>
      ) : all.length === 0 ? (
        <p className="co-quiet">No developers running.</p>
      ) : (
        groups.map((g) => (
          <div key={g.repo} className="repo-group">
            <h3 className="lbl">{g.repo.toUpperCase()}</h3>
            <div className="devs">
              {g.nodes.map((n) => (
                <Developer key={n.paneId} n={n} now={now} onFocus={onFocus} />
              ))}
            </div>
          </div>
        ))
      )}
    </Dept>
  );
}
