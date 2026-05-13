import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";

interface SessionMeta {
  id: string;
  cwd: string;
  shell: string;
  title: string;
  created_at: string;
}

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
    // Wayland subsurface positions are in logical pixels on this setup.
    // The compositor handles DPI scaling internally — do NOT multiply by
    // devicePixelRatio here or the position/size will be double-counted.
    return {
      x: Math.round(rect.left),
      y: Math.round(rect.top),
      width: Math.max(1, Math.round(rect.width)),
      height: Math.max(1, Math.round(rect.height)),
    };
  }, []);

  // Spawn + attach on mount when visible
  useEffect(() => {
    if (!visible || !containerRef.current || sessionRef.current) return;
    let cancelled = false;
    (async () => {
      try {
        const meta = await invoke<SessionMeta>("terminal_spawn", {});
        if (cancelled) {
          await invoke("terminal_kill", { sessionId: meta.id }).catch(() => {});
          return;
        }
        const geom = computeGeom();
        if (!geom) throw new Error("no geom");
        await invoke("native_term_attach", { sessionId: meta.id, geom });
        sessionRef.current = meta.id;
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      cancelled = true;
      if (sessionRef.current) {
        const id = sessionRef.current;
        sessionRef.current = null;
        invoke("native_term_detach", { sessionId: id })
          .catch(() => {})
          .then(() => invoke("terminal_kill", { sessionId: id }).catch(() => {}));
      }
    };
  }, [visible, computeGeom]);

  // Detach + kill when component becomes hidden (mode toggle or section switch)
  // without unmounting (e.g. when parent keeps both renderers in the tree).
  useEffect(() => {
    if (visible) return; // only act when transitioning to hidden
    if (!sessionRef.current) return;
    const id = sessionRef.current;
    sessionRef.current = null;
    invoke("native_term_detach", { sessionId: id })
      .catch(() => {})
      .then(() => invoke("terminal_kill", { sessionId: id }).catch(() => {}));
  }, [visible]);

  // Reposition on resize / move
  useEffect(() => {
    if (!visible) return;
    const reposition = () => {
      if (!sessionRef.current) return;
      const geom = computeGeom();
      if (geom) {
        invoke("native_term_resize", { sessionId: sessionRef.current, geom }).catch(() => {});
      }
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
      style={{ width: "100%", height: "100%", background: "#0d1117" }}
    >
      {error && (
        <div style={{ color: "#fda4af", fontFamily: "monospace", padding: 12 }}>
          Native terminal failed: {error}. Toggle back to xterm.js.
        </div>
      )}
    </div>
  );
}
