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

const SQUADS: SquadInfo[] = [
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
    
      {
        id: "office", name: "Office", director: "office-chief", cap: 3, cwd: "~/dev/eventflo",
        roles: [
          { id: "office-chief", title: "Chief of Staff", model: "claude-opus-5-5", hires: ["office-pm", "office-dev-release"], description: "Runs the office team.", prompt: "You run the office team.", hasAgentFile: true },
          { id: "office-pm", title: "Project Manager", model: "claude-sonnet-5-5", hires: [], description: "Board hygiene.", prompt: "You keep the boards clean.", hasAgentFile: true },
          { id: "office-dev-release", title: "Dev Release Writer", model: "claude-sonnet-5-5", hires: [], description: "Monthly update.", prompt: "You write the update.", hasAgentFile: true },
        ],
        jobs: [{ id: "2026-10-13-board-sweep", path: "/mock/job3", state: "working", updatedMs: t0 - 4 * min, lastLog: "Moved 7 double-listed cards" }],
      },
      {
        id: "release", name: "Release", director: "release-lead", cap: 3, cwd: "~/dev/eventflo",
        roles: [
          { id: "release-lead", title: "Release Lead", model: "claude-opus-5-5", hires: ["release-faq", "release-video"], description: "Runs a release.", prompt: "You run the release.", hasAgentFile: true },
          { id: "release-faq", title: "Help Centre Writer", model: "claude-sonnet-5-5", hires: [], description: "Help articles.", prompt: "You update the help centre.", hasAgentFile: true },
          { id: "release-video", title: "Video Editor", model: "claude-sonnet-5-5", hires: [], description: "Walkthrough edits.", prompt: "You edit the video.", hasAgentFile: true },
        ],
        jobs: [],
      },
    ]

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

const MEM_ROWS = [
  { kind: "feedback", name: "Never use Codex for building", description: "Mark, 12 Sep 2026: builds and fix rounds stay on Claude. Codex reviews are fine.", used: 4, teams: ["Engineering", "Synthia"] },
  { kind: "feedback", name: "Competitor fees are verified and cited", description: "Any competitor fee or pricing claim is re-checked on their own page the day it is written, and cited.", used: 6, teams: ["Growth"] },
  { kind: "feedback", name: "Bug dashboard shows production bugs only", description: "Lead with left to fix; QA and audit catches are one grey footnote.", used: 2, teams: ["Office", "Synthia"] },
  { kind: "project", name: "Offline scanning must ship", description: "Hard requirement after the Altitude connectivity failure.", used: 1, teams: ["Engineering", "Growth"] },
  { kind: "project", name: "Board cleanup, 26 Sep", description: "139 shipped issues closed and the rules Mark approved for stale cards.", used: 3, teams: ["Office"] },
  { kind: "reference", name: "Nano Banana Pro image generation", description: "Gemini image endpoint, the body-shape gotcha and where the key lives.", used: 3, teams: ["Growth"] },
  { kind: "reference", name: "Ledger panel", description: "Done, Calls made, Waiting on Mark. Every reported item is logged there.", used: 22, teams: ["Synthia", "Engineering"] },
  { kind: "feedback", name: "Build on Claude first, offload at 80%", description: "Kimi or OpenCode only when weekly usage passes about 80% with lots of week left.", used: 1, teams: ["Synthia"] },
].map((m, i) => ({ path: `/mock/memory/${i}.md`, modifiedMs: t0 - (i + 1) * 3 * 60 * min, recalls7d: m.used, recalledToday: Math.min(m.used, 3), teams7d: m.teams, kind: m.kind, name: m.name, description: m.description }));

const RECALL_HISTORY = [
  { m: 3, team: "synthia", label: "Synthia", title: "Decide and report", kind: "read" },
  { m: 14, team: "synthia", label: "Synthia", title: "Telegram voice timeouts count as delivered", kind: "write" },
  { m: 22, team: "growth", label: "Growth · Designer", title: "Nano Banana Pro image generation", kind: "read" },
  { m: 41, team: "office", label: "Office · Project Manager", title: "One board per issue", kind: "read" },
  { m: 55, team: "engineering", label: "Engineering · Admin panel PR 175", title: "V1/V2 wiring landmines", kind: "read" },
  { m: 80, team: "growth", label: "Growth · Editor", title: "Competitor fees are verified and cited", kind: "read" },
  { m: 130, team: "synthia", label: "Synthia", title: "Squads build plan decisions", kind: "write" },
].map((r) => ({ atMs: t0 - r.m * min, kind: r.kind, title: r.title, file: "/mock/memory/x.md", team: { key: r.team, label: r.label }, who: "" })).reverse();

