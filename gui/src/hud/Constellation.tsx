import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { statusColor, statusLabel } from "./format";
import type { Fleet, FleetNode } from "./types";

export const RING_LIMIT = 8;

export interface Size {
  w: number;
  h: number;
}

export interface Placed {
  node: FleetNode;
  /** Centre of the card. */
  x: number;
  y: number;
  w: number;
  h: number;
  /** A squad specialist hangs off this director. */
  from?: Placed;
  /** A squad director. */
  head?: boolean;
}

export interface Layout {
  cx: number;
  cy: number;
  placed: Placed[];
  /** The stage height this layout needs (null: use the CSS minimum). */
  height: number | null;
}

const MARGIN = 22;
const CORE_R = 62;
const RING_W = 220;
const KID_W = 150;
const BAND_W = 440;
const WIDE_MIN = 980;
const KID_GAP = 16;
const HEAD_TO_KIDS = 58;
/** A finished or closed squad member leaves the cluster after this long. */
export const MEMBER_LINGER_MS = 120_000;

function sizeOf(node: FleetNode, kid: boolean, sizes: ReadonlyMap<string, Size>): Size {
  const m = sizes.get(node.paneId);
  if (m) return m;
  return { w: kid ? KID_W : RING_W, h: kid ? 70 : 96 };
}

/** Squad members that are done or closed for a while stop taking space in the cluster. */
export function visibleNodes(nodes: FleetNode[], now: number): FleetNode[] {
  return nodes.filter((n) => !(n.parent && (n.status === "done" || n.status === "gone") && now - n.sinceMs > MEMBER_LINGER_MS));
}

/** Stable order: repo, then title, then pane id. Polls never reshuffle the ring. */
function stableOrder(a: FleetNode, b: FleetNode): number {
  return a.repo.localeCompare(b.repo) || a.title.localeCompare(b.title) || a.paneId.localeCompare(b.paneId);
}

/** Push overlapping cards apart along the axis they overlap least, then keep them inside the region. */
function relax(ps: Placed[], x0: number, y0: number, w: number, h: number): void {
  for (let pass = 0; pass < 80; pass++) {
    let moved = false;
    for (let i = 0; i < ps.length; i++) {
      for (let j = i + 1; j < ps.length; j++) {
        const a = ps[i];
        const b = ps[j];
        const ox = (a.w + b.w) / 2 + 14 - Math.abs(a.x - b.x);
        const oy = (a.h + b.h) / 2 + 14 - Math.abs(a.y - b.y);
        if (ox <= 0 || oy <= 0) continue;
        moved = true;
        if (oy < ox) {
          const d = (oy / 2 + 0.5) * (a.y <= b.y ? 1 : -1);
          a.y -= d;
          b.y += d;
        } else {
          const d = (ox / 2 + 0.5) * (a.x <= b.x ? 1 : -1);
          a.x -= d;
          b.x += d;
        }
      }
    }
    for (const p of ps) {
      p.x = Math.max(x0 + MARGIN + p.w / 2, Math.min(x0 + w - MARGIN - p.w / 2, p.x));
      p.y = Math.max(y0 + MARGIN + p.h / 2 + 14, Math.min(y0 + h - MARGIN - p.h / 2, p.y));
    }
    if (!moved) break;
  }
}

interface Region {
  x0: number;
  y0: number;
  w: number;
  h: number;
}

/** Ring agents evenly by angle around the core, in stable order. */
function placeRing(nodes: FleetNode[], r: Region, sizes: ReadonlyMap<string, Size>): { cx: number; cy: number; placed: Placed[] } {
  const cx = r.x0 + r.w / 2;
  const cy = r.y0 + r.h / 2 + 8;
  const ordered = nodes.slice().sort(stableOrder);
  const boxes = ordered.map((node) => ({ node, ...sizeOf(node, false, sizes) }));
  const n = boxes.length;
  const maxW = Math.max(RING_W, ...boxes.map((b) => b.w));
  const maxH = Math.max(90, ...boxes.map((b) => b.h));
  const two = n > RING_LIMIT;
  const rx = Math.max(CORE_R + maxW / 2 + 20, r.w / 2 - MARGIN - maxW / 2);
  const ry = Math.max(CORE_R + maxH / 2 + 24, r.h / 2 - MARGIN - maxH / 2 - 8);
  const outer = two ? Math.ceil(n / 2) : n;
  const placed: Placed[] = boxes.map((b, i) => {
    const onInner = two && i >= outer;
    const count = onInner ? n - outer : outer;
    const k = onInner ? i - outer : i;
    const scale = onInner ? 0.55 : 1;
    const ang = -Math.PI / 2 + Math.PI / count + (k * 2 * Math.PI) / count;
    return { node: b.node, w: b.w, h: b.h, x: cx + rx * scale * Math.cos(ang), y: cy + ry * scale * Math.sin(ang) };
  });
  relax(placed, r.x0, r.y0, r.w, r.h);
  return { cx, cy, placed };
}

