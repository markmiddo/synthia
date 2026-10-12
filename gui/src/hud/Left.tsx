import type { BrainView, ConfirmAsk } from "./brain";
import { formatSince } from "./format";
import type { FleetNode } from "./types";

/** Her current or last line, written as it arrives; a caret while she is still speaking. */
export function Spoken({
  spoken,
  link,
  talkKey,
}: {
  spoken: BrainView["spoken"];
  link: BrainView["link"];
  talkKey: string;
}) {
  const text = spoken.text || (link === "online" ? `Hold ${talkKey} and ask me what's going on.` : "");
  return (
    <p className="says" aria-live="polite">
      {text}
      {spoken.live && <span className="caret" aria-hidden="true" />}
    </p>
  );
}

export function NeedsYou({
  nodes,
  confirms,
  now,
  onFocus,
  onConfirm,
}: {
  nodes: FleetNode[];
  confirms: ConfirmAsk[];
  now: number;
  onFocus: (paneId: string) => void;
  onConfirm: (id: string, yes: boolean) => void;
}) {
  const waiting = nodes.filter((n) => n.status === "needs-you");
  return (
    <section aria-label="Needs you">
      <p className="lbl">NEEDS YOU</p>
      {waiting.length === 0 && confirms.length === 0 && (
        <div className="allclear">
          <i />
          Nothing is waiting on you.
        </div>
      )}
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
