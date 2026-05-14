import { useEffect, useRef, useState } from "react";
import { invoke, Channel } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { readText, writeText, readImage } from "@tauri-apps/plugin-clipboard-manager";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebglAddon } from "@xterm/addon-webgl";
import { CanvasAddon } from "@xterm/addon-canvas";
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
    let onWinResize: (() => void) | undefined;

    async function start(): Promise<(() => void) | undefined> {
      if (!containerRef.current) return;

      const term = new Terminal({
        theme: glassTheme,
        fontFamily: terminalFont.family,
        fontSize: terminalFont.size,
        lineHeight: terminalFont.lineHeight,
        fontWeight: terminalFont.weight,
        cursorBlink: false,
        scrollback: 1000,
        allowProposedApi: true,
        disableStdin: false,
        convertEol: false,
        fastScrollModifier: "shift",
      });
      const fit = new FitAddon();
      term.loadAddon(fit);
      term.loadAddon(new WebLinksAddon());
      term.loadAddon(new SearchAddon());

      term.open(containerRef.current);
      // Belt-and-braces fit schedule: rAF for first paint, then two more
      // timeouts to handle slow flex layout passes on Linux/COSMIC.
      requestAnimationFrame(() => fit.fit());
      window.setTimeout(() => fit.fit(), 100);
      window.setTimeout(() => fit.fit(), 300);

      onWinResize = () => fit.fit();
      window.addEventListener("resize", onWinResize);

      // Renderer load order: WebGL (fastest) → Canvas (mid-tier) → DOM (slowest fallback).
      // On webkit2gtk/COSMIC, WebGL may silently fall back to the DOM renderer internally.
      // The Canvas addon avoids that by using the 2D canvas API which is always accelerated.
      let rendererName = "dom";
      try {
        const webglAddon = new WebglAddon();
        // Propagate WebGL context-loss so we degrade gracefully without a broken addon.
        webglAddon.onContextLoss(() => {
          webglAddon.dispose();
          console.warn("[terminal] WebGL context lost — falling back to dom renderer");
        });
        term.loadAddon(webglAddon);
        rendererName = "webgl";
      } catch (e) {
        console.warn("[terminal] WebGL unavailable, trying canvas", e);
        try {
          term.loadAddon(new CanvasAddon());
          rendererName = "canvas";
        } catch (e2) {
          console.warn("[terminal] Canvas unavailable, using DOM (slowest)", e2);
        }
      }
      console.info(`[terminal] renderer = ${rendererName}`);

      termRef.current = term;
      fitRef.current = fit;
      // Fix 3: write renderer name to the terminal screen so it's visible without DevTools.
      term.write(`\x1b[2m[synthia: renderer=${rendererName}]\x1b[0m\r\n`);

      try {
        const sessionMeta = await invoke<SessionMeta>("terminal_spawn", { cwd, shell });
        if (disposed) {
          await invoke("terminal_kill", { sessionId: sessionMeta.id });
          return;
        }
        spawnedId = sessionMeta.id;
        setSessionId(sessionMeta.id);
        setMeta(sessionMeta);

        // Channel<String> with base64 — proven reliable across Tauri 2.x webkit builds.
        // Binary InvokeResponseBody::Raw was unreliable; JS received empty/undefined data.
        const outputChannel = new Channel<string>();
        outputChannel.onmessage = (encoded: string) => {
          const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
          term.write(bytes);
        };

        // Optional write-timing diagnostics: set localStorage.SYNTHIA_TERM_DEBUG = '1'
        // in DevTools console and reload to enable. Logs inter-write delta + payload length.
        const debug =
          typeof localStorage !== "undefined" &&
          localStorage.getItem("SYNTHIA_TERM_DEBUG") === "1";
        if (debug) {
          let lastWrite = performance.now();
          const origWrite = term.write.bind(term);
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          (term as any).write = function (data: any) {
            const now = performance.now();
            console.debug(
              `[terminal] write Δ${(now - lastWrite).toFixed(1)}ms len=${
                typeof data === "string" ? data.length : data.byteLength
              }`,
            );
            lastWrite = now;
            return origWrite(data);
          };
        }

        // Exit events remain on the low-frequency event bus.
        unlistenExit = await listen<number>(
          `terminal-exit-${sessionMeta.id}`,
          (event) => {
            setExitCode(event.payload);
            onExit?.(event.payload);
          },
        );

        // Custom Ctrl+V paste handler. xterm's default ignores Ctrl+V (Linux terminals
        // reserve it for the running program). We override it for editor-like UX.
        //
        // Clipboard notes: navigator.clipboard throws NotAllowedError in webkit2gtk
        // because the webview hasn't been granted clipboard-read permission.
        // We use the Tauri clipboard-manager plugin instead, which reads the OS
        // clipboard directly without needing browser permission grants.
        term.attachCustomKeyEventHandler((event: KeyboardEvent) => {
          if (event.type !== "keydown") return true;

          // Ctrl+V (no shift) — paste from clipboard, but forward raw ^V if the
          // clipboard contains an image so the inner program (e.g. Claude Code)
          // can call wl-paste itself.
          if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "v") {
            event.preventDefault();
            (async () => {
              try {
                // If the clipboard has an image, forward raw ^V to the inner
                // app (Claude Code etc) which knows how to read images via wl-paste.
                let hasImage = false;
                try {
                  const img = await readImage();
                  hasImage = !!img;
                } catch {
                  /* no image or not supported */
                }
                if (hasImage) {
                  // Forward raw 0x16 (^V) to PTY so the running app reads the image.
                  await invoke("terminal_write", { sessionId: sessionMeta.id, data: "\x16" });
                  return;
                }
                const text = await readText();
                if (text) {
                  await invoke("terminal_write", { sessionId: sessionMeta.id, data: text });
                }
              } catch (e) {
                console.error("[terminal] paste failed", e);
                term.write(`\r\n\x1b[31m[paste failed: ${String(e).slice(0, 100)}]\x1b[0m\r\n`);
              }
            })();
            return false;
          }

          // Ctrl+Shift+V — also paste (Linux convention). Always text path.
          if (event.ctrlKey && event.shiftKey && !event.altKey && event.key.toLowerCase() === "v") {
            event.preventDefault();
            (async () => {
              try {
                const text = await readText();
                if (text) await invoke("terminal_write", { sessionId: sessionMeta.id, data: text });
              } catch (e) {
                console.error("[terminal] paste failed", e);
                term.write(`\r\n\x1b[31m[paste failed: ${String(e).slice(0, 100)}]\x1b[0m\r\n`);
              }
            })();
            return false;
          }

          // Ctrl+C: copy selection if any, otherwise pass through as interrupt (^C).
          if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key.toLowerCase() === "c") {
            const sel = term.getSelection();
            if (sel && sel.length > 0) {
              event.preventDefault();
              writeText(sel).catch((e) => console.error("[terminal] copy failed", e));
              term.clearSelection();
              return false;
            }
          }

          return true;
        });

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
      if (onWinResize) window.removeEventListener("resize", onWinResize);
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
