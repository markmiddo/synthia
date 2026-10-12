import type { ActivityItem } from "./activity";
import { clock } from "./format";

const TONE: Record<ActivityItem["tone"], string> = {
  work: "var(--blue)",
  need: "var(--amber)",
  done: "var(--slate)",
};

export function Feed({ items }: { items: ActivityItem[] }) {
  return (
    <aside className="feed" aria-label="Activity">
      <p className="lbl">ACTIVITY</p>
      {items.length === 0 ? (
        <p className="quiet-note">Quiet so far. Changes show up here as they happen.</p>
      ) : (
        <ol>
          {items.map((i) => (
            <li key={i.id} className="new" style={{ ["--c" as string]: TONE[i.tone] }}>
              <time>{clock(i.at)}</time>
              <b>{i.subject}</b> {i.what}
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}