const LIVE_TEAMS: [string, string][] = [["synthia", "Synthia"], ["engineering", "Engineering · Admin panel PR 175"], ["growth", "Growth · Writer"], ["office", "Office · Project Manager"]];
const LAST_BY_TEAM = {
  synthia: { title: "Decide and report", atMs: t0 - 3 * min, kind: "read" },
  engineering: { title: "V1/V2 wiring landmines", atMs: t0 - 55 * min, kind: "read" },
  growth: { title: "Competitor fees, verified and cited", atMs: t0 - 22 * min, kind: "read" },
  office: { title: "One board per issue", atMs: t0 - 41 * min, kind: "read" },
  release: { title: "Help Centre fields", atMs: t0 - 26 * 60 * min, kind: "read" },
};

/** Data for the hive and the brain drawer. New recalls keep arriving so the pulses are lively. */
function hiveMock(args?: Record<string, unknown>): Record<string, unknown> {
  const since = Number(args?.since ?? 0);
  const fresh = since > Date.now() - 60_000;
  const live = fresh && Math.random() < 0.7
    ? [0, 1].slice(0, 1 + Math.floor(Math.random() * 2)).map(() => {
        const [key, label] = LIVE_TEAMS[Math.floor(Math.random() * LIVE_TEAMS.length)];
        const write = Math.random() < 0.2;
        return { atMs: Date.now(), kind: write ? "write" : "read", title: write ? "New note" : "Ledger panel", file: "/mock/memory/x.md", team: { key, label }, who: "" };
      })
    : [];
  const q = String(args?.query ?? "").toLowerCase();
  return {
    brain_overview: {
      total: 1108, recalledToday: 42, writtenToday: 9, vaultNotes: 63, skills: 102, roles: 17, claudeMd: 6, squads: 3, connectors: 12,
      kinds: [{ kind: "reference", count: 582 }, { kind: "project", count: 284 }, { kind: "feedback", count: 211 }, { kind: "bug", count: 25 }, { kind: "other", count: 6 }],
      lastByTeam: LAST_BY_TEAM,
    },
    brain_memories: MEM_ROWS.filter((m) => !q || m.name.toLowerCase().includes(q) || m.description.toLowerCase().includes(q)),
    brain_memory: { name: "Competitor fees are verified and cited", kind: "feedback", description: "", body: "## Rule\n\nAny competitor fee or pricing claim is **re-checked** on their own page the day it is written, and cited.\n\n- Fetch the live page, not a cached one\n- Quote the fee exactly\n- Add the URL to the draft\n\n**Why:** a wrong competitor number is the fastest way to lose a promoter's trust." },
    brain_recalls: fresh ? live : RECALL_HISTORY,
    brain_skills: {
      skills: ["project-management", "seo-dataforseo", "branded-deck", "remotion", "customer-success", "weekly-report", "nano-banana-pro", "build"].map((n) => ({ name: n, description: `The ${n} playbook the teams lean on.` })),
      roles: ["growth-director", "growth-seo", "growth-writer", "growth-editor", "growth-designer", "office-chief", "office-pm", "release-lead", "release-faq", "release-video", "studio-designer", "bob", "bug-hunter", "mark-planner", "mark-reviewer"],
      claudeMd: 6, squads: 3,
    },
    brain_connected: { local: ["astrology", "lightpanda", "tavily", "eva-core"], claudeAi: ["Gmail", "Google Calendar", "Notion", "Google Drive", "Claude Docs", "Slack", "eventflo"] },
    brain_now: {
      sessionId: "25f51e0e-2254-4c12-b639-d393282ba59b", sessionDate: new Date(t0).toISOString().slice(0, 10), sessionModifiedMs: t0 - 12 * min,
      journal: { name: new Date(t0).toISOString().slice(0, 10), text: "# Walk journal\n\n- 07:12 Mark asked what was running; four agents, none blocked.\n- 07:40 Dispatched a worker for the board sweep.\n- 08:05 Board sweep finished, 7 cards moved." },
      ledgerDone: 14, ledgerCalls: 5, ledgerWaiting: 2,
    },
  };
}