/** One squad: the director, with its members in a row (or a column when the row will not fit) beneath it. */
function placeCluster(head: FleetNode, kids: FleetNode[], x: number, w: number, top: number, sizes: ReadonlyMap<string, Size>): { placed: Placed[]; height: number } {
  const hs = sizeOf(head, false, sizes);
  const hp: Placed = { node: head, x, y: top + hs.h / 2, w: hs.w, h: hs.h, head: true };
  const placed: Placed[] = [hp];
  const ks = kids.map((k) => ({ node: k, ...sizeOf(k, true, sizes) }));
  const rowW = ks.reduce((t, k) => t + k.w, 0) + KID_GAP * Math.max(0, ks.length - 1);
  const y1 = top + hs.h + HEAD_TO_KIDS;
  let height = hs.h;
  if (ks.length > 0 && rowW <= w - 2 * MARGIN) {
    let left = x - rowW / 2;
    const rowH = Math.max(...ks.map((k) => k.h));
    for (const k of ks) {
      placed.push({ node: k.node, w: k.w, h: k.h, x: left + k.w / 2, y: y1 + rowH / 2, from: hp });
      left += k.w + KID_GAP;
    }
    height = hs.h + HEAD_TO_KIDS + rowH;
  } else if (ks.length > 0) {
    let y = y1;
    for (const k of ks) {
      placed.push({ node: k.node, w: k.w, h: k.h, x, y: y + k.h / 2, from: hp });
      y += k.h + 12;
    }
    height = y - top - 12;
  }
  return { placed, height };
}

/**
 * Deterministic layout. Ordinary agents sit evenly around CORE; each squad is its own cluster, in a
 * column beside the ring on a wide stage and in bands beneath it on a narrow one. `avail` is the
 * viewport height the stage should try to fit.
 */
export function place(nodes: FleetNode[], w: number, h: number, avail: number, sizes: ReadonlyMap<string, Size> = new Map()): Layout {
  const ids = new Set(nodes.map((n) => n.paneId));
  const family = new Map<string, FleetNode[]>();
  for (const k of nodes) {
    if (k.parent && k.parent !== k.paneId && ids.has(k.parent)) family.set(k.parent, [...(family.get(k.parent) ?? []), k]);
  }
  const heads = nodes.filter((n) => family.has(n.paneId) && !(n.parent && ids.has(n.parent))).sort(stableOrder);
  const hung = new Set<string>();
  for (const hd of heads) for (const k of family.get(hd.paneId) ?? []) hung.add(k.paneId);
  const headIds = new Set(heads.map((n) => n.paneId));
  const ring = nodes.filter((n) => !headIds.has(n.paneId) && !hung.has(n.paneId));
  const clusterOf = (hd: FleetNode, x: number, cw: number, top: number) =>
    placeCluster(hd, (family.get(hd.paneId) ?? []).slice().sort(stableOrder), x, cw, top, sizes);

  if (heads.length === 0) {
    const region = { x0: 0, y0: 0, w, h };
    const { cx, cy, placed } = placeRing(ring, region, sizes);
    return { cx, cy, placed, height: null };
  }

  const wide = w >= WIDE_MIN;
  if (wide) {
    // Squads stack in a right-hand column; the ring owns the rest.
    const bandX = w - BAND_W / 2 - MARGIN;
    const placed: Placed[] = [];
    let top = MARGIN + 14;
    for (const hd of heads) {
      const c = clusterOf(hd, bandX, BAND_W, top);
      placed.push(...c.placed);
      top += c.height + 56;
    }
    const bandsH = top - 56 + MARGIN;
    const height = Math.max(avail, bandsH, 480);
    const region = { x0: 0, y0: 0, w: w - BAND_W - 2 * MARGIN, h: height };
    const r = placeRing(ring, region, sizes);
    return { cx: r.cx, cy: r.cy, placed: [...r.placed, ...placed], height };
  }

  // Narrow: the ring on top, the squads in bands underneath.
  const bandsEstimate = heads.reduce((t, hd) => t + clusterOf(hd, w / 2, w, 0).height + 56, 0);
  const ringH = Math.max(360, Math.min(560, avail - bandsEstimate), ring.length > 3 ? 120 * ring.length + 80 : 0);
  const r = placeRing(ring, { x0: 0, y0: 0, w, h: ringH }, sizes);
  const placed: Placed[] = [...r.placed];
  let top = ringH + MARGIN;
  for (const hd of heads) {
    const c = clusterOf(hd, w / 2, w, top);
    placed.push(...c.placed);
    top += c.height + 56;
  }
  return { cx: r.cx, cy: r.cy, placed, height: top };
}

