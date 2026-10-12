import type { BrainView } from "./brain";
import type { Fleet } from "./types";

interface Props {
  brain: BrainView;
  fleet: Fleet | null;
  voiceRunning: boolean | null;
  onStartVoice: () => void;
  talkKey: string;
  /** Other problems already phrased for the user (focus failed, voice app unreadable...). */
  notes?: string[];
}

/** One plain-words line per problem; renders nothing when everything is reachable. */
export function Connection({
  brain,
  fleet,
  voiceRunning,
  onStartVoice,
  talkKey,
  notes = [],
}: Props) {
  const lines: string[] = [];
  if (brain.link === "offline" && brain.reason) lines.push(brain.reason);
  if (brain.notice) lines.push(brain.notice);
  lines.push(...notes);
  if (fleet && !fleet.herdrOk) lines.push(`I can't see your agents. ${fleet.error ?? ""}`.trim());
  const voiceDown = voiceRunning === false;
  if (lines.length === 0 && !voiceDown) return null;
  return (
    <div className="conn" role="status">
      {lines.map((l) => (
        <p key={l}>{l}</p>
      ))}
      {voiceDown && (
        <p>
          The voice app isn't running, so {talkKey} won't work.{" "}
          <button type="button" className="link" onClick={onStartVoice}>
            Start it
          </button>
        </p>
      )}
    </div>
  );
}
