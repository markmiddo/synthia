import { useCallback, useEffect, useReducer, useRef } from "react";
import { call, MOCK } from "./tauri";
import { startMockBrain } from "./mock";

export const DESK_URL = "ws://127.0.0.1:8766";
const CLOSE_UNAUTHORISED = 4401;

export type BrainState = "idle" | "thinking" | "speaking";
export type Link = "connecting" | "online" | "offline";

export interface ConfirmAsk {
  id: string;
  question: string;
}

export interface BrainView {
  link: Link;
  /** Plain-words reason shown when the link is down. */
  reason: string | null;
  state: BrainState;
  /** Her current or last line; `live` while it is still being written. */
  spoken: { text: string; live: boolean };
  confirms: ConfirmAsk[];
  /** A short problem the user should see (e.g. an answer that could not be sent). */
  notice: string | null;
}

export const INITIAL_VIEW: BrainView = {
  link: "connecting",
  reason: null,
  state: "idle",
  spoken: { text: "", live: false },
  confirms: [],
  notice: null,
};

export type Action =
  | { type: "connecting" }
  | { type: "offline"; reason: string }
  | { type: "notice"; text: string }
  | { type: "frame"; frame: Record<string, unknown> };

/** Pure: fold one message from the brain (or a link change) into the view. */
export function reduce(view: BrainView, action: Action): BrainView {
  switch (action.type) {
    case "connecting":
      return { ...view, link: "connecting" };
    case "offline":
      return { ...view, link: "offline", reason: action.reason, state: "idle", confirms: [], notice: null };
    case "notice":
      return { ...view, notice: action.text };
    case "frame": {
      const f = action.frame;
      const online: BrainView = { ...view, link: "online", reason: null, notice: null };
      switch (f.type) {
        case "state": {
          const value = f.value;
          if (value !== "idle" && value !== "thinking" && value !== "speaking") return online;
          return { ...online, state: value };
        }
        case "delta": {
          // The first delta of a new reply replaces the previous line.
          const base = view.spoken.live ? view.spoken.text : "";
          return { ...online, spoken: { text: base + String(f.text ?? ""), live: true } };
        }
        case "reply_done": {
          const text = String(f.text ?? "").trim() || view.spoken.text;
          return { ...online, spoken: { text, live: false } };
        }
        case "event":
          return { ...online, spoken: { text: String(f.text ?? ""), live: false } };
        case "error":
          return { ...online, spoken: { text: String(f.text ?? "Something went wrong."), live: false } };
        case "confirm": {
          const ask = { id: String(f.id), question: String(f.question ?? "") };
          return { ...online, confirms: [...view.confirms.filter((c) => c.id !== ask.id), ask] };
        }
        case "confirm_done":
          return { ...online, confirms: view.confirms.filter((c) => c.id !== f.id) };
        default:
          return online;
      }
    }
  }
}

export function useBrain(): { view: BrainView; confirmReply: (id: string, yes: boolean) => void } {
  const [view, dispatch] = useReducer(reduce, INITIAL_VIEW);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (MOCK) return startMockBrain((frame) => dispatch({ type: "frame", frame }));

    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const retry = () => {
      if (closed) return;
      const wait = Math.min(10_000, 1_000 * 2 ** attempt);
      attempt += 1;
      timer = setTimeout(connect, wait);
    };

    const connect = async () => {
      if (closed) return;
      dispatch({ type: "connecting" });
      let token: string;
      try {
        token = await call<string>("get_desk_token");
      } catch {
        dispatch({ type: "offline", reason: "My brain isn't running, so I can't answer yet." });
        retry();
        return;
      }
      if (closed) return;
      const ws = new WebSocket(DESK_URL);
      wsRef.current = ws;
      ws.onopen = () => ws.send(JSON.stringify({ type: "auth", token }));
      ws.onmessage = (ev) => {
        attempt = 0;
        try {
          const frame = JSON.parse(String(ev.data));
          if (frame && typeof frame === "object") dispatch({ type: "frame", frame });
        } catch {
          /* a malformed frame is dropped; the link stays up */
        }
      };
      ws.onclose = (ev) => {
        if (wsRef.current === ws) wsRef.current = null;
        if (closed) return;
        dispatch({
          type: "offline",
          reason:
            ev.code === CLOSE_UNAUTHORISED
              ? "My brain refused the key. Restart it and I'll reconnect."
              : "I can't reach my brain.",
        });
        retry();
      };
    };

    void connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      wsRef.current?.close();
    };
  }, []);

  const confirmReply = useCallback((id: string, yes: boolean) => {
    // The card goes away only when the brain says the question is closed (confirm_done),
    // so an answer that never left this window cannot look like it was given.
    const ws = wsRef.current;
    try {
      if (!ws || ws.readyState !== WebSocket.OPEN) throw new Error("not connected");
      ws.send(JSON.stringify({ type: "confirm_reply", id, yes }));
    } catch {
      dispatch({
        type: "notice",
        text: "I can't reach my brain, so I couldn't send your answer. The question stays until I'm back.",
      });
    }
  }, []);

  return { view, confirmReply };
}
