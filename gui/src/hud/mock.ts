// Fake data for previewing the HUD in a plain browser (dev only, see tauri.ts).
import type { DayChart, Fleet, SynthiaState, UsageStats } from "./types";

const now = () => Date.now();
const min = 60_000;

function fleet(): Fleet {
  return {
    herdrOk: true,
    error: null,
    nodes: [
      {
        paneId: "w1:p1", agent: "claude", status: "working", title: "Gallery drafts #3338",
        repo: "organizer-platform", cwd: "", session: "s1", sinceMs: now() - 52 * min,
        subagents: [
          { id: "a1", description: "Eva review fixes", agentType: "general-purpose", model: "opus", live: true },
          { id: "a2", description: "Verify on dev", agentType: "general-purpose", model: "opus", live: false },
        ],
      },
      {
        paneId: "w1:p2", agent: "claude", status: "needs-you", title: "Tier-count repair #3275",
        repo: "backend", cwd: "", session: "s2", sinceMs: now() - 13 * min,
        subagents: [
          { id: "a3", description: "Find moved Hype tickets", agentType: "Explore", model: "sonnet", live: false },
        ],
      },
      {
        paneId: "w1:p3", agent: "claude", status: "working", title: "Pharcyde backfill",
        repo: "backend", cwd: "", session: "s3", sinceMs: now() - 42 * min,
        subagents: [
          { id: "a4", description: "Dry-run count", agentType: "general-purpose", model: "opus", live: true },
        ],
      },
      {
        paneId: "w1:p4", agent: "claude", status: "idle", title: "Admin panel PR 175",
        repo: "admin-panel", cwd: "", session: "s4", sinceMs: now() - 120 * min, subagents: [],
      },
      {
        paneId: "w1:p5", agent: "claude", status: "done", title: "Custom questions",
        repo: "organizer-platform", cwd: "", session: "s5", sinceMs: now() - 40 * min, subagents: [],
      },
    ],
  };
}

const usage: UsageStats = {
  five_hour_pct: 62, five_hour_resets_in: "2h 10m", seven_day_pct: 41, error: null,
};

function day(date: string): DayChart {
  const t = new Date(`${date}T09:00:00`).getTime();
  return {
    date,
    nodes: {
      x1: {
        paneId: "w1:p1", agent: "claude", title: "Gallery drafts #3338", repo: "organizer-platform",
        session: "x1", firstSeen: t, lastSeen: t + 3 * 60 * min, lastStatus: "done",
        subagents: { y1: { description: "Eva review fixes", agentType: "general-purpose", model: "opus", firstSeen: t, lastSeen: t + 60 * min, lastLive: false } },
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
    get_synthia_state: { status: "ready", recording: false } satisfies SynthiaState,
    fleet_day: day(String(args?.date ?? "")),
  };
  return Promise.resolve((cmd in table ? table[cmd] : null) as T);
}

export function mockListen<T>(event: string, handler: (p: T) => void): () => void {
  if (event !== "fleet") return () => {};
  const t = setTimeout(() => handler(fleet() as T), 50);
  return () => clearTimeout(t);
}

export function startMockBrain(send: (frame: Record<string, unknown>) => void): () => void {
  send({ type: "state", value: "idle" });
  send({
    type: "reply_done",
    text: "Three agents running. Gallery's through review and with Vishal. Tier-count is waiting on your call.",
  });
  return () => {};
}
