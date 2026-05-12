import { useEffect, useRef, useState } from "react";
import { invoke, Channel } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { SearchAddon } from "@xterm/addon-search";
import { glassTheme, terminalFont } from "./theme";

export interface SessionMeta {
  id: string;
  cwd: string;
  shell: string;
  title: string;
  created_at: string;
}

export interface UseTerminalSessionOptions {
  containerRef: React.RefObject<HTMLDivElement | null>;
  cwd?: string;
  shell?: string;
  initialCommand?: string;
  onExit?: (code: number) => void;
}

export interface TerminalSessionHandle {
  sessionId: string | null;
  meta: SessionMeta | null;
  error: string | null;
  exitCode: number | null;
  focus: () => void;
  fit: () => void;
}

export function useTerminalSession(opts: UseTerminalSessionOptions): TerminalSessionHandle {
  const { containerRef, cwd, shell, initialCommand, onExit } = opts;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [meta, setMeta] = useState<SessionMeta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exitCode, setExitCode] = useState<number | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    let unlistenExit: UnlistenFn | undefined;
    let disposed = false;
    let spawnedId: string | null = null;

    async function start(): Promise<(() => void) | undefined> {
      if (!containerRef.current) return;

      const term = new Terminal({
        theme: glassTheme,
        fontFamily: terminalFont.family,
        fontSize: terminalFont.size,
        lineHeight: terminalFont.lineHeight,
        fontWeight: terminalFont.weight,
        cursorBlink: true,
        scrollback: 5000,
        allowProposedApi: true,
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.loadAddon(new WebLinksAddon());
      term.loadAddon(new SearchAddon());
      try {
        term.loadAddon(new WebglAddon());
      } catch (e) {
        console.warn("[terminal] WebGL addon unavailable, falling back to canvas", e);
      }

      term.open(containerRef.current);
      fit.fit();
      termRef.current = term;
      fitRef.current = fit;

      try {
        const sessionMeta = await invoke<SessionMeta>("terminal_spawn", { cwd, shell });
        if (disposed) {
          await invoke("terminal_kill", { sessionId: sessionMeta.id });
          return;
        }
        spawnedId = sessionMeta.id;
        setSessionId(sessionMeta.id);
        setMeta(sessionMeta);

        // Build a typed Channel for PTY output. This bypasses the global event
        // router and eliminates the per-chunk routing overhead that caused
        // visible keystroke lag.
        const outputChannel = new Channel<string>();
        outputChannel.onmessage = (encoded: string) => {
          const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
          term.write(bytes);
        };

        // Exit events remain on the low-frequency event bus.
        unlistenExit = await listen<number>(
          `terminal-exit-${sessionMeta.id}`,
          (event) => {
            setExitCode(event.payload);
            onExit?.(event.payload);
          },
        );

        term.onData((data) => {
          invoke("terminal_write", { sessionId: sessionMeta.id, data }).catch((e) =>
            console.error("[terminal] write failed", e),
          );
        });

        term.onResize(({ cols, rows }) => {
          invoke("terminal_resize", { sessionId: sessionMeta.id, cols, rows }).catch(
            (e) => console.error("[terminal] resize failed", e),
          );
        });

        // Pass the channel to terminal_attach — Rust streams PTY output directly
        // through it without touching the global event bus.
        await invoke("terminal_attach", {
          sessionId: sessionMeta.id,
          onOutput: outputChannel,
        });

        if (initialCommand) {
          await invoke("terminal_write", {
            sessionId: sessionMeta.id,
            data: `${initialCommand}\n`,
          });
        }

        const observer = new ResizeObserver(() => {
          if (!disposed) fit.fit();
        });
        if (containerRef.current) observer.observe(containerRef.current);
        return () => observer.disconnect();
      } catch (e) {
        setError(String(e));
      }
    }

    const cleanupPromise = start();

    return () => {
      disposed = true;
      cleanupPromise.then((maybeCleanup) => {
        if (typeof maybeCleanup === "function") maybeCleanup();
      });
      unlistenExit?.();
      if (spawnedId) {
        invoke("terminal_kill", { sessionId: spawnedId }).catch(() => {});
      }
      termRef.current?.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, [containerRef, cwd, shell, initialCommand, onExit]);

  return {
    sessionId,
    meta,
    error,
    exitCode,
    focus: () => termRef.current?.focus(),
    fit: () => fitRef.current?.fit(),
  };
}
