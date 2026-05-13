/**
 * NativeTerminalView — fake-embed prototype (Stage 1).
 *
 * Spawns a borderless Wezterm window and repositions it to sit precisely over
 * this component's DOM bounding box.  As Synthia moves, resizes, or switches
 * panels, the Wezterm window follows (250 ms poll + ResizeObserver).
 *
 * Limitations (Stage 1):
 *  - Requires Xwayland ($DISPLAY set).  Pure Wayland will get a clear error.
 *  - Window stacking order is best-effort; Wezterm sits above Synthia but may
 *    be occluded by other apps. Stage 2 (Tauri child window) fixes this.
 */

import { invoke } from "@tauri-apps/api/core";
import { useCallback, useEffect, useRef } from "react";

interface TermGeom {
  x: number;
  y: number;
  width: number;
  height: number;
}

interface NativeTerminalViewProps {
  visible: boolean;
}

export function NativeTerminalView({ visible }: NativeTerminalViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<string | null>(null);
  const errorRef = useRef<string | null>(null);

  /** Compute pane geometry in physical screen pixels. */
  const computeGeom = useCallback((): TermGeom | null => {
    if (!containerRef.current) return null;
    const rect = containerRef.current.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    return {
      x: Math.round((window.screenX + rect.left) * dpr),
      y: Math.round((window.screenY + rect.top) * dpr),
      width: Math.round(rect.width * dpr),
      height: Math.round(rect.height * dpr),
    };
  }, []);

  // Spawn on first mount when visible.
  useEffect(() => {
    if (!visible || !containerRef.current || sessionRef.current) return;
    if (errorRef.current) return; // don't retry after a fatal error

    const geom = computeGeom();
    if (!geom) return;

    invoke<string>("native_term_spawn", { cwd: undefined, geom })
      .then((id) => {
        sessionRef.current = id;
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : String(e);
        console.error("[native-term] spawn failed:", msg);
        errorRef.current = msg;
      });

    // Cleanup: kill the Wezterm window when the component unmounts.
    return () => {
      const id = sessionRef.current;
      if (id) {
        invoke("native_term_kill", { nativeSessionId: id }).catch(() => {});
        sessionRef.current = null;
      }
    };
  }, [visible, computeGeom]);

  // Reposition on visibility change, window resize, or every 250 ms (window move).
  useEffect(() => {
    if (!visible) return;

    const reposition = () => {
      const id = sessionRef.current;
      if (!id) return;
      const geom = computeGeom();
      if (!geom) return;
      invoke("native_term_reposition", {
        nativeSessionId: id,
        geom,
      }).catch(() => {});
    };

    const observer = new ResizeObserver(reposition);
    if (containerRef.current) {
      observer.observe(containerRef.current);
    }
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
      style={{
        width: "100%",
        height: "100%",
        background: "#0d1117",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: errorRef.current ? "#f85149" : "#8b949e",
        fontSize: "13px",
        fontFamily: "monospace",
      }}
    >
      {errorRef.current ? (
        <span>Native terminal error: {errorRef.current}</span>
      ) : !sessionRef.current ? (
        <span>Launching Wezterm…</span>
      ) : null}
    </div>
  );
}
