import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ago, type BrainOverview, type LastRecall, type RecallEntry, useRecallEvents } from "./hive";

export interface HiveTeam {
  key: string;
  eyebrow: string;
  title: string;
  meta: string;
  chips: { label: string; live: boolean }[];
}

interface Pulse {
  team: string;
  t: number;
  speed: number;
  inward: boolean;
  color: string;
}

const BRAIN_R = 104;
const WIDE_MIN = 900;
const STAGE_H = 760;
const CARD_W = 230;

interface Pt {
  x: number;
  y: number;
}

/** Where the line from `b` towards `a` leaves card `a` (a little outside it). */
function edgePoint(a: { x: number; y: number; w: number; h: number }, b: Pt): Pt {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const s = Math.min((a.w / 2 + 6) / Math.abs(dx || 1e-6), (a.h / 2 + 6) / Math.abs(dy || 1e-6));
  return { x: a.x + dx * s, y: a.y + dy * s };
}

function bez(p0: Pt, c: Pt, p1: Pt, t: number): Pt {
  const a = 1 - t;
  return { x: a * a * p0.x + 2 * a * t * c.x + t * t * p1.x, y: a * a * p0.y + 2 * a * t * c.y + t * t * p1.y };
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

export function Hive({
  teams,
  overview,
  selected,
  onSelect,
  onOpenBrain,
}: {
  teams: HiveTeam[];
  overview: BrainOverview;
  selected: string | null;
  onSelect: (key: string) => void;
  onOpenBrain: () => void;
}) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const brainRef = useRef<HTMLButtonElement | null>(null);
  const cardRefs = useRef(new Map<string, HTMLButtonElement>());
  const pulses = useRef<Pulse[]>([]);
  const selRef = useRef<string | null>(selected);
  selRef.current = selected;
  const keysRef = useRef<string[]>([]);
  keysRef.current = teams.map((t) => t.key);
  const [width, setWidth] = useState(1000);
  const [now, setNow] = useState(() => Date.now());
  const wide = width >= WIDE_MIN;
  const reduce = typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  useLayoutEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const read = () => setWidth(el.clientWidth);
    read();
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Real recalls become pulses: a read flows in towards the brain (blue), a write flows out (amber).
  useRecallEvents((events: RecallEntry[]) => {
    if (reduce) return;
    for (const e of events.slice(-12)) {
      if (!keysRef.current.includes(e.team.key)) continue;
      const write = e.kind === "write";
      pulses.current.push({ team: e.team.key, t: 0, speed: 0.006 + Math.random() * 0.004, inward: !write, color: write ? "amber" : "blue" });
    }
    if (pulses.current.length > 40) pulses.current.splice(0, pulses.current.length - 40);
  });

  // The canvas: brain, synapses and pulses.
  useEffect(() => {
    const cv = canvasRef.current;
    const stage = stageRef.current;
    const brain = brainRef.current;
    if (!cv || !stage || !brain) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const blue = cssVar("--blue") || "#7cc4ff";
    const amber = cssVar("--amber") || "#ffc66d";
    let W = 0;
    let H = 0;
    let dpr = 1;
    const nodes: { x: number; y: number; z: number; lobe: number; tw: number }[] = [];
    for (let i = 0; i < 520; i++) {
      const u = Math.random() * 2 - 1;
      const th = Math.random() * Math.PI * 2;
      const r = Math.sqrt(1 - u * u);
      nodes.push({ x: r * Math.cos(th), y: u * 0.82, z: r * Math.sin(th), lobe: Math.cos(th) > 0 ? 1 : -1, tw: Math.random() * Math.PI * 2 });
    }
    const size = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1);
      W = stage.clientWidth;
      H = stage.clientHeight;
      cv.width = W * dpr;
      cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(stage);
    let tick = 0;
    let raf = 0;
    const centre = (): Pt => {
      const b = brain.getBoundingClientRect();
      const s = stage.getBoundingClientRect();
      return { x: b.left - s.left + b.width / 2, y: b.top - s.top + b.height / 2 };
    };
    const draw = () => {
      tick++;
      ctx.clearRect(0, 0, W, H);
      const o = centre();
      const s = stage.getBoundingClientRect();
      const links = keysRef.current
        .map((key) => {
          const el = cardRefs.current.get(key);
          if (!el) return null;
          const b = el.getBoundingClientRect();
          const a = { x: b.left - s.left + b.width / 2, y: b.top - s.top + b.height / 2, w: b.width, h: b.height };
          const from = edgePoint(a, o);
          const ang = Math.atan2(from.y - o.y, from.x - o.x);
          const to = { x: o.x + Math.cos(ang) * BRAIN_R, y: o.y + Math.sin(ang) * BRAIN_R };
          const mx = (from.x + to.x) / 2;
          const my = (from.y + to.y) / 2;
          const c = { x: mx - (to.y - from.y) * 0.12, y: my + (to.x - from.x) * 0.12 };
          return { key, from, to, c };
        })
        .filter((l): l is NonNullable<typeof l> => l !== null);
      const sel = selRef.current;
      links.forEach((l, i) => {
        const on = !sel || sel === l.key;
        ctx.beginPath();
        ctx.moveTo(l.from.x, l.from.y);
        ctx.quadraticCurveTo(l.c.x, l.c.y, l.to.x, l.to.y);
        ctx.strokeStyle = on ? "rgba(124,196,255,0.30)" : "rgba(124,196,255,0.08)";
        ctx.lineWidth = sel === l.key ? 1.8 : 1.2;
        ctx.stroke();
        // Quiet: a slow shimmer so a team with no recent recall still reads as connected.
        if (!reduce && !pulses.current.some((p) => p.team === l.key)) {
          const q = bez(l.from, l.c, l.to, (tick * 0.0012 + i * 0.23) % 1);
          ctx.beginPath();
          ctx.arc(q.x, q.y, 1.8, 0, Math.PI * 2);
          ctx.fillStyle = "rgba(124,196,255,0.35)";
          ctx.fill();
        }
      });
      for (const p of pulses.current) {
        const l = links.find((x) => x.key === p.team);
        if (!l) continue;
        p.t += p.speed;
        const tt = p.inward ? p.t : 1 - p.t;
        const color = p.color === "amber" ? amber : blue;
        for (let k = 0; k < 6; k++) {
          const q = bez(l.from, l.c, l.to, Math.max(0, Math.min(1, tt - (p.inward ? k : -k) * 0.012)));
          ctx.beginPath();
          ctx.arc(q.x, q.y, 3.2 - k * 0.45, 0, Math.PI * 2);
          ctx.fillStyle = color;
          ctx.globalAlpha = (1 - k / 6) * (sel && sel !== p.team ? 0.2 : 1);
          ctx.fill();
        }
        ctx.globalAlpha = 1;
      }
      pulses.current = pulses.current.filter((p) => p.t < 1);

      // The brain: a rotating two-lobe particle sphere with filaments, a glow and an orbit ring.
      const rot = reduce ? 0.6 : tick * 0.0032;
      const pts = nodes.map((n) => {
        const x = n.x * Math.cos(rot) - n.z * Math.sin(rot);
        const z = n.x * Math.sin(rot) + n.z * Math.cos(rot);
        return { x: o.x + x * BRAIN_R + n.lobe * 6, y: o.y + n.y * BRAIN_R, z, tw: n.tw };
      });
      const g = ctx.createRadialGradient(o.x, o.y, 10, o.x, o.y, BRAIN_R * 1.35);
      g.addColorStop(0, "rgba(124,196,255,0.22)");
      g.addColorStop(0.6, "rgba(63,143,217,0.07)");
      g.addColorStop(1, "rgba(63,143,217,0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(o.x, o.y, BRAIN_R * 1.35, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineWidth = 0.6;
      for (let i = 0; i < pts.length; i += 3) {
        const a = pts[i];
        const b = pts[(i * 7 + 11) % pts.length];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        if (d < 46 && a.z > -0.2) {
          ctx.strokeStyle = `rgba(124,196,255,${0.16 * (1 - d / 46)})`;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
      for (const p of pts) {
        const depth = (p.z + 1) / 2;
        const flick = reduce ? 0.85 : 0.65 + 0.35 * Math.sin(p.tw + tick * 0.05);
        ctx.fillStyle = `rgba(${(200 + 40 * depth) | 0},${(225 + 25 * depth) | 0},255,${(0.15 + 0.75 * depth) * flick})`;
        ctx.fillRect(p.x, p.y, 1.1 + depth * 1.3, 1.1 + depth * 1.3);
      }
      ctx.strokeStyle = "rgba(124,196,255,0.28)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(o.x, o.y, BRAIN_R + 12, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([2, 6]);
      ctx.beginPath();
      ctx.arc(o.x, o.y, BRAIN_R + 22, rot, rot + Math.PI * 1.4);
      ctx.stroke();
      ctx.setLineDash([]);
      raf = requestAnimationFrame(draw);
    };
    if (reduce) {
      // Static: draw once now and again whenever the layout changes.
      draw();
      cancelAnimationFrame(raf);
      const redraw = () => {
        size();
        draw();
        cancelAnimationFrame(raf);
      };
      const ro2 = new ResizeObserver(redraw);
      ro2.observe(stage);
      const t = setTimeout(redraw, 120);
      return () => {
        clearTimeout(t);
        ro2.disconnect();
        ro.disconnect();
      };
    }
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
    // The drawing reads teams and selection through refs; only the motion preference restarts it.
  }, [reduce, wide, teams.length]);

  const place = (i: number): React.CSSProperties => {
    if (!wide) return {};
    const n = teams.length;
    const ang = -Math.PI / 2 + (2 * Math.PI * i) / n;
    const rx = Math.max(60, width / 2 - CARD_W / 2 - 16);
    const ry = STAGE_H / 2 - 100;
    return { left: width / 2 + rx * Math.cos(ang), top: STAGE_H / 2 + ry * Math.sin(ang) };
  };

  const pull = (key: string) => {
    const r: LastRecall | undefined = overview.lastByTeam[key];
    return r ? (
      <div className="pull">
        {r.kind === "write" ? "Last memory written: " : "Last recall: "}
        <b>{r.title}</b> · {ago(r.atMs, now)}
      </div>
    ) : (
      <div className="pull">No recalls logged yet</div>
    );
  };

  return (
    <div className="hive-wrap">
      <div className="hive-intro">
        <h2>One brain, every team</h2>
        <p>Each team draws on the same memory, skills and context. Pulses show a real recall in flight. Click the brain to look inside it.</p>
      </div>
      <div ref={stageRef} className={`hive${wide ? " wide" : " narrow"}`} style={wide ? { height: STAGE_H } : undefined}>
        <canvas ref={canvasRef} aria-hidden="true" />
        <button type="button" ref={brainRef} className="brain" onClick={onOpenBrain} aria-label="Open the brain">
          <span className="hint">Open</span>
          <span className="blabel">
            <b>The brain</b>
            <span>
              {overview.total.toLocaleString()} memories · {overview.skills} skills · {overview.roles} roles · {overview.connectors} connectors
            </span>
          </span>
        </button>
        <div className="teams">
          {teams.map((t, i) => (
            <button
              key={t.key}
              type="button"
              ref={(el) => {
                if (el) cardRefs.current.set(t.key, el);
                else cardRefs.current.delete(t.key);
              }}
              className={`team${selected === t.key ? " sel" : ""}`}
              style={place(i)}
              onClick={() => onSelect(t.key)}
              aria-pressed={selected === t.key}
            >
              <div className="eyebrow">{t.eyebrow}</div>
              <h3>{t.title}</h3>
              <div className="meta">{t.meta}</div>
              {t.chips.length > 0 && (
                <div className="who">
                  {t.chips.map((c) => (
                    <span key={c.label} className={`hchip${c.live ? " live" : ""}`}>
                      {c.label}
                    </span>
                  ))}
                </div>
              )}
              {pull(t.key)}
            </button>
          ))}
        </div>
      </div>
      <div className="hive-legend">
        <span><i style={{ background: "var(--blue)" }} />Recall in flight</span>
        <span><i style={{ background: "var(--amber)" }} />New memory written</span>
        <span><i style={{ background: "var(--line-hi)" }} />Connected, quiet</span>
      </div>
    </div>
  );
}
