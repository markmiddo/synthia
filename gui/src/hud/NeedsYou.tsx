import type { ConfirmAsk } from "./brain";
import { formatSince } from "./format";
import type { FleetNode } from "./types";

interface Props {
  nodes: FleetNode[];
  confirms: ConfirmAsk[];
  now: number;
  onFocus: (paneId: string) => void;
  onConfirm: (id: string, yes: boolean) => void;
}

export function NeedsYou({ nodes, confirms, now, onFocus, onConfirm }: Props) {
  const waiting = nodes.filter((n) => n.status === "needs-you");
  if (waiting.length === 0 && confirms.length === 0) return null;
  return (
    <section aria-label="Needs you">
      <h3>Needs you</h3>
      {confirms.map((c) => (
        <div className="need" key={c.id}>
          <b>Asking before it acts</b>
          {c.question}
          <div className="need-actions">
            <button type="button" onClick={() => onConfirm(c.id, true)}>
              Yes, go ahead
            </button>
            <button type="button" className="quiet" onClick={() => onConfirm(c.id, false)}>
              No
            </button>
          </div>
        </div>
      ))}
      {waiting.map((n) => (
        <button type="button" className="need need-button" key={n.paneId} onClick={() => onFocus(n.paneId)}>
          <b>{n.title}</b>
          {n.repo} · waiting {formatSince(n.sinceMs, now)}
        </button>
      ))}
    </section>
  );
}
