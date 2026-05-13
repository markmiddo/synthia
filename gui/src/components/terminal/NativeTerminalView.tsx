import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface NativeTerminalViewProps {
  visible: boolean;
}

interface TermGeom {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function NativeTerminalView({ visible }: NativeTerminalViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const sessionRef = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const computeGeom = useCallback((): TermGeom | null => {
    if (!containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    return {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      width: Math.max(1, Math.round(rect.width)),
      height: Math.max(1, Math.round(rect.height)),
    };
  }, []);

  // Show on mount / when becoming visible.  Hide (but don't kill) on
  // unmount / when becoming hidden.  The backend keeps the PTY + subsurface
  // alive between hide/show cycles, so navigating away and back preserves
  // shell state, scrollback, and any running command.
  useEffect(() => {
    if (!visible) {
      // Hide path: tell backend to move subsurface off-screen + paint blank.
      invoke("native_term_hide").catch(() => {});
      return;
    }
    if (!containerRef.current) return;
    let cancelled = false;
    // Wait for layout: getBoundingClientRect after mount can return 0×0
    // for one frame.  rAF + a fallback timeout cover both cases.
    const showWhenReady = () => {
      if (cancelled) return;
      const geom = computeGeom();
      if (!geom || geom.width <= 1 || geom.height <= 1) {
        requestAnimationFrame(showWhenReady);
        return;
      }
      invoke<string>("native_term_show", { geom })
        .then((id) => {
          sessionRef.current = id;
        })
        .catch((e) => setError(String(e)));
    };
    requestAnimationFrame(showWhenReady);
    return () => {
      cancelled = true;
      // On unmount (section change), hide the persistent terminal so the
      // subsurface clears off-screen and the next section's content shows.
      // The PTY + render loop stay alive so a return to Terminal restores
      // the same shell state.
      invoke("native_term_hide").catch(() => {});
    };
  }, [visible, computeGeom]);

  // Reposition on resize / move — only push to backend when geom actually
  // changes so we don't spam the resize path at 4 Hz when idle.
  useEffect(() => {
    if (!visible) return;
    let last: TermGeom | null = null;
    const reposition = () => {
      const geom = computeGeom();
      if (!geom) return;
      if (
        last &&
        last.x === geom.x &&
        last.y === geom.y &&
        last.width === geom.width &&
        last.height === geom.height
      ) {
        return;
      }
      last = geom;
      // native_term_show is idempotent — reuses persistent session and just
      // repositions/resizes when one already exists.
      invoke("native_term_show", { geom }).catch(() => {});
    };
    const observer = new ResizeObserver(reposition);
    if (containerRef.current) observer.observe(containerRef.current);
    window.addEventListener("resize", reposition);
    const interval = window.setInterval(reposition, 250);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", reposition);
      window.clearInterval(interval);
    };
  }, [visible, computeGeom]);

  return (
    <div
      ref={containerRef}
      className="native-terminal-pane"
      style={{ width: "100%", height: "100%", background: "#0a0b14" }}
    >
      {error && (
        <div style={{ color: "#fda4af", fontFamily: "monospace", padding: 12 }}>
          Native terminal failed: {error}.
        </div>
      )}
    </div>
  );
}
