import { useEffect, useState } from "react";
import { call, on } from "./tauri";
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
      .catch(() =>
        alive &&
        setFleet((cur) => cur ?? { nodes: [], herdrOk: false, error: "I can't read herdr." }),
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
        .catch(() => alive && setUsage(null));
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
export function useSynthiaState(): SynthiaState {
  const [state, setState] = useState<SynthiaState>({ status: "ready", recording: false });
  useEffect(() => {
    let alive = true;
    call<SynthiaState>("get_synthia_state")
      .then((s) => alive && s && setState(s))
      .catch(() => {});
    const off = on<SynthiaState>("synthia-state", (s) => alive && setState(s));
    return () => {
      alive = false;
      off();
    };
  }, []);
  return state;
}

/** Whether the voice app (Right Alt / Right Ctrl) is running. */
export function useVoiceRunning(): { running: boolean | null; start: () => void } {
  const [running, setRunning] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () =>
      call<string>("get_status")
        .then((s) => alive && setRunning(s === "running"))
        .catch(() => alive && setRunning(null));
    load();
    const t = setInterval(load, 10_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);
  const start = () => {
    call("start_synthia")
      .then(() => setRunning(true))
      .catch(() => setRunning(false));
  };
  return { running, start };
}
