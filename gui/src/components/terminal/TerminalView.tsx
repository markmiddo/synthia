import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
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

  // Drag-and-drop: insert shell-quoted file paths at the cursor.
  // Note: standard browser File objects don't expose `.path`, but Tauri's
  // webview injects it. If `.path` is undefined we fall back to `f.name`
  // (still useful as a filename hint).
  function handleDrop(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
    if (!session.sessionId) return;
    const files = Array.from(e.dataTransfer.files);
    if (files.length === 0) return;
    const paths = files
      .map((f) => {
        const p = (f as File & { path?: string }).path ?? f.name;
        // Shell-quote: wrap in single quotes, escape inner single quotes.
        return `'${p.replace(/'/g, "'\\''")}'`;
      })
      .join(" ");
    invoke("terminal_write", { sessionId: session.sessionId, data: paths }).catch((err) =>
      console.error("[terminal] drop write failed", err),
    );
  }

  function handleDragOver(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragEnter(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(true);
  }

  function handleDragLeave(e: React.DragEvent<HTMLDivElement>) {
    e.preventDefault();
    setDragOver(false);
  }

  return (
    <div
      className={`terminal-view-container${dragOver ? " drag-over" : ""}`}
      style={{ display: props.visible ? "block" : "none" }}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
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
