// Fake data for previewing the HUD in a plain browser (dev only, see tauri.ts).
import type { DayChart, Fleet, JobDetail, SquadInfo, SynthiaState, UsageStats } from "./types";

const now = () => Date.now();
const min = 60_000;
const t0 = now();

/** `?mock&n=11` previews a crowded fleet; `?mock&need` puts one agent in "needs you". */
const params = new URLSearchParams(window.location.search);
const EXTRA = Math.max(0, Number(params.get("n") ?? 0) - 3);
const NEEDS = params.has("need");
/** `?mock&squad` adds a live growth squad to the fleet and the Company view. */
const REAL = params.has("real");
const SQUAD = params.has("squad") || REAL;

/** Changes that arrive after load, so the activity feed has something to show. */
let step = 0;
/** Flips a squad writer between working and idle every few seconds, to show the feed ignoring it. */
let flap = 0;

const TYPES = ["Explore", "general-purpose", "bug-hunter", "mark-reviewer", "bob"];
function subs(prefix: string, done: number, live: string[]) {
  const out = Array.from({ length: done }, (_, i) => ({
    id: `${prefix}-d${i}`, description: `Finished task ${i + 1}`, agentType: TYPES[i % TYPES.length], model: i % 2 ? "sonnet" : "opus", live: false,
  }));
  live.forEach((d, i) =>
    out.push({ id: `${prefix}-l${i}`, description: d, agentType: TYPES[(i + 2) % TYPES.length], model: i % 2 ? "sonnet" : "opus", live: step < 1 || i === 0 }),
  );
  return out;
}

/** `?mock&real`: the shape of Mark's real day. Five agents, a growth squad (director and one live
 *  member, plus a designer that finished long ago) and an office squad (director and PM). */
function realFleet(): Fleet {
  const none = { squad: null, job: null, role: null, roleTitle: null, parent: null, session: null, cwd: "", subagents: [] };
  const agent = (id: string, title: string, repo: string, status: Fleet["nodes"][number]["status"], mins: number, subs = 0) => ({
    ...none, paneId: id, agent: "claude", title, repo, status, sinceMs: t0 - mins * min,
    subagents: Array.from({ length: subs }, (_, i) => ({ id: `${id}-${i}`, description: `Task ${i + 1}`, agentType: "general-purpose", model: "opus", live: i === 0 })),
  });
  const member = (id: string, squad: string, job: string, role: string, roleTitle: string, parent: string | null, status: Fleet["nodes"][number]["status"], mins: number) => ({
    ...none, paneId: id, agent: "claude", title: role, repo: "eventflo", squad, job, role, roleTitle, parent, status, sinceMs: t0 - mins * min,
  });
  return {
    herdrOk: true, error: null,
    nodes: [
      agent("r1", "Synthia to Jarvis brainstorm", "synthia", "working", 41, 3),
      agent("r2", "Weekly scheduling setup", "eventflo", "working", 12, 1),
      agent("r3", "Claude Code", "personal", "idle", 95),
      agent("r4", "Eva's performance yesterday", "eva-core", "needs-you", 6, 2),
      agent("r5", "Admin panel PR 175", "admin-panel", "working", 17, 5),
      member("g1", "growth", "2026-10-13-week-of-posts", "growth-director", "Marketing Director", null, "working", 22),
      member("g2", "growth", "2026-10-13-week-of-posts", "growth-writer", "Writer", "g1", "working", 6),
      member("g3", "growth", "2026-10-13-week-of-posts", "growth-designer", "Designer", "g1", "done", 9),
      member("o1", "office", "2026-10-13-board-sweep", "office-chief", "Chief of Staff", null, "working", 15),
      member("o2", "office", "2026-10-13-board-sweep", "office-pm", "Project Manager", "o1", "working", 4),
    ],
  };
}

