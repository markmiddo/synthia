import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTerminalSession, type SessionMeta } from "./useTerminalSession";

interface TerminalViewProps {
  cwd?: string;
  shell?: string;
  initialCommand?: string;
  visible: boolean;
  onMeta?: (meta: SessionMeta) => void;
  onExit?: (code: number) => void;
}

export function TerminalView(props: TerminalViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const session = useTerminalSession({
    containerRef,
    cwd: props.cwd,
    shell: props.shell,
    initialCommand: props.initialCommand,
    onExit: props.onExit,
  });

  useEffect(() => {
    if (session.meta) props.onMeta?.(session.meta);
  }, [session.meta, props]);

  useEffect(() => {
    if (props.visible) {
      // Multiple deferred fits cover slow layout settling on Linux/COSMIC.
      // rAF fires after the first paint; the timeouts catch cases where the
      // parent flex container finalises its width slightly later.
      const rafId = requestAnimationFrame(() => { session.fit(); session.focus(); });
      const t1 = window.setTimeout(() => session.fit(), 50);
      const t2 = window.setTimeout(() => session.fit(), 200);
      const t3 = window.setTimeout(() => session.fit(), 500);
      return () => {
        cancelAnimationFrame(rafId);
        window.clearTimeout(t1);
        window.clearTimeout(t2);
        window.clearTimeout(t3);
      };
    }
  }, [props.visible, session]);

  // Fix 2: File drag-and-drop via Tauri's OS-level DragDrop window event.
  // HTML5 onDrop/onDragOver handlers don't fire in Tauri webviews because
  // Tauri intercepts file drops at the OS level before they reach the DOM.
  // We listen to the Tauri events emitted from lib.rs on_window_event instead.
  useEffect(() => {
    if (!props.visible) return;
    let unlistenDrop: (() => void) | undefined;
    let unlistenEnter: (() => void) | undefined;
    let unlistenLeave: (() => void) | undefined;

    listen<string[]>("synthia://file-drop", (event) => {
      setDragOver(false);
      if (!session.sessionId) return;
      const quoted = event.payload
        .map((p) => `'${p.replace(/'/g, "'\\''")}'`)
        .join(" ");
      invoke("terminal_write", { sessionId: session.sessionId, data: quoted }).catch((err) =>
        console.error("[terminal] drop write failed", err),
      );
    }).then((u) => { unlistenDrop = u; });

    listen<void>("synthia://drag-enter", () => {
      setDragOver(true);
    }).then((u) => { unlistenEnter = u; });

    listen<void>("synthia://drag-leave", () => {
      setDragOver(false);
    }).then((u) => { unlistenLeave = u; });

    return () => {
      unlistenDrop?.();
      unlistenEnter?.();
      unlistenLeave?.();
    };
  }, [props.visible, session.sessionId]);

  return (
    <div
      className={`terminal-view-container${dragOver ? " drag-over" : ""}`}
      style={{ display: props.visible ? "block" : "none" }}
    >
      <div ref={containerRef} className="terminal-view" />
      {session.error && (
        <div className="terminal-exit-banner">Error: {session.error}</div>
      )}
      {session.exitCode !== null && (
        <div className="terminal-exit-banner">
          Process exited (code {session.exitCode}) · press Enter or close tab
        </div>
      )}
    </div>
  );
}
