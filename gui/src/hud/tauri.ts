import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { mockCall, mockListen } from "./mock";

/** Browser-only preview with fake data: `npm run dev`, then open /?mock. Never in a build. */
export const MOCK: boolean = import.meta.env.DEV && window.location.search.includes("mock");

export function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (MOCK) return mockCall<T>(cmd, args);
  return invoke<T>(cmd, args);
}

/** A short plain-words reason from whatever a failed Tauri call rejected with. */
export function reasonOf(e: unknown): string {
  if (typeof e === "string") return e;
  if (e && typeof e === "object" && "message" in e) return String((e as { message: unknown }).message);
  return "unknown error";
}

/** Subscribe to a Tauri event; returns an unsubscribe function. */
export function on<T>(event: string, handler: (payload: T) => void): () => void {
  if (MOCK) return mockListen<T>(event, handler);
  let off: (() => void) | null = null;
  let cancelled = false;
  listen<T>(event, (e) => handler(e.payload)).then((fn) => {
    if (cancelled) fn();
    else off = fn;
  });
  return () => {
    cancelled = true;
    off?.();
  };
}
