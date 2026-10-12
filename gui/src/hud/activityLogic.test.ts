import assert from "node:assert/strict";
import { test } from "node:test";
import { applyDrafts, diffFleet, FLAP_MS, subjectOf, type ActivityItem, type Draft } from "./activityLogic";
import type { Fleet, FleetNode } from "./types";

function node(over: Partial<FleetNode>): FleetNode {
  return {
    paneId: "p1", agent: "claude", status: "working", title: "Admin panel", repo: "r", cwd: "", session: null,
    sinceMs: 0, subagents: [], squad: null, job: null, role: null, roleTitle: null, parent: null, ...over,
  };
}
const fleet = (...nodes: FleetNode[]): Fleet => ({ nodes, herdrOk: true, error: null });
let id = 0;
const nextId = () => ++id;
const d = (key: string, kind: Draft["kind"], at: number, what = kind === "start" ? "started" : "finished"): Draft => ({
  key, kind, at, tone: "work", subject: key, what,
});

test("squad members are named by role and squad", () => {
  assert.equal(subjectOf(node({ squad: "growth", roleTitle: "Writer", title: "growth-writer-1" })), "Writer, Growth");
  assert.equal(subjectOf(node({ title: "Admin panel" })), "Admin panel");
});

test("diff only reports started, finished, needs you and closed", () => {
  const a = fleet(node({ status: "idle" }));
  assert.deepEqual(diffFleet(a, fleet(node({ status: "idle", title: "x" })), 1), []);
  assert.deepEqual(diffFleet(a, fleet(node({ status: "working" })), 1).map((x) => x.what), ["started"]);
  assert.deepEqual(diffFleet(fleet(node({ status: "working" })), fleet(node({ status: "idle" })), 1).map((x) => x.what), ["finished"]);
  assert.deepEqual(diffFleet(fleet(), fleet(node({ status: "idle" })), 1), [], "a new idle pane is not news");
  assert.deepEqual(diffFleet(fleet(), fleet(node({ status: "working" })), 1).map((x) => x.what), ["started"]);
  assert.deepEqual(diffFleet(a, fleet(node({ status: "needs-you" })), 1).map((x) => x.what), ["needs you"]);
  assert.deepEqual(diffFleet(a, fleet(node({ status: "gone" })), 1).map((x) => x.what), ["was closed"]);
});

test("one line per agent, updated in place", () => {
  let items: ActivityItem[] = [];
  items = applyDrafts(items, [d("a", "start", 0), d("b", "start", 1)], nextId);
  items = applyDrafts(items, [d("a", "finish", 100_000)], nextId);
  assert.deepEqual(items.map((i) => [i.key, i.kind]), [["a", "finish"], ["b", "start"]]);
});

test("a quick finish then start flip restores the start line instead of adding lines", () => {
  let items: ActivityItem[] = [];
  items = applyDrafts(items, [d("a", "start", 0)], nextId);
  items = applyDrafts(items, [d("a", "finish", 5_000)], nextId);
  assert.equal(items[0].kind, "finish");
  items = applyDrafts(items, [d("a", "start", 5_000 + FLAP_MS - 1)], nextId);
  assert.deepEqual(items.map((i) => [i.key, i.kind, i.at]), [["a", "start", 0]]);
  // Flapping repeatedly never grows the feed.
  for (let t = 1; t <= 6; t++) {
    items = applyDrafts(items, [d("a", "finish", t * 10_000)], nextId);
    items = applyDrafts(items, [d("a", "start", t * 10_000 + 3_000)], nextId);
  }
  assert.equal(items.length, 1);
});

test("a finish that lasts past the window is real: starting again is a new line", () => {
  let items: ActivityItem[] = [];
  items = applyDrafts(items, [d("a", "start", 0), d("a", "finish", 1_000)], nextId);
  items = applyDrafts(items, [d("a", "start", 1_000 + FLAP_MS + 1)], nextId);
  assert.deepEqual(items.map((i) => i.kind), ["start"]);
  assert.equal(items[0].prev, null);
});

test("an identical repeat only refreshes the time, and the feed is capped", () => {
  let items: ActivityItem[] = [];
  items = applyDrafts(items, [d("a", "need", 1, "needs you")], nextId);
  items = applyDrafts(items, [d("a", "need", 9, "needs you")], nextId);
  assert.equal(items.length, 1);
  assert.equal(items[0].at, 9);
  const many = Array.from({ length: 40 }, (_, i) => d(`k${i}`, "start", i));
  assert.equal(applyDrafts([], many, nextId).length, 30);
});
