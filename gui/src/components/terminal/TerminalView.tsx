import { useEffect, useRef } from "react";
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
      // Defer until after the display:block repaint so clientWidth is correct.
      requestAnimationFrame(() => {
        session.fit();
        session.focus();
      });
    }
  }, [props.visible, session]);

  return (
    <div
      className="terminal-view-container"
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