/* ---- inbox ---- */
function svgImg(a: string, b: string, label: string): string {
  const svg = `<svg xmlns='http://www.w3.org/2000/svg' width='960' height='540'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='${a}'/><stop offset='1' stop-color='${b}'/></linearGradient></defs><rect width='960' height='540' fill='url(%23g)'/><circle cx='700' cy='170' r='90' fill='rgba(255,255,255,0.18)'/><text x='60' y='470' font-family='sans-serif' font-size='44' fill='white'>${label}</text></svg>`;
  return `data:image/svg+xml;utf8,${svg.replace(/#/g, "%23")}`;
}
const PAYLOADS: Record<string, unknown> = {
  "/mock/inbox/growth/out/how-to-sell-out-your-first-gig.json": {
    title: "How to sell out your first gig", slug: "how-to-sell-out-your-first-gig",
    excerpt: "Most first-time promoters price too late and promote too early. Here is the order that works.",
    body: "## Start with the room\n\nPick a venue **40% smaller** than the crowd you hope for. A full small room beats an empty big one every time.\n\n## Price in three waves\n\n1. Early bird for your own followers\n2. General release two weeks out\n3. A final-week release you only announce once\n\nSee the [pricing guide](https://example.com/pricing) for the maths.\n\n| Wave | Share of tickets | When |\n|---|---|---|\n| Early bird | 20% | 8 weeks out |\n| General | 60% | 4 weeks out |\n| Final | 20% | last week |",
    tags: ["promoters", "ticketing", "first event"],
    faq: [{ question: "How early should I put tickets on sale?", answer: "Eight weeks out is a good default for a club night." }, { question: "What if the early bird sells slowly?", answer: "Bring the general release forward rather than discounting." }],
  },
  "/mock/inbox/growth/out/resale-without-the-headache.json": {
    title: "Resale without the headache", slug: "resale-without-the-headache",
    excerpt: "Fans will resell. Give them a safe way to do it and you keep the relationship.",
    body: "Resale is going to happen whether you plan for it or not.\n\n- Cap the price at face value\n- Let the buyer see the seller is verified\n- Pay the organiser a fee on every resale\n\nThat is the whole idea.",
    tags: ["resale", "fans"], faq: [],
  },
};
const FILE_TEXT: Record<string, string> = {
  "/mock/inbox/office/out/board-cleanup.md": "## Board cleanup\n\nI moved **7** double-listed cards and closed 3 stale ones.\n\n| Board | Moved | Closed |\n|---|---|---|\n| v3.2 release | 5 | 2 |\n| Bug tracker | 2 | 1 |\n\n### Proposals for you\n\n- Close the five cards older than 90 days\n- Nudge Syed about two merged fixes still in triage",
};
const IMAGES: Record<string, string> = {
  "/mock/inbox/growth/out/how-to-sell-out-your-first-gig-cover.png": svgImg("#2c4a74", "#7cc4ff", "Sell out your first gig"),
  "/mock/inbox/growth/out/resale-without-the-headache-cover.png": svgImg("#3a2c74", "#b39cff", "Resale without the headache"),
};
const iso = (ago: number) => new Date(t0 - ago * min).toISOString();
let INBOX: Record<string, unknown>[] = [
  {
    version: 1, id: "growth-week-of-posts", created_at: iso(14), source: "squad", squad: "growth", job: "2026-10-13-week-of-posts",
    title: "Growth: week of posts", director: "growth-director", state: "new", note: null, decided_at: null, desk: "/mock/inbox/growth",
    summary_md: "## Two drafts are ready\n\nThe editor passed both and every competitor claim was re-checked on the day.\n\n- **How to sell out your first gig**: fan-side search term first\n- **Resale without the headache**: links to the help article\n\nCovers are 16:9, no text in the image. See the [brief](https://example.com/brief).",
    deliverables: [
      { path: "/mock/inbox/growth/out/how-to-sell-out-your-first-gig.json", name: "how-to-sell-out-your-first-gig.json", kind: "json", bytes: 5120 },
      { path: "/mock/inbox/growth/out/how-to-sell-out-your-first-gig-cover.png", name: "how-to-sell-out-your-first-gig-cover.png", kind: "png", bytes: 48200 },
      { path: "/mock/inbox/growth/out/resale-without-the-headache.json", name: "resale-without-the-headache.json", kind: "json", bytes: 3100 },
      { path: "/mock/inbox/growth/out/resale-without-the-headache-cover.png", name: "resale-without-the-headache-cover.png", kind: "png", bytes: 51200 },
    ],
  },
  {
    version: 1, id: "office-board-cleanup", created_at: iso(62), source: "squad", squad: "office", job: "2026-10-13-board-sweep",
    title: "Office: board cleanup", director: "office-chief", state: "new", note: null, decided_at: null, desk: "/mock/inbox/office",
    summary_md: "The sweep finished. Everything is in the report below, with two proposals that need your yes.",
    deliverables: [{ path: "/mock/inbox/office/out/board-cleanup.md", name: "board-cleanup.md", kind: "md", bytes: 900 }],
  },
  {
    version: 1, id: "growth-covers", created_at: iso(30), source: "squad", squad: "growth", job: "2026-10-13-covers",
    title: "Growth: covers", director: "growth-director", state: "sent_back", note: "Warmer is fine, but lose the vans.", decided_at: iso(20), desk: "/mock/inbox/growth",
    summary_md: "# Blog covers, 13 October 2026\n\nBoth covers are done. Each image took one try. No post text was changed.\n\n- **Bush doof guide**: dusty campsite at golden hour, 16:9 (2752 x 1536), no text\n- **Resale**: a punter queues at dusk outside a brick venue",
    feedback: [{ at: iso(20), target: { path: "/mock/inbox/growth/out/how-to-sell-out-your-first-gig-cover.png", title: "Cover: How to sell out your first gig" }, note: "Warmer is fine, but lose the vans.", routed_to: "revision job", job: "2026-10-13-revise-covers" }],
    deliverables: [
      { path: "/mock/inbox/growth/out/how-to-sell-out-your-first-gig-cover.png", name: "how-to-sell-out-your-first-gig-cover.png", kind: "png", bytes: 7549747 },
      { path: "/mock/inbox/growth/out/resale-without-the-headache-cover.png", name: "resale-without-the-headache-cover.png", kind: "png", bytes: 5872025 },
    ],
  },
  {
    version: 1, id: "growth-revise-covers", created_at: iso(3), source: "squad", squad: "growth", job: "2026-10-13-revise-covers",
    title: "Growth: revise covers", director: "growth-director", state: "new", note: null, decided_at: null, desk: "/mock/inbox/growth",
    summary_md: "The bush doof cover is redone without the vans.", deliverables: [],
  },
  {
    version: 1, id: "release-faq-v31", created_at: iso(60 * 20), source: "squad", squad: "release", job: "2026-10-12-v31-faq",
    title: "Release: v3.1 Help Centre updates", director: "release-lead", state: "approved", note: null, decided_at: iso(60 * 19), desk: "/mock/inbox/release",
    summary_md: "Four articles updated, two new ones drafted.", deliverables: [],
  },
];
function inboxMock(cmd: string, args?: Record<string, unknown>): unknown {
  const id = String(args?.id ?? "");
  const patch = (fields: Record<string, unknown>) => {
    INBOX = INBOX.map((i) => (i.id === id ? { ...i, ...fields } : i));
    return INBOX.find((i) => i.id === id) ?? null;
  };
  switch (cmd) {
    case "inbox_list": {
      const rank = (s: unknown) => (s === "new" ? 0 : s === "archived" ? 2 : 1);
      return [...INBOX].sort((a, b) => rank(a.state) - rank(b.state));
    }
    case "inbox_decide": return patch({ state: args?.state, decided_at: new Date().toISOString() });
    case "inbox_restore": return patch({ state: args?.state, note: args?.note ?? null, decided_at: args?.decided_at ?? null });
    case "inbox_send_back": {
      const cur = INBOX.find((i) => i.id === id);
      const tgt = args?.target as { path: string | null; title: string } | null;
      const live = SQUAD && cur?.squad === "growth";
      const entry = { at: new Date().toISOString(), target: tgt, note: String(args?.note), routed_to: live ? "Marketing Director" : "revision job", job: live ? null : `${new Date().toISOString().slice(0, 10)}-revise-${String(cur?.job).slice(11)}` };
      patch({ state: "sent_back", note: args?.note, decided_at: entry.at, feedback: [...(((cur?.feedback) as unknown[]) ?? []), entry] });
      return { how: live ? "asked" : "started", detail: "", routed_to: entry.routed_to, job: entry.job };
    }
    case "inbox_read_file": {
      const p = String(args?.path);
      return p in PAYLOADS ? JSON.stringify(PAYLOADS[p]) : FILE_TEXT[p] ?? "";
    }
    case "inbox_image": return IMAGES[String(args?.path)] ?? svgImg("#2c4a74", "#7cc4ff", "image");
    default: return undefined;
  }
}

export function mockCall<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const inboxHit = inboxMock(cmd, args);
  if (inboxHit !== undefined) return Promise.resolve(inboxHit as T);
  const table: Record<string, unknown> = {
    ...hiveMock(args),
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
