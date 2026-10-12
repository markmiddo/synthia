import { useEffect, useRef, useState } from "react";
import { byAttention, statusColor, statusLabel } from "./format";
import type { Fleet, FleetNode } from "./types";

export const RING_LIMIT = 8;

export interface Placed {
  node: FleetNode;
  x: number;
  y: number;
  /** Where its link starts: the director for a squad specialist, otherwise the core. */
  from?: Placed;
}

/** Distance from a director to its specialists. */
const CLUSTER_R = 215;

/** Nodes sit on an ellipse around the core; past eight they use two. Squad specialists are not on
 *  the ring: they fan out around their director, away from the core. Pure, for the layout. */
export function place(nodes: FleetNode[], w: number, h: number): { cx: number; cy: number; placed: Placed[] } {
  const cx = w / 2;
  const cy = h * 0.46;
  const ids = new Set(nodes.map((n) => n.paneId));
  const isKid = (n: FleetNode) => n.parent !== null && n.parent !== n.paneId && ids.has(n.parent);
  const tops = nodes.filter((n) => !isKid(n));
  const kids = nodes.filter(isKid);
  const two = tops.length > RING_LIMIT;
  const rx = two ? Math.min(w * 0.4, 440) : Math.min(w * 0.36, 380);
  const ry = two ? Math.min(h * 0.4, 360) : Math.min(h * 0.34, 230);
  const outer = two ? Math.ceil(tops.length / 2) : tops.length;
  const placed: Placed[] = tops.map((node, i) => {
    const onInner = two && i >= outer;
    const count = onInner ? tops.length - outer : outer;
    const k = onInner ? i - outer : i;
    const scale = onInner ? 0.55 : 1;
    const ang = -Math.PI / 2 + (k + (onInner ? 1 : 0.5)) * ((2 * Math.PI) / count) + 0.35;
    return { node, x: cx + rx * scale * Math.cos(ang), y: cy + ry * scale * Math.sin(ang) };
  });
  const byId = new Map(placed.map((p) => [p.node.paneId, p]));
  const family = new Map<string, FleetNode[]>();
  for (const k of kids) family.set(k.parent as string, [...(family.get(k.parent as string) ?? []), k]);
  // A kid whose parent is itself a kid (a malformed registry) hangs off the ring node it was placed under.
  for (const [parentId, group] of family) {
    let parent = byId.get(parentId);
    if (!parent) {
      const up = kids.find((k) => k.paneId === parentId);
      parent = up && byId.get(up.parent as string);
    }
    if (!parent) {
      group.forEach((node) => placed.push({ node, x: cx, y: cy }));
      continue;
    }
    const out = Math.atan2(parent.y - cy, parent.x - cx);
    const span = Math.min(2.7, 0.8 * (group.length - 1));
    group.forEach((node, i) => {
      const ang = group.length === 1 ? out : out - span / 2 + (span * i) / (group.length - 1);
      const p: Placed = { node, x: parent.x + CLUSTER_R * Math.cos(ang), y: parent.y + CLUSTER_R * Math.sin(ang), from: parent };
      placed.push(p);
      byId.set(node.paneId, p);
    });
  }
  if (two || kids.length > 0) relax(placed, w, h);
  return { cx, cy, placed };
}

const CARD_W = 232;
const CARD_H = 118;

/** Crowded fleets: nudge overlapping cards apart (along the axis they overlap least) and keep them on stage. */
function relax(placed: Placed[], w: number, h: number): void {
  for (let pass = 0; pass < 60; pass++) {
    let moved = false;
    for (let i = 0; i < placed.length; i++) {
      for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i];
        const b = placed[j];
        const ox = CARD_W - Math.abs(a.x - b.x);
        const oy = CARD_H - Math.abs(a.y - b.y);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        if (oy < ox) {
          const d = (oy / 2 + 1) * (a.y <= b.y ? 1 : -1);
          a.y -= d;
          b.y += d;
        } else {
          const d = (ox / 2 + 1) * (a.x <= b.x ? 1 : -1);
          a.x -= d;
          b.x += d;
        }
      }
    }
    for (const p of placed) {
      p.x = Math.max(CARD_W / 2, Math.min(w - CARD_W / 2, p.x));
      p.y = Math.max(CARD_H / 2 + 20, Math.min(h - CARD_H / 2, p.y));
    }
    if (!moved) break;
  }
}

