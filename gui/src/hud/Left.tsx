import { useEffect, useRef, useState } from "react";
import type { BrainView, ConfirmAsk } from "./brain";
import { formatSince } from "./format";
import type { FleetNode } from "./types";

/** The most characters that fit on two lines of subtitle in the left column. */
const MAX_CHARS = 46;

/** Split a reply into subtitle lines: sentences, with long ones broken at word edges. */
export function sentences(text: string): string[] {
  const out: string[] = [];
  for (const sentence of text.split(/(?<=[.!?])\s+/)) {
    let line = "";
    for (const word of sentence.split(/\s+/).filter(Boolean)) {
      if (line && line.length + 1 + word.length > MAX_CHARS) {
        out.push(line);
        line = word;
      } else {
        line = line ? `${line} ${word}` : word;
      }
    }
    if (line) out.push(line);
  }
  return out;
}

/** About how long a sentence takes to say out loud, at roughly 2.6 words a second. */
export function speakMs(sentence: string): number {
  const words = sentence.split(/\s+/).filter(Boolean).length;
  return Math.max(1600, (words / 2.6) * 1000);
}

/** Linger on the last line after it is done, then fade to nothing. */
const LINGER_MS = 2200;

/**
 * Subtitles: only the sentence being spoken right now, centred under the orb. There is no
 * progress signal from the voice app, so each sentence is held for about as long as it
 * takes to say, then the next one replaces it.
 */
export function Spoken({ spoken }: { spoken: BrainView["spoken"] }) {
  const parts = sentences(spoken.text);
  const [idx, setIdx] = useState(0);
  const [hidden, setHidden] = useState(true);
  const firstRef = useRef("");

  // A new reply starts over from its first sentence.
  const first = parts[0] ?? "";
  useEffect(() => {
    if (first !== firstRef.current) {
      firstRef.current = first;
      setIdx(0);
      setHidden(first === "");
    }
  }, [first]);

  const current = parts[Math.min(idx, parts.length - 1)] ?? "";
  const hasNext = idx < parts.length - 1;
  const done = !spoken.live;
  useEffect(() => {
    if (!current) return;
    // The last sentence of a finished reply fades away once it has been said.
    if (!hasNext && !done) return;
    const t = setTimeout(
      () => (hasNext ? setIdx(idx + 1) : setHidden(true)),
      speakMs(current) + (hasNext ? 0 : LINGER_MS),
    );
    return () => clearTimeout(t);
  }, [current, idx, hasNext, done]);

  const show = !hidden && current !== "";
  return (
    <p className={`says${show ? " on" : ""}`} aria-live="polite">
      <span key={current}>{show ? current : ""}</span>
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
