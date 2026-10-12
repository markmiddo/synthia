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
  /** A squad director: its band has its own links, none to the core. */
  head?: boolean;
}

const RING_H = 560;
const WIDE_CLUSTER_H = 330;
const NARROW_W = 560;
const KID_STEP = 158;

/** Ordinary agents sit on an ellipse around the core; past eight they use two. A squad is its own
 *  band below the ring: the director in the middle, its specialists in an arc beneath it (a column
 *  when the stage is narrow), each linked to the director. Pure, for the layout. */
export function place(
  nodes: FleetNode[],
  w: number,
  h: number,
): { cx: number; cy: number; placed: Placed[]; height: number | null } {
  const ids = new Set(nodes.map((n) => n.paneId));
  const isKid = (n: FleetNode) => n.parent !== null && n.parent !== n.paneId && ids.has(n.parent);
  const kids = nodes.filter(isKid);
  const family = new Map<string, FleetNode[]>();
  for (const k of kids) family.set(k.parent as string, [...(family.get(k.parent as string) ?? []), k]);
  // A specialist whose parent is itself a specialist (a malformed registry) is treated as ordinary.
  const heads = nodes.filter((n) => family.has(n.paneId) && !isKid(n));
  const headIds = new Set(heads.map((n) => n.paneId));
  const hung = new Set<string>();
  for (const [parent, group] of family) if (headIds.has(parent)) group.forEach((g) => hung.add(g.paneId));
  const ring = nodes.filter((n) => !headIds.has(n.paneId) && !hung.has(n.paneId));

  const narrow = w < NARROW_W;
  const banded = heads.length > 0;
  const ringH = banded ? (narrow ? Math.max(RING_H, ring.length * 130 + 200) : RING_H) : h;
  const cx = w / 2;
  const cy = ringH * 0.46;
  const two = ring.length > RING_LIMIT;
  const rx = two ? Math.min(w * 0.4, 440) : Math.min(w * 0.36, 380);
  const ry = two ? Math.min(ringH * 0.4, 360) : Math.min(ringH * 0.34, 230);
  const outer = two ? Math.ceil(ring.length / 2) : ring.length;
  const placed: Placed[] = ring.map((node, i) => {
    const onInner = two && i >= outer;
    const count = onInner ? ring.length - outer : outer;
    const k = onInner ? i - outer : i;
    const scale = onInner ? 0.55 : 1;
    const ang = -Math.PI / 2 + (k + (onInner ? 1 : 0.5)) * ((2 * Math.PI) / count) + 0.35;
    return { node, x: cx + rx * scale * Math.cos(ang), y: cy + ry * scale * Math.sin(ang) };
  });
  if (two || (banded && narrow)) relax(placed, w, ringH);

  let top = banded ? ringH : 0;
  for (const head of heads) {
    const group = family.get(head.paneId) ?? [];
    const n = group.length;
    const hp: Placed = { node: head, x: cx, y: top + 70, head: true };
    placed.push(hp);
    if (narrow) {
      group.forEach((node, i) => placed.push({ node, x: cx, y: hp.y + 130 + i * 112, from: hp }));
      top += 150 + n * 112 + 40;
    } else {
      const step = n > 1 ? Math.min(KID_STEP, (w - 40 - 150) / (n - 1)) : 0;
      group.forEach((node, i) => {
        const off = n > 1 ? i - (n - 1) / 2 : 0;
        const edge = n > 1 ? Math.abs(off) / ((n - 1) / 2) : 0;
        placed.push({ node, x: cx + off * step, y: hp.y + 170 + 36 * edge * edge, from: hp });
      });
      top += WIDE_CLUSTER_H;
    }
  }
  return { cx, cy, placed, height: banded ? top : null };
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

function Node({ p, now, rank, replay, onFocus }: { p: Placed; now: number; rank: number; replay: boolean; onFocus: (id: string) => void }) {
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
  return gone || replay ? (
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
  onOpenJob,
  replay = false,
}: {
  fleet: Fleet | null;
  now: number;
  onFocus: (paneId: string) => void;
  onOpenJob: (squad: string, job: string) => void;
  /** Showing a past day: nothing is clickable. */
  replay?: boolean;
}) {
  const [ref, { w, h }] = useSize();
  const nodes = fleet?.nodes ?? [];
  const { cx, cy, placed, height } = place(nodes, w, h);
  const rank = new Map(byAttention(nodes).map((n, i) => [n.paneId, i]));
  const note =
    fleet === null
      ? "Looking for your agents…"
      : !fleet.herdrOk
        ? `I can't read herdr${fleet.error ? `: ${fleet.error}` : "."} Your agents may still be running.`
        : nodes.length === 0
          ? replay
            ? "No agents were running that day."
            : "No agents running. Start one in herdr or ask me."
          : null;
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  const fault = fleet !== null && !fleet.herdrOk;
  return (
    <section
      ref={ref}
      className={`stage${nodes.length > RING_LIMIT ? " many" : ""}`}
      style={height ? { minHeight: height } : undefined}
      aria-label="Your agents"
    >
      <svg aria-hidden="true">
        {placed.map(({ node, x, y, from, head }) => {
          if (head) return null;
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
        <Node key={p.node.paneId} p={p} now={now} rank={rank.get(p.node.paneId) ?? 0} replay={replay} onFocus={onFocus} />
      ))}
      {placed
        .filter((p) => !replay && p.head && p.node.squad && p.node.job)
        .map((p) => (
          <button
            key={`job-${p.node.paneId}`}
            type="button"
            className="cluster-open"
            style={{ left: p.x, top: p.y + 82 }}
            onClick={() => onOpenJob(p.node.squad as string, p.node.job as string)}
          >
            View job
          </button>
        ))}
      {note && (
        <p className={`stage-note${fault ? " fault" : ""}`} role="status">
          {note}
        </p>
      )}
    </section>
  );
}

