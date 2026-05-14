import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

/// Serialize native_term_show / native_term_hide so a rapid tab toggle
/// (hide fires before the previous show finished inserting the session
/// into the backend map) can't cause state loss.  Each call chains onto
/// the previous one so show.observe → hide.run order is preserved even
/// when React fires both within a few milliseconds.
let lastNativeTermOp: Promise<unknown> = Promise.resolve();
function chain<T>(op: () => Promise<T>): Promise<T> {
  const next = lastNativeTermOp.then(op, op);
  lastNativeTermOp = next.catch(() => {});
  return next;
}

interface NativeTerminalViewProps {
  visible: boolean;
  /** When set, show that specific tab; null/undefined defaults to last active. */
  activeTabId?: string | null;
}

interface TermGeom {
  x: number;
  y: number;
  width: number;
  height: number;
}

export function NativeTerminalView({ visible, activeTabId }: NativeTerminalViewProps) {
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
      chain(() => invoke("native_term_hide")).catch(() => {});
      return;
    }
    if (!containerRef.current) return;
    let cancelled = false;
    // Register show into the chain SYNCHRONOUSLY at mount time — the
    // rAF wait for layout happens *inside* the chained promise, so a
    // hide queued by useEffect cleanup (when the user clicks another
    // tab fast) always runs after show in the same chain order.
    chain(
      () =>
        new Promise<string>((resolve, reject) => {
          const tryShow = () => {
            if (cancelled) {
              reject(new Error("cancelled"));
              return;
            }
            const geom = computeGeom();
            if (!geom || geom.width <= 1 || geom.height <= 1) {
              requestAnimationFrame(tryShow);
              return;
            }
            invoke<string>("native_term_show", { tabId: activeTabId ?? null, geom }).then(
              resolve,
              reject,
            );
          };
          tryShow();
        }),
    )
      .then((id) => {
        if (!cancelled) sessionRef.current = id as string;
      })
      .catch((e) => {
        if (!cancelled) setError(String(e));
      });
    return () => {
      cancelled = true;
      chain(() => invoke("native_term_hide")).catch(() => {});
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
      // native_term_show is idempotent — reuses active or persistent
      // session and just repositions/resizes when one already exists.
      chain(() => invoke("native_term_show", { tabId: activeTabId ?? null, geom })).catch(
        () => {},
      );
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