function fleet(): Fleet {
  if (REAL) return realFleet();
  const nodes: Fleet["nodes"] = [
    {
      paneId: "w1:p1", agent: "claude", status: "working", title: "Admin panel PR 175",
      repo: "admin-panel", cwd: "/home/u/dev/eventflo/admin-panel", session: "s1", sinceMs: t0 - 17 * min,
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
    {
      paneId: "w1:p4", agent: "codex", status: "working", title: "Eva review loop",
      repo: "eva-core", cwd: "/home/u/dev/eventflo/eva-core", session: "s4", sinceMs: t0 - 9 * min,
      squad: null, job: null, role: null, roleTitle: null, parent: null,
      subagents: subs("e", 2, ["Check queue retries"]),
    },
  ];
  if (SQUAD) {
    const base = { agent: "claude", repo: "eventflo", cwd: "", session: null, subagents: [], squad: "growth", job: "2026-10-13-week-of-posts" };
    nodes.push(
      { ...base, paneId: "w3:p1", status: "working", title: "growth-director", role: "growth-director", roleTitle: "Marketing Director", parent: null, sinceMs: t0 - 22 * min },
      { ...base, paneId: "w3:p2", status: flap % 2 === 1 ? "idle" : "working", title: "growth-writer-1", role: "growth-writer", roleTitle: "Writer", parent: "w3:p1", sinceMs: t0 - 6 * min },
      { ...base, paneId: "w3:p3", status: "idle", title: "growth-seo-1", role: "growth-seo", roleTitle: "SEO Strategist", parent: "w3:p1", sinceMs: t0 - 9 * min },
      { ...base, paneId: "w3:p4", status: "working", title: "growth-editor-1", role: "growth-editor", roleTitle: "Editor and Fact-checker", parent: "w3:p1", sinceMs: t0 - 2 * min },
    );
  }
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
  five_hour_pct: 7, five_hour_resets_in: "2h 46m", five_hour_resets_at: new Date(t0 + 166 * min).toISOString(),
  seven_day_pct: 40, seven_day_resets_in: "58h 20m", seven_day_resets_at: new Date(t0 + 58 * 60 * min).toISOString(),
  seven_day_opus_pct: 31, seven_day_sonnet_pct: 9, error: null,
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
          { id: "growth-director", title: "Marketing Director", model: "claude-opus-5-5", hires: ["growth-seo", "growth-writer", "growth-editor", "growth-designer"], description: "Runs the growth team.", prompt: "You run the growth team.\n\nHire specialists, review their work, deliver.", hasAgentFile: true },
          { id: "growth-seo", title: "SEO Strategist", model: "claude-sonnet-5-5", hires: [], description: "Keywords and briefs.", prompt: "You find the topics worth writing.", hasAgentFile: true },
          { id: "growth-writer", title: "Writer", model: "claude-sonnet-5-5", hires: [], description: "Drafts posts.", prompt: "You write the posts.", hasAgentFile: true },
          { id: "growth-designer", title: "Designer", model: "claude-sonnet-5-5", hires: [], description: "Images.", prompt: "You design.", hasAgentFile: true },
          { id: "growth-editor", title: "Editor and Fact-checker", model: "claude-haiku-5-5", hires: [], description: "Edits.", prompt: "You edit and check facts.", hasAgentFile: false },
        ],
        jobs: [
          { id: "2026-10-13-week-of-posts", path: "/mock/job", state: "working", updatedMs: t0 - 2 * min, lastLog: "Writer is drafting post two of five" },
          { id: "2026-10-06-launch-notes", path: "/mock/job2", state: "done", updatedMs: t0 - 7 * 24 * 60 * min, lastLog: "Delivered four posts" },
        ],
      },
    ]
  : [];

