// Fake data for previewing the HUD in a plain browser (dev only, see tauri.ts).
import type { DayChart, Fleet, SquadInfo, SynthiaState, UsageStats } from "./types";

const now = () => Date.now();
const min = 60_000;
const t0 = now();

/** `?mock&n=11` previews a crowded fleet; `?mock&need` puts one agent in "needs you". */
const params = new URLSearchParams(window.location.search);
const EXTRA = Math.max(0, Number(params.get("n") ?? 0) - 3);
const NEEDS = params.has("need");
/** `?mock&squad` adds a live growth squad to the fleet and the Company view. */
const SQUAD = params.has("squad");

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
      squad: null, job: null, role: null, roleTitle: null, parent: null,
      subagents: subs("a", 10, ["Multi-tier promoter unlock build", "Promoter code manual unlock fix"]),
    },
    {
      paneId: "w1:p2", agent: "claude", status: NEEDS ? "needs-you" : "working", title: "Synthia to Jarvis brainstorm",
      repo: "synthia", cwd: "", session: "s2", sinceMs: t0 - 1 * min,
      squad: null, job: null, role: null, roleTitle: null, parent: null, subagents: subs("b", 12, []),
    },
    {
      paneId: "w1:p3", agent: "claude", status: step >= 2 ? "working" : "idle", title: "Remote working visa timing",
      repo: "personal", cwd: "", session: "s3", sinceMs: t0 - 81 * min,
      squad: null, job: null, role: null, roleTitle: null, parent: null, subagents: [],
    },
  ];
  for (let i = 0; i < EXTRA; i++) {
    nodes.push({
      paneId: `w2:p${i}`, agent: "claude", status: i % 3 === 0 ? "working" : i % 3 === 1 ? "idle" : "done",
      title: i === 0 ? "A deliberately long agent title that has to wrap inside its card and then be cut off" : `Side quest ${i + 1}`,
      repo: "eventflo", cwd: "", session: `x${i}`, sinceMs: t0 - (5 + i * 7) * min,
      squad: null, job: null, role: null, roleTitle: null, parent: null,
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

const SQUADS: SquadInfo[] = SQUAD
  ? [
      {
        id: "growth", name: "Growth", director: "growth-director", cap: 4, cwd: "~/dev/eventflo",
        roles: [
          { id: "growth-director", title: "Marketing Director", model: "claude-opus-5-5", hires: ["growth-seo", "growth-writer", "growth-editor"], description: "Runs the growth team.", prompt: "You run the growth team.\n\nHire specialists, review their work, deliver.", hasAgentFile: true },
          { id: "growth-seo", title: "SEO Strategist", model: "claude-sonnet-5-5", hires: [], description: "Keywords and briefs.", prompt: "You find the topics worth writing.", hasAgentFile: true },
          { id: "growth-writer", title: "Writer", model: "claude-sonnet-5-5", hires: [], description: "Drafts posts.", prompt: "You write the posts.", hasAgentFile: true },
          { id: "growth-editor", title: "Editor and Fact-checker", model: "claude-haiku-5-5", hires: [], description: "Edits.", prompt: "You edit and check facts.", hasAgentFile: false },
        ],
        jobs: [
          { id: "2026-10-13-week-of-posts", path: "/mock/job", state: "working", updatedMs: t0 - 2 * min, lastLog: "Writer is drafting post two of five" },
          { id: "2026-10-06-launch-notes", path: "/mock/job2", state: "done", updatedMs: t0 - 7 * 24 * 60 * min, lastLog: "Delivered four posts" },
        ],
      },
    ]
  : [];

export function mockCall<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const table: Record<string, unknown> = {
    fleet_snapshot: fleet(),
    get_usage_stats: usage,
    get_status: "running",
    get_voice_muted: false,
    get_desk_token: "mock",
    get_hotkeys: ["none", "Key.alt_l"],
    get_synthia_state: { status: "ready", recording: false } satisfies SynthiaState,
    squads_list: SQUADS,
    squad_role_save: null,
    squad_open_job: null,
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
  "Three agents are up and none of them is blocked on you. The admin panel hotfix needs about half an hour. Want the detail?";

export function startMockBrain(send: (frame: Record<string, unknown>) => void): () => void {
  const timers: ReturnType<typeof setTimeout>[] = [];
  send({ type: "state", value: "idle" });
  timers.push(setTimeout(() => send({ type: "state", value: "thinking" }), 300));
  timers.push(
    setTimeout(() => {
      send({ type: "state", value: "speaking" });
      send({ type: "delta", text: MOCK_LINE });
      timers.push(
        setTimeout(() => {
          send({ type: "reply_done", text: MOCK_LINE });
          send({ type: "state", value: "idle" });
        }, 300),
      );
    }, 1400),
  );
  return () => timers.forEach(clearTimeout);
}
