import type { BrainState } from "./brain";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** Local recording (Right Alt held) wins over what the brain is doing. */
export function orbState(recording: boolean, brain: BrainState): OrbState {
  if (recording) return "listening";
  if (brain === "thinking") return "thinking";
  if (brain === "speaking") return "speaking";
  return "idle";
}

const CAPTION: Record<OrbState, string> = {
  idle: "Ready · hold Right Alt",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking",
};

export function Orb({ state }: { state: OrbState }) {
  return (
    <div className="orb-block">
      <div className={`orb orb-${state}`} aria-hidden="true" />
      <div className="name" role="status">
        SYNTHIA
        <small>{CAPTION[state]}</small>
      </div>
    </div>
  );
}
