import assert from "node:assert/strict";
import { test } from "node:test";
import { callsMade, groupOf, isReport, needsMark, pillLabel, questionsOf, unanswered, withoutSection, type LogicItem } from "./inboxLogic";

const SUMMARY = `# Board sweep

Done.

## Calls I made

- Closed 3 stale cards: they were merged weeks ago. Undo: reopen from the archive.
- **Moved** 7 double-listed cards: one board per issue. Undo: move back.

## Needs you

- Enable the weekday 7:30 sweep?
- Nudge Syed about the two merged fixes?

## Notes

- not a call
`;

const item = (over: Partial<LogicItem>): LogicItem => ({ id: "x", state: "new", review: "fyi", summary_md: "A report.", feedback: [], ...over });

test("bullets are read from the named section only", () => {
  assert.deepEqual(callsMade(SUMMARY), [
    "Closed 3 stale cards: they were merged weeks ago. Undo: reopen from the archive.",
    "Moved 7 double-listed cards: one board per issue. Undo: move back.",
  ]);
  assert.deepEqual(questionsOf(SUMMARY), ["Enable the weekday 7:30 sweep?", "Nudge Syed about the two merged fixes?"]);
  assert.deepEqual(callsMade("no sections here"), []);
  assert.deepEqual(callsMade("## calls i made\n1. numbered\n* starred"), ["numbered", "starred"]);
});

test("a section can be cut out of the summary", () => {
  const rest = withoutSection(SUMMARY, "Needs you");
  assert.ok(!rest.includes("Enable the weekday"));
  assert.ok(rest.includes("Closed 3 stale cards"));
  assert.ok(rest.includes("## Notes"));
});

test("review-required items need Mark while new; reports do not", () => {
  assert.equal(needsMark(item({ review: "required" })), true);
  assert.equal(needsMark(item({ review: "required", state: "approved" })), false);
  assert.equal(needsMark(item({ review: "required", state: "sent_back" })), false);
  assert.equal(needsMark(item({ review: "fyi" })), false);
  assert.equal(needsMark(item({ review: undefined })), false, "a missing value counts as fyi");
  assert.equal(isReport(item({})), true);
  assert.equal(isReport(item({ review: "required" })), false);
});

test("a report with open questions needs Mark until every question is answered", () => {
  const withQs = item({ summary_md: SUMMARY });
  assert.equal(needsMark(withQs), true);
  assert.equal(unanswered(withQs).length, 2);
  assert.equal(groupOf(withQs), "needs");
  assert.equal(pillLabel(withQs), "Needs you");
  const half = item({ summary_md: SUMMARY, feedback: [{ at: "t", kind: "answer", answer: "yes", note: "", target: { path: null, title: "Enable the weekday 7:30 sweep?" } }] });
  assert.equal(unanswered(half).length, 1);
  assert.equal(needsMark(half), true);
  const done = item({
    summary_md: SUMMARY,
    feedback: [
      { at: "t", kind: "answer", answer: "yes", note: "", target: { path: null, title: "Enable the weekday 7:30 sweep?" } },
      { at: "t", kind: "answer", answer: "no", note: "later", target: { path: null, title: "Nudge Syed about the two merged fixes?" } },
    ],
  });
  assert.equal(needsMark(done), false);
  assert.equal(groupOf(done), "reports");
  assert.equal(pillLabel(done), "Report");
  // Ordinary feedback on a question's text is not an answer.
  const notAnswer = item({ summary_md: SUMMARY, feedback: [{ at: "t", note: "x", target: { path: null, title: "Enable the weekday 7:30 sweep?" } }] });
  assert.equal(unanswered(notAnswer).length, 2);
});

test("groups and pills", () => {
  assert.equal(groupOf(item({ review: "required" })), "needs");
  assert.equal(pillLabel(item({ review: "required" })), "Needs your review");
  assert.equal(groupOf(item({})), "reports");
  assert.equal(groupOf(item({ state: "approved", review: "required" })), "decided");
  assert.equal(groupOf(item({ state: "archived" })), "decided");
  assert.equal(pillLabel(item({ state: "sent_back" })), "Sent back");
});
