/** Pure rules for the Inbox: no React, no Tauri, so they can be tested on their own. */

export interface LogicFeedback {
  at: string;
  target: { path: string | null; title: string } | null;
  note: string;
  kind?: string | null;
  answer?: string | null;
}

export interface LogicItem {
  id: string;
  state: string;
  review?: string | null;
  summary_md: string;
  feedback?: LogicFeedback[];
}

/** The bullets under a `## <heading>` section of a summary. */
export function sectionBullets(md: string, heading: string): string[] {
  const out: string[] = [];
  let inSection = false;
  for (const raw of md.replace(/\r/g, "").split("\n")) {
    const h = /^#{1,4}\s+(.*?)\s*$/.exec(raw);
    if (h) {
      inSection = h[1].toLowerCase() === heading.toLowerCase();
      continue;
    }
    if (!inSection) continue;
    const b = /^\s*(?:[-*]|\d+[.)])\s+(.*\S)\s*$/.exec(raw);
    if (b) out.push(b[1].replace(/\*\*/g, ""));
  }
  return out;
}

/** The summary without one section, so a section shown elsewhere is not shown twice. */
export function withoutSection(md: string, heading: string): string {
  const out: string[] = [];
  let skipping = false;
  for (const raw of md.replace(/\r/g, "").split("\n")) {
    const h = /^#{1,4}\s+(.*?)\s*$/.exec(raw);
    if (h) skipping = h[1].toLowerCase() === heading.toLowerCase();
    if (!skipping) out.push(raw);
  }
  return out.join("\n");
}

export const callsMade = (md: string): string[] => sectionBullets(md, "Calls I made");
export const questionsOf = (md: string): string[] => sectionBullets(md, "Needs you");

export function answerOf(item: LogicItem, question: string): LogicFeedback | null {
  return (item.feedback ?? []).find((f) => f.kind === "answer" && f.target?.title === question) ?? null;
}

export function unanswered(item: LogicItem): string[] {
  return questionsOf(item.summary_md).filter((q) => answerOf(item, q) === null);
}

export const isRequired = (item: LogicItem): boolean => item.review === "required";

/** Does this item need Mark? A review-required item still new, or a report with open questions. */
export function needsMark(item: LogicItem): boolean {
  if (item.state === "archived") return false;
  if (isRequired(item)) return item.state === "new";
  return unanswered(item).length > 0;
}

/** A plain report: nothing to decide, nothing to answer, not yet put away. */
export function isReport(item: LogicItem): boolean {
  return !isRequired(item) && item.state === "new" && unanswered(item).length === 0;
}

export type Group = "needs" | "reports" | "decided";

export function groupOf(item: LogicItem): Group {
  if (needsMark(item)) return "needs";
  if (isReport(item)) return "reports";
  return "decided";
}

export function pillLabel(item: LogicItem): string {
  if (item.state === "approved") return "Approved";
  if (item.state === "sent_back") return "Sent back";
  if (item.state === "archived") return "Archived";
  if (isRequired(item)) return "Needs your review";
  return unanswered(item).length > 0 ? "Needs you" : "Report";
}