/** Where a ray from a card's centre toward (tx, ty) leaves the card. */
export function edgePoint(c: { x: number; y: number; w: number; h: number }, tx: number, ty: number): [number, number] {
  const dx = tx - c.x;
  const dy = ty - c.y;
  if (dx === 0 && dy === 0) return [c.x, c.y];
  const t = Math.min(dx !== 0 ? c.w / 2 / Math.abs(dx) : Infinity, dy !== 0 ? c.h / 2 / Math.abs(dy) : Infinity);
  return [c.x + dx * t, c.y + dy * t];
}

function useStageSize(): [React.RefObject<HTMLElement | null>, { w: number; h: number }] {
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

function Node({
  p,
  now,
  replay,
  onFocus,
  onOpenJob,
  setEl,
}: {
  p: Placed;
  now: number;
  replay: boolean;
  onFocus: (id: string) => void;
  onOpenJob: (squad: string, job: string) => void;
  setEl: (id: string, el: HTMLElement | null) => void;
}) {
  const n = p.node;
  const live = n.subagents.filter((s) => s.live);
  const done = n.subagents.length - live.length;
  const gone = n.status === "gone";
  const inert = gone || replay;
  const style = { left: p.x, top: p.y, ["--c" as string]: statusColor(n.status) };
  const cls = `node${n.parent ? " kid" : ""}${p.head ? " head" : ""} ${n.status === "working" ? "working" : n.status === "needs-you" ? "ask" : "idle"}`;
  const body = (
    <>
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
    </>
  );
  return (
    <div className={cls} style={style} ref={(el) => setEl(n.paneId, el)}>
      <span className="dot">
        {live.map((s, k) => (
          <span key={s.id} className="sat" style={{ ["--a" as string]: `${(k * 180) % 360}deg` }} />
        ))}
      </span>
      {inert ? (
        <div className="card">{body}</div>
      ) : (
        <button type="button" className="card" onClick={() => onFocus(n.paneId)}>
          {body}
        </button>
      )}
      {p.head && !replay && n.squad && n.job && (
        <button type="button" className="job-chip" onClick={() => onOpenJob(n.squad as string, n.job as string)}>
          View job
        </button>
      )}
    </div>
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
  const [ref, { w, h }] = useStageSize();
  const nodes = visibleNodes(fleet?.nodes ?? [], now);
  const els = useRef(new Map<string, HTMLElement>());
  const [sizes, setSizes] = useState<ReadonlyMap<string, Size>>(new Map());
  const setEl = (id: string, el: HTMLElement | null) => {
    if (el) els.current.set(id, el);
    else els.current.delete(id);
  };
  // Cards are measured once drawn, so links can end exactly on their edges. A layout never depends
  // on its own positions, so this settles after one extra pass.
  useLayoutEffect(() => {
    let changed = false;
    const next = new Map<string, Size>();
    for (const [id, el] of els.current) {
      const s = { w: el.offsetWidth, h: el.offsetHeight };
      const old = sizes.get(id);
      if (!old || old.w !== s.w || old.h !== s.h) changed = true;
      next.set(id, s);
    }
    if (changed || next.size !== sizes.size) setSizes(next);
  });

  const { cx, cy, placed, height } = place(nodes, w, h, Math.max(0, window.innerHeight - 44), sizes);
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
        {placed.map((p) => {
          if (p.head) return null;
          const working = p.node.status === "working";
          let a: [number, number];
          let b: [number, number];
          if (p.from) {
            a = [p.from.x, p.from.y + p.from.h / 2];
            b = [p.x, p.y - p.h / 2];
          } else {
            b = edgePoint(p, cx, cy);
            const d = Math.hypot(b[0] - cx, b[1] - cy);
            if (d <= CORE_R + 4) return null;
            a = [cx + ((b[0] - cx) / d) * CORE_R, cy + ((b[1] - cy) / d) * CORE_R];
          }
          return (
            <g key={p.node.paneId}>
              <path d={`M${a[0]},${a[1]} L${b[0]},${b[1]}`} className={`link${working ? " live" : ""}`} />
              {working && !reduce &&
                [0, -1.2].map((begin) => (
                  <circle key={begin} r="3.2" className="pulse">
                    <animateMotion dur="2.4s" begin={`${begin}s`} repeatCount="indefinite" path={`M${b[0]},${b[1]} L${a[0]},${a[1]}`} />
                    <animate attributeName="opacity" values="0;1;0" dur="2.4s" begin={`${begin}s`} repeatCount="indefinite" />
                  </circle>
                ))}
            </g>
          );
        })}
      </svg>
      {(placed.some((p) => !p.from && !p.head) || placed.length === 0) && (
        <div className={`core${fault ? " fault" : ""}`} style={{ left: cx, top: cy }}>
          <b>CORE</b>
        </div>
      )}
      {placed.map((p) => (
        <Node key={p.node.paneId} p={p} now={now} replay={replay} onFocus={onFocus} onOpenJob={onOpenJob} setEl={setEl} />
      ))}
      {note && (
        <p className={`stage-note${fault ? " fault" : ""}`} role="status">
          {note}
        </p>
      )}
    </section>
  );
}
