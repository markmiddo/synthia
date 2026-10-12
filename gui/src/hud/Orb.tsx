import { useEffect, useRef } from "react";
import type { BrainState } from "./brain";
import { Wordmark } from "./Wordmark";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** Local recording (talk key held) wins over what the brain is doing. */
export function orbState(recording: boolean, brain: BrainState): OrbState {
  if (recording) return "listening";
  if (brain === "thinking") return "thinking";
  if (brain === "speaking") return "speaking";
  return "idle";
}

const POINTS = 520;
const SIZE = 500;

/** Seeded so the sphere looks the same on every launch. */
function makePoints(): number[][] {
  let seed = 7;
  const rnd = () => {
    seed = (seed * 16807) % 2147483647;
    return seed / 2147483647;
  };
  const pts: number[][] = [];
  for (let i = 0; i < POINTS; i++) {
    const u = rnd() * 2 - 1;
    const th = rnd() * Math.PI * 2;
    const r = Math.sqrt(1 - u * u);
    pts.push([r * Math.cos(th), u, r * Math.sin(th), rnd()]);
  }
  return pts;
}

const TARGET: Record<OrbState, (t: number) => number> = {
  speaking: (t) => 0.55 + 0.45 * Math.abs(Math.sin(t / 90) * Math.sin(t / 230)),
  listening: () => 0.35,
  thinking: () => 0.25,
  idle: () => 0.08,
};

function reducedMotion(): boolean {
  return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** The particle sphere: drifts when idle, swells when listening, spins faster while thinking,
 *  ripples while she speaks. */
function ParticleOrb({ state }: { state: OrbState }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const mode = useRef<OrbState>(state);
  const redraw = useRef<(() => void) | null>(null);
  mode.current = state;

  useEffect(() => {
    const cv = canvas.current;
    const g = cv?.getContext("2d");
    if (!cv || !g) return;
    const pts = makePoints();
    const c = SIZE / 2;
    const R = c * 0.66;
    let level = 0;
    let raf = 0;
    const draw = (t: number, still: boolean) => {
      const m = mode.current;
      g.clearRect(0, 0, SIZE, SIZE);
      const target = TARGET[m](t);
      level = still ? target : level + (target - level) * 0.12;
      const glow = g.createRadialGradient(c, c, 0, c, c, c * 0.8);
      glow.addColorStop(0, `rgba(143,240,255,${0.3 + level * 0.35})`);
      glow.addColorStop(0.55, `rgba(124,196,255,${0.1 + level * 0.12})`);
      glow.addColorStop(1, "rgba(124,196,255,0)");
      g.fillStyle = glow;
      g.beginPath();
      g.arc(c, c, c * 0.8, 0, 7);
      g.fill();
      const rot = still ? 0.9 : t / (m === "thinking" ? 1600 : 5200);
      const cr = Math.cos(rot);
      const sr = Math.sin(rot);
      for (const p of pts) {
        const x = p[0] * cr - p[2] * sr;
        const z = p[0] * sr + p[2] * cr;
        const wob = 1 + level * 0.18 * Math.sin(p[3] * 12 + t / 120);
        const d = (z + 1) / 2;
        g.fillStyle = `rgba(${(170 + 85 * d) | 0},${(225 + 30 * d) | 0},255,${0.15 + 0.75 * d})`;
        g.beginPath();
        g.arc(c + x * R * wob, c + p[1] * R * wob, 0.8 + 1.8 * d, 0, 7);
        g.fill();
      }
    };
    if (reducedMotion()) {
      redraw.current = () => draw(0, true);
      redraw.current();
      return () => {
        redraw.current = null;
      };
    }
    const loop = (t: number) => {
      draw(t, false);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Reduced motion draws one still frame, so a state change has to redraw it.
  useEffect(() => {
    if (reducedMotion()) redraw.current?.();
  }, [state]);

  return <canvas ref={canvas} width={SIZE} height={SIZE} aria-hidden="true" />;
}

export function Orb({ state, talkKey }: { state: OrbState; talkKey: string }) {
  return (
    <>
      <div className={`orbwrap orb-${state}`} aria-hidden="true">
        <span className="ring" />
        <span className="ring r2" />
        <ParticleOrb state={state} />
      </div>
      <div className="state" role="status">
        <b>
          <Wordmark size={44} />
        </b>
        <span>
          {state === "idle" ? (
            <>
              Ready · hold <em>{talkKey}</em>
            </>
          ) : state === "listening" ? (
            "Listening…"
          ) : state === "thinking" ? (
            "Thinking…"
          ) : (
            "Speaking"
          )}
        </span>
      </div>
    </>
  );
}
