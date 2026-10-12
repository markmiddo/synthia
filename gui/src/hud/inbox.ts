import { useCallback, useEffect, useState } from "react";
import { call } from "./tauri";

export interface InboxFile {
  path: string;
  name: string;
  kind: "json" | "md" | "png" | "jpg" | "pdf" | "mp4" | "other";
  bytes: number;
}

export type InboxState = "new" | "approved" | "sent_back" | "archived";

/** One finished piece of work. Python writes everything except `state`, `note` and `decided_at`. */
export interface InboxItem {
  id: string;
  created_at: string;
  source: "squad" | "job" | string;
  squad: string;
  job: string;
  title: string;
  summary_md: string;
  desk: string;
  deliverables: InboxFile[];
  director: string;
  state: InboxState;
  note: string | null;
  decided_at: string | null;
}

const POLL_MS = 5000;

/** The inbox, refreshed every five seconds and straight away when the brain pushes an `inbox` frame. */
export function useInbox(tick: number): { items: InboxItem[]; reload: () => void } {
  const [items, setItems] = useState<InboxItem[]>([]);
  const reload = useCallback(() => {
    call<InboxItem[]>("inbox_list", { state: null })
      .then((v) => setItems(Array.isArray(v) ? v : []))
      .catch(() => {});
  }, []);
  useEffect(() => {
    reload();
    const t = setInterval(reload, POLL_MS);
    return () => clearInterval(t);
  }, [reload]);
  useEffect(() => {
    if (tick > 0) reload();
  }, [tick, reload]);
  return { items, reload };
}

export const newItems = (items: InboxItem[]): InboxItem[] => items.filter((i) => i.state === "new");

export function itemTime(i: InboxItem): number {
  const t = Date.parse(i.created_at);
  return Number.isNaN(t) ? Date.now() : t;
}

export function squadLabel(i: InboxItem): string {
  const s = i.squad || (i.source === "job" ? "Brain" : "");
  return s ? s[0].toUpperCase() + s.slice(1) : "Job";
}

export const STATE_LABEL: Record<InboxState, string> = {
  new: "New",
  approved: "Approved",
  sent_back: "Sent back",
  archived: "Archived",
};

/** A blog.Payload: the JSON a Growth post is delivered as. */
export interface Payload {
  title: string;
  slug: string;
  excerpt: string;
  body: string;
  tags: string[];
  faq: { q: string; a: string }[];
}

export function asPayload(text: string): Payload | null {
  let v: unknown;
  try {
    v = JSON.parse(text);
  } catch {
    return null;
  }
  if (!v || typeof v !== "object") return null;
  const o = v as Record<string, unknown>;
  if (typeof o.title !== "string" || typeof o.slug !== "string" || typeof o.excerpt !== "string" || typeof o.body !== "string") return null;
  const faq = Array.isArray(o.faq)
    ? o.faq
        .map((f) => {
          const r = (f ?? {}) as Record<string, unknown>;
          return { q: String(r.question ?? r.q ?? ""), a: String(r.answer ?? r.a ?? "") };
        })
        .filter((f) => f.q)
    : [];
  const tags = Array.isArray(o.tags) ? o.tags.map(String) : [];
  return { title: o.title, slug: o.slug, excerpt: o.excerpt, body: o.body, tags, faq };
}

/** The cover for a post: a png or jpg delivered with the same slug in its name. */
export function coverFor(slug: string, files: InboxFile[]): InboxFile | null {
  const s = slug.toLowerCase();
  return files.find((f) => (f.kind === "png" || f.kind === "jpg") && f.name.toLowerCase().includes(s)) ?? null;
}
