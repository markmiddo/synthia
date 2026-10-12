// Fake data for previewing the HUD in a plain browser (dev only, see tauri.ts).
import type { DayChart, Fleet, SynthiaState, UsageStats } from "./types";

const now = () => Date.now();
const min = 60_000;
const t0 = now();

/** `?mock&n=11` previews a crowded fleet; `?mock&need` puts one agent in "needs you". */
const params = new URLSearchParams(window.location.search);
const EXTRA = Math.max(0, Number(params.get("n") ?? 0) - 3);
const NEEDS = params.has("need");

/** Changes that arrive after load, so the activity feed has something to show. */
let step = 0;

function subs(prefix: string, done: number, live: string[]) {
  const out = Array.from({ length: done }, (_, i) => ({
    id: `${prefix}-d${i}`, description: `Finished task ${i + 1}`, agentType: "general-purpose", model: "opus", live: false,
  }));
  live.forEach((d, i) =>
    out.push({ id: `${prefix}-l${i}`, description: d, agentType: "general-purpose", model: "opus", live: step < 1 || i === 0 }),
  );
  return out;
}

function fleet(): Fleet {
  const nodes: Fleet["nodes"] = [
    {
      paneId: "w1:p1", agent: "claude", status: "working", title: "Admin panel PR 175",
      repo: "eventflo", cwd: "", session: "s1", sinceMs: t0 - 17 * min,
      subagents: subs("a", 10, ["Multi-tier promoter unlock build", "Promoter code manual unlock fix"]),
    },
    {
      paneId: "w1:p2", agent: "claude", status: NEEDS ? "needs-you" : "working", title: "Synthia to Jarvis brainstorm",
      repo: "synthia", cwd: "", session: "s2", sinceMs: t0 - 1 * min, subagents: subs("b", 12, []),
    },
    {
      paneId: "w1:p3", agent: "claude", status: step >= 2 ? "working" : "idle", title: "Remote working visa timing",
      repo: "personal", cwd: "", session: "s3", sinceMs: t0 - 81 * min, subagents: [],
    },
  ];
  for (let i = 0; i < EXTRA; i++) {
    nodes.push({
      paneId: `w2:p${i}`, agent: "claude", status: i % 3 === 0 ? "working" : i % 3 === 1 ? "idle" : "done",
      title: i === 0 ? "A deliberately long agent title that has to wrap inside its card and then be cut off" : `Side quest ${i + 1}`,
      repo: "eventflo", cwd: "", session: `x${i}`, sinceMs: t0 - (5 + i * 7) * min,
      subagents: i % 2 === 0 ? subs(`x${i}`, 2, ["Checking"]) : [],
    });
  }
  return { herdrOk: true, error: null, nodes };
}

const usage: UsageStats = {
  five_hour_pct: 2, five_hour_resets_in: "4h 10m", seven_day_pct: 11, error: null,
};

function day(date: string): DayChart {
  const today = new Date(t0);
  const isToday = date === `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
  const end = isToday ? t0 : new Date(`${date}T18:00:00`).getTime();
  const at = (ago: number) => end - ago * min;
  const sub = (d: string, a: number, b: number) => ({
    description: d, agentType: "general-purpose", model: "opus", firstSeen: at(a), lastSeen: at(b), lastLive: false,
  });
  return {
    date,
    nodes: {
      n1: {
        paneId: "w1:p1", agent: "claude", title: "Admin panel PR 175", repo: "eventflo", session: "s1",
        firstSeen: at(560), lastSeen: end, lastStatus: "working",
        subagents: { s1: sub("Multi-tier promoter unlock build", 34, 4) },
      },
      n2: {
        paneId: "w1:p2", agent: "claude", title: "Synthia to Jarvis brainstorm", repo: "synthia", session: "s2",
        firstSeen: at(300), lastSeen: end, lastStatus: "working", subagents: {},
      },
      n3: {
        paneId: "w1:p3", agent: "claude", title: "Remote working visa timing", repo: "personal", session: "s3",
        firstSeen: at(210), lastSeen: at(81), lastStatus: "idle", subagents: {},
      },
    },
  };
}

export function mockCall<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const table: Record<string, unknown> = {
    fleet_snapshot: fleet(),
    get_usage_stats: usage,
    get_status: "running",
    get_voice_muted: false,
    get_desk_token: "mock",
    get_hotkeys: ["none", "Key.alt_l"],
    get_synthia_state: { status: "ready", recording: false } satisfies SynthiaState,
    fleet_day: day(String(args?.date ?? "")),
  };
  return Promise.resolve((cmd in table ? table[cmd] : null) as T);
}

export function mockListen<T>(event: string, handler: (p: T) => void): () => void {
  if (event !== "fleet") return () => {};
  const timers = [
    setTimeout(() => handler(fleet() as T), 50),
    setTimeout(() => { step = 1; handler(fleet() as T); }, 4000),
    setTimeout(() => { step = 2; handler(fleet() as T); }, 8000),
  ];
  return () => timers.forEach(clearTimeout);
}

const MOCK_LINE =
  "Three agents are up and none of them is blocked on you. Admin panel PR 175 has two builds running. Tomorrow, the Symbiotic tier-count repair is due.";

export function startMockBrain(send: (frame: Record<string, unknown>) => void): () => void {
  const timers: ReturnType<typeof setTimeout>[] = [];
  send({ type: "state", value: "idle" });
  timers.push(setTimeout(() => send({ type: "state", value: "thinking" }), 300));
  timers.push(
    setTimeout(() => {
      send({ type: "state", value: "speaking" });
      const words = MOCK_LINE.split(" ");
      words.forEach((w, i) =>
        timers.push(setTimeout(() => send({ type: "delta", text: (i ? " " : "") + w }), i * 110)),
      );
      timers.push(
        setTimeout(() => {
          send({ type: "reply_done", text: MOCK_LINE });
          send({ type: "state", value: "idle" });
        }, words.length * 110 + 300),
      );
    }, 1400),
  );
  return () => timers.forEach(clearTimeout);
}
