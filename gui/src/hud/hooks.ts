import { useEffect, useState } from "react";
import { call, on, reasonOf } from "./tauri";
import type { Fleet, SynthiaState, UsageStats } from "./types";

/** Re-render every `ms` so "52m" keeps counting without any new data. */
export function useNow(ms = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(t);
  }, [ms]);
  return now;
}

/** Live fleet: one snapshot on mount, then the backend's `fleet` events (sent only on change). */
export function useFleet(): Fleet | null {
  const [fleet, setFleet] = useState<Fleet | null>(null);
  useEffect(() => {
    let alive = true;
    call<Fleet>("fleet_snapshot")
      .then((f) => alive && setFleet((cur) => cur ?? f))
      .catch((e) =>
        alive &&
        setFleet((cur) => cur ?? { nodes: [], herdrOk: false, error: reasonOf(e) }),
      );
    const off = on<Fleet>("fleet", (f) => alive && setFleet(f));
    return () => {
      alive = false;
      off();
    };
  }, []);
  return fleet;
}

export function useUsage(): UsageStats | null {
  const [usage, setUsage] = useState<UsageStats | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<UsageStats>("get_usage_stats")
        .then((u) => alive && setUsage(u))
        // An error entry renders as "Claude usage unavailable".
        .catch((e) =>
          alive &&
          setUsage({ five_hour_pct: 0, five_hour_resets_in: "", seven_day_pct: 0, error: reasonOf(e) }),
        );
    load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  return usage;
}

/** The voice process's own state (recording, thinking...), written by the Python app. */
export function useSynthiaState(): { state: SynthiaState; error: string | null } {
  const [state, setState] = useState<SynthiaState>({ status: "ready", recording: false });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    call<SynthiaState>("get_synthia_state")
      .then((s) => alive && s && setState(s))
      .catch((e) => alive && setError(reasonOf(e)));
    const off = on<SynthiaState>("synthia-state", (s) => {
      if (!alive) return;
      setState(s);
      setError(null);
    });
    return () => {
      alive = false;
      off();
    };
  }, []);
  return { state, error };
}

/** Whether the voice app (the talk key) is running. */
export function useVoiceRunning(): {
  running: boolean | null;
  start: () => void;
  error: string | null;
} {
  const [running, setRunning] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<string>("get_status")
        .then((s) => {
          if (!alive) return;
          setRunning(s === "running");
          setError(null);
        })
        .catch((e) => {
          if (!alive) return;
          setRunning(null);
          setError(`I can't tell whether the voice app is running: ${reasonOf(e)}`);
        });
    load();
    const t = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const start = () => {
    call("start_synthia")
      .then(() => {
        setRunning(true);
        setError(null);
      })
      .catch((e) => {
        setRunning(false);
        setError(`I couldn't start the voice app: ${reasonOf(e)}`);
      });
  };
  return { running, start, error };
}

const KEY_NAMES: Record<string, string> = {
  "Key.alt_l": "Left Alt",
  "Key.alt_r": "Right Alt",
  "Key.ctrl_l": "Left Ctrl",
  "Key.ctrl_r": "Right Ctrl",
  "Key.shift_l": "Left Shift",
  "Key.shift_r": "Right Shift",
};

/**
 * The talk key in words ("Left Alt"). With Murmur hearing the key, the voice app reports
 * Murmur's own label in its state file; otherwise it is the key from Synthia's config.
 */
export function useTalkKey(voice: SynthiaState): string {
  const [configured, setConfigured] = useState("your talk key");
  useEffect(() => {
    call<[string, string]>("get_hotkeys")
      .then(([, assistant]) => setConfigured(KEY_NAMES[assistant] ?? assistant))
      .catch(() => undefined); // keep the neutral wording; nothing else depends on it
  }, []);
  return talkKeyLabel(voice, configured);
}

export const NO_MURMUR_KEY_LINE = "Set an assistant key in Murmur's settings so I can hear you.";

/** Pure choice of label: Murmur's when it hears the key (unknown stays neutral). */
export function talkKeyLabel(voice: SynthiaState, configured: string): string {
  if (voice.stt_source !== "murmur") return configured;
  return voice.talk_key || "your talk key";
}

/** Murmur is the ear but has no assistant key, so nothing can start a question. */
export function murmurKeyMissing(voice: SynthiaState): boolean {
  return voice.stt_source === "murmur" && voice.talk_key === "";
}
