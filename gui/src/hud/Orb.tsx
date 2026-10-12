import type { BrainState } from "./brain";

export type OrbState = "idle" | "listening" | "thinking" | "speaking";

/** Local recording (talk key held) wins over what the brain is doing. */
export function orbState(recording: boolean, brain: BrainState): OrbState {
  if (recording) return "listening";
  if (brain === "thinking") return "thinking";
  if (brain === "speaking") return "speaking";
  return "idle";
}

const CAPTION: Record<OrbState, string> = {
  idle: "Ready",
  listening: "Listening…",
  thinking: "Thinking…",
  speaking: "Speaking",
};

export function Orb({ state, talkKey }: { state: OrbState; talkKey: string }) {
  return (
    <div className="orb-block">
      <div className={`orb orb-${state}`} aria-hidden="true" />
      <div className="name" role="status">
        SYNTHIA
        <small>{state === "idle" ? `Ready · hold ${talkKey}` : CAPTION[state]}</small>
      </div>
    </div>
  );
}