const JOB: JobDetail = {
  id: "2026-10-13-week-of-posts", squad: "growth", path: "/mock/job", state: "working",
  brief: "# Week of posts\n\nWrite **five** blog posts for the eventflo blog this week.\n\n- Audience: promoters running first events\n- Tone: plain, practical\n- Each post links to one help article",
  log: [
    { at: new Date(t0 - 2 * min).toISOString(), who: "growth-writer", text: "Drafting post two of five" },
    { at: new Date(t0 - 8 * min).toISOString(), who: "growth-seo", text: "Delivered keyword brief for all five posts" },
    { at: new Date(t0 - 21 * min).toISOString(), who: "growth-director", text: "Hired SEO Strategist and Writer" },
    { at: new Date(t0 - 22 * min).toISOString(), who: "growth-director", text: "Briefed" },
  ],
  deliverables: [
    { name: "keywords.json", size: 3180, path: "keywords.json", kind: "json", thumb: null },
    { name: "post-1.md", size: 6240, path: "post-1.md", kind: "md", thumb: null },
    { name: "hero.png", size: 48200, path: "hero.png", kind: "image", thumb: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='60' height='40'><rect width='60' height='40' fill='%232c4a74'/><circle cx='30' cy='20' r='10' fill='%238ff0ff'/></svg>" },
  ],
};

const li = (id: string, title: string, ago: number, extra: object = {}) => ({
  id, title, detail: "", recommendation: null, undo: null, createdAt: t0 - ago * min, links: [], ...extra,
});
const LEDGER = {
  doneCount: 14, callCount: 5, waitingCount: 2,
  done: [
    li("d1", "Merged the Eva hotfix to main and watched the deploy", 12, { detail: "CI and Eva were green. Deploy finished clean; checked the escalation reply on prod." }),
    li("d2", "Email triage: 13 archived, Vishal invoice kept", 55),
    li("d3", "Filed #3387 for the impersonation image upload error", 90),
    li("d4", "Dependabot wave 1 merged to dev", 140),
    li("d5", "Squad install command shipped", 200), li("d6", "Role editor polished", 230), li("d7", "Job panel built", 260),
    li("d8", "Timeline replaced by day chip", 300), li("d9", "Calendar helper checked", 340), li("d10", "Weekly report drafted", 380),
  ],
  calls: [
    li("c1", "Branched the squads work off feat/squads", 30, { detail: "The active branch had unmerged HUD work, so a clean development branch would have hidden it.", undo: "git branch -D feat/squads-c" }),
    li("c2", "Kept the brain on the desk machine", 70), li("c3", "Used the CPU small model", 120),
  ],
  waiting: [
    li("b1", "Enable weekday 7:30 board sweep + monthly investor update timers?", 25, { detail: "Both squads are installed and tested. Timers are not enabled.", recommendation: "Yes, enable both." }),
    li("b2", "Merge multi-tier be#3837 then op#1467?", 900, { detail: "Both are green on development.", recommendation: "Merge after be#3836." }),
  ],
};
const day0 = new Date(t0); day0.setHours(0, 0, 0, 0);
const dueDate = (offset: number) => { const d = new Date(day0); d.setDate(d.getDate() + offset); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const DUE = [
  { id: "a1", kind: "pay", title: "Vishal INV-2026-10-02 AUD 1,950", due: dueDate(-2), overdue: true },
  { id: "a2", kind: "reply", title: "Reply to Josh about Reminisce wages", due: dueDate(0), overdue: false },
];
const SHIPPED = {
  ok: true,
  items: [
    { number: 392, title: "Fix escalation for how-to questions", repo: "eva-ai", url: "https://github.com/eventfloHQ/eva-ai/pull/392" },
    { number: 3836, title: "Prod hotfix: ticket scan retry", repo: "backend", url: "https://github.com/eventfloHQ/backend/pull/3836" },
    { number: 1745, title: "Gate the scanner contrast change", repo: "frontend", url: "https://github.com/eventfloHQ/frontend/pull/1745" },
  ],
};
const RELEASE = {
  ok: true, title: "Version 3.2 Release", url: "https://github.com/orgs/eventfloHQ/projects/16", total: 133,
  counts: [
    { status: "Backlog", count: 4 }, { status: "In review", count: 13 }, { status: "Testing", count: 2 },
    { status: "Ready for Prod", count: 4 }, { status: "Done", count: 110 },
  ],
};
const MEETING = {
  state: "ok",
  next: { title: "Weekly management and product jam", startMs: t0 + 8 * min, link: "https://calendar.google.com/calendar/event?eid=mock" },
  moreToday: 2,
};
const SPEND = { ok: true, percent: 6.2, points: [0, 0.4, 1.1, 1.6, 2.9, 3.4, 4.8, 5.1, 6.2], firstAt: t0 - 6 * 60 * min, distinct: 8 };
const BUGS = { ok: true, asOf: new Date(t0 - 24 * 60 * min).toISOString().slice(0, 10), leftToFix: 42, high: 5, noFix: 38, planned: 13, fixInProgress: 4, awaitingQa: 22, awaitingRelease: 37 };
const SQUAD_OUT = { deliverables: 4, jobsFinished: 1 };

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
    today_ledger: LEDGER,
    today_inbox: DUE,
    today_shipped: SHIPPED,
    today_release: RELEASE,
    today_meeting: MEETING,
    today_spend: SPEND,
    today_bugs: BUGS,
    open_bug_dashboard: null,
    today_squad_output: SQUAD_OUT,
    open_url: null,
    squad_job_detail: JOB,
    squad_stop_job: "",
    squad_start_job: "",
    squad_open_file: null,
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
    ...[10000, 12500, 15000, 17500, 20000].map((ms) => setTimeout(() => { flap++; handler(fleet() as T); }, ms)),
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