function link(cx: number, cy: number, x: number, y: number): string {
  const mx = (cx + x) / 2 + (y - cy) * 0.18;
  const my = (cy + y) / 2 - (x - cx) * 0.18;
  return `M${cx},${cy} Q${mx},${my} ${x},${y}`;
}

function useSize(): [React.RefObject<HTMLElement | null>, { w: number; h: number }] {
  const ref = useRef<HTMLElement | null>(null);
  const [size, setSize] = useState({ w: 900, h: 540 });
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = () => setSize({ w: el.clientWidth, h: el.clientHeight });
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, size];
}

function Node({ p, now, rank, onFocus }: { p: Placed; now: number; rank: number; onFocus: (id: string) => void }) {
  const n = p.node;
  const live = n.subagents.filter((s) => s.live);
  const done = n.subagents.length - live.length;
  const gone = n.status === "gone";
  const body = (
    <>
      <span className="dot">
        {live.map((s, k) => (
          <span key={s.id} className="sat" style={{ ["--a" as string]: `${(k * 180) % 360}deg` }} />
        ))}
      </span>
      <div className="card">
        {n.squad && n.role && !n.parent && <i className="squad-tag">{n.squad} squad</i>}
        <b title={n.title}>{n.roleTitle ?? n.title}</b>
        <span>
          {n.squad ?? n.repo} · <em>{statusLabel(n.status, n.sinceMs, now)}</em>
        </span>
        {(live.length > 0 || done > 0) && (
          <div className="chips">
            {live.map((s) => (
              <span key={s.id} className="chip live" title={s.description || s.agentType}>
                {s.description || s.agentType}
              </span>
            ))}
            {done > 0 && <span className="chip">{done} done</span>}
          </div>
        )}
      </div>
    </>
  );
  const style = {
    left: p.x,
    top: p.y,
    order: rank,
    ["--c" as string]: statusColor(n.status),
  };
  const cls = `node${n.parent ? " kid" : ""} ${n.status === "working" ? "working" : n.status === "needs-you" ? "need" : "idle"}`;
  return gone ? (
    <div className={cls} style={style}>
      {body}
    </div>
  ) : (
    <button type="button" className={cls} style={style} onClick={() => onFocus(n.paneId)}>
      {body}
    </button>
  );
}

export function Constellation({
  fleet,
  now,
  onFocus,
}: {
  fleet: Fleet | null;
  now: number;
  onFocus: (paneId: string) => void;
}) {
  const [ref, { w, h }] = useSize();
  const nodes = fleet?.nodes ?? [];
  const { cx, cy, placed } = place(nodes, w, h);
  const rank = new Map(byAttention(nodes).map((n, i) => [n.paneId, i]));
  const note =
    fleet === null
      ? "Looking for your agents…"
      : !fleet.herdrOk
        ? `I can't read herdr${fleet.error ? `: ${fleet.error}` : "."} Your agents may still be running.`
        : nodes.length === 0
          ? "No agents running. Start one in herdr or ask me."
          : null;
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fault = fleet !== null && !fleet.herdrOk;
  return (
    <section ref={ref} className={`stage${nodes.length > RING_LIMIT ? " many" : ""}`} aria-label="Your agents">
      <svg aria-hidden="true">
        {placed.map(({ node, x, y, from }) => {
          const working = node.status === "working";
          const [sx, sy] = from ? [from.x, from.y] : [cx, cy];
          const d = link(sx, sy, x, y);
          const back = `M${x},${y} Q${(sx + x) / 2 + (y - sy) * 0.18},${(sy + y) / 2 - (x - sx) * 0.18} ${sx},${sy}`;
          return (
            <g key={node.paneId}>
              <path d={d} className={`link${working ? " live" : ""}`} />
              {working && !reduce &&
                [0, -1.2].map((begin) => (
                  <circle key={begin} r="3.2" className="pulse">
                    <animateMotion dur="2.4s" begin={`${begin}s`} repeatCount="indefinite" path={back} />
                    <animate attributeName="opacity" values="0;1;0" dur="2.4s" begin={`${begin}s`} repeatCount="indefinite" />
                  </circle>
                ))}
            </g>
          );
        })}
      </svg>
      <div className={`core${fault ? " fault" : ""}`} style={{ left: cx, top: cy }}>
        <b>CORE</b>
      </div>
      {placed.map((p) => (
        <Node key={p.node.paneId} p={p} now={now} rank={rank.get(p.node.paneId) ?? 0} onFocus={onFocus} />
      ))}
      {note && (
        <p className={`stage-note${fault ? " fault" : ""}`} role="status">
          {note}
        </p>
      )}
    </section>
  );
}

