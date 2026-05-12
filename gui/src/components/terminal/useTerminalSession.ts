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

      // Attempt WebGL renderer — fastest rendering path.
      // We track success explicitly so we know which renderer is active.
      let webglAddon: WebglAddon | null = null;
      try {
        webglAddon = new WebglAddon();
        // Propagate WebGL context-loss as an error so we can fall through
        // to the canvas renderer without leaving a broken addon attached.
        webglAddon.onContextLoss(() => {
          webglAddon?.dispose();
          webglAddon = null;
          console.warn("[terminal] WebGL context lost — renderer degraded to canvas");
        });
        term.loadAddon(webglAddon);
      } catch (e) {
        webglAddon = null;
        console.warn("[terminal] WebGL addon failed to load — falling back to canvas renderer", e);
      }

      term.open(containerRef.current);
      fit.fit();

      // Log the actual renderer that loaded so we can verify it in console.
      if (webglAddon !== null) {
        console.info("[terminal] WebGL renderer active");
      } else {
        console.warn("[terminal] Using canvas/DOM renderer — install @xterm/addon-canvas for better performance");
      }

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

        // Binary channel: Rust sends InvokeResponseBody::Raw → JS receives ArrayBuffer.
        // Zero base64 overhead in both directions.
        const outputChannel = new Channel<ArrayBuffer>();
        outputChannel.onmessage = (buf: ArrayBuffer) => {
          term.write(new Uint8Array(buf));
        };

        // Exit events remain on the low-frequency event bus.
        unlistenExit = await listen<number>(
          `terminal-exit-${sessionMeta.id}`,
          (event) => {
            setExitCode(event.payload);
            onExit?.(event.payload);
          },
        );

        // Keystroke coalescing: batch multiple onData callbacks that fire within
        // the same JS microtask queue drain into a single invoke call.
        // Eliminates redundant IPC round-trips during paste or fast typing.
        let pendingInput = "";
        let inputScheduled = false;
        term.onData((data) => {
          pendingInput += data;
          if (!inputScheduled) {
            inputScheduled = true;
            queueMicrotask(() => {
              const batch = pendingInput;
              pendingInput = "";
              inputScheduled = false;
              invoke("terminal_write", { sessionId: sessionMeta.id, data: batch }).catch(
                (e) => console.error("[terminal] write failed", e),
              );
            });
          }
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
