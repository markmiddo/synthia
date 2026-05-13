import { useCallback, useEffect, useState } from "react";
import { NativeTerminalView } from "./NativeTerminalView";
import { TerminalTabs } from "./TerminalTabs";
import { TerminalView } from "./TerminalView";
import { onSpawnRequest, type SpawnRequest } from "./spawnRequest";
import type { SessionMeta } from "./useTerminalSession";

type TerminalMode = "xterm" | "native";

const STORAGE_KEY = "synthia.terminal.mode";

function loadMode(): TerminalMode {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (v === "native" || v === "xterm") return v;
  } catch {
    // ignore
  }
  return "xterm";
}

function saveMode(mode: TerminalMode) {
  try {
    localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore
  }
}

interface Tab {
  uiId: string;
  title: string;
  cwd?: string;
  shell?: string;
  initialCommand?: string;
}

function uid() {
  return `tab-${Math.random().toString(36).slice(2, 10)}-${Date.now().toString(36)}`;
}

interface TerminalPanelProps {
  visible: boolean;
}

export function TerminalPanel({ visible }: TerminalPanelProps) {
  const [tabs, setTabs] = useState<Tab[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [mode, setMode] = useState<TerminalMode>(loadMode);

  const handleModeToggle = (next: TerminalMode) => {
    setMode(next);
    saveMode(next);
  };

  const newShell = useCallback((req?: SpawnRequest) => {
    const tab: Tab = {
      uiId: uid(),
      title: req?.cwd
        ? `shell · ${req.cwd.split("/").pop() ?? req.cwd}`
        : "shell",
      cwd: req?.cwd,
      shell: req?.shell,
      initialCommand: req?.initialCommand,
    };
    setTabs((t) => [...t, tab]);
    setActiveId(tab.uiId);
  }, []);

  const newClaude = useCallback(() => {
    newShell({ initialCommand: "claude" });
  }, [newShell]);

  const closeTab = useCallback((uiId: string) => {
    setTabs((t) => {
      const remaining = t.filter((x) => x.uiId !== uiId);
      setActiveId((current) => {
        if (current !== uiId) return current;
        return remaining.length ? remaining[remaining.length - 1].uiId : null;
      });
      return remaining;
    });
  }, []);

  useEffect(() => {
    return onSpawnRequest((req) => newShell(req));
  }, [newShell]);

  useEffect(() => {
    if (!visible) return;
    function onKey(e: KeyboardEvent) {
      if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "t") {
        e.preventDefault();
        newShell();
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "c") {
        e.preventDefault();
        newClaude();
      } else if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === "w") {
        if (activeId) {
          e.preventDefault();
          closeTab(activeId);
        }
      } else if (e.ctrlKey && e.key === "Tab" && !e.shiftKey) {
        if (tabs.length > 1 && activeId) {
          e.preventDefault();
          const idx = tabs.findIndex((t) => t.uiId === activeId);
          setActiveId(tabs[(idx + 1) % tabs.length].uiId);
        }
      } else if (e.ctrlKey && e.key === "Tab" && e.shiftKey) {
        if (tabs.length > 1 && activeId) {
          e.preventDefault();
          const idx = tabs.findIndex((t) => t.uiId === activeId);
          setActiveId(tabs[(idx - 1 + tabs.length) % tabs.length].uiId);
        }
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [visible, tabs, activeId, newShell, newClaude, closeTab]);

  function onMeta(uiId: string, meta: SessionMeta) {
    setTabs((t) => t.map((x) => (x.uiId === uiId ? { ...x, title: meta.title } : x)));
  }

  return (
    <div className="terminal-panel">
      {/* Mode toggle header */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "6px",
          padding: "4px 8px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: "11px",
            color: "rgba(255,255,255,0.4)",
            marginRight: "2px",
          }}
        >
          Renderer:
        </span>
        <button
          onClick={() => handleModeToggle("xterm")}
          style={{
            fontSize: "11px",
            padding: "2px 8px",
            border: "none",
            borderRadius: "3px",
            cursor: "pointer",
            background: mode === "xterm" ? "rgba(99,102,241,0.7)" : "rgba(255,255,255,0.06)",
            color: mode === "xterm" ? "#fff" : "rgba(255,255,255,0.5)",
          }}
        >
          xterm.js
        </button>
        <button
          onClick={() => handleModeToggle("native")}
          style={{
            fontSize: "11px",
            padding: "2px 8px",
            border: "none",
            borderRadius: "3px",
            cursor: "pointer",
            background: mode === "native" ? "rgba(99,102,241,0.7)" : "rgba(255,255,255,0.06)",
            color: mode === "native" ? "#fff" : "rgba(255,255,255,0.5)",
          }}
        >
          Native (beta)
        </button>
      </div>

      {/* Native mode: single Wezterm overlay */}
      {mode === "native" ? (
        <NativeTerminalView visible={visible} />
      ) : (
        <>
          {tabs.length > 0 && (
            <TerminalTabs
              tabs={tabs.map((t) => ({ uiId: t.uiId, title: t.title }))}
              activeId={activeId}
              onSelect={setActiveId}
              onClose={closeTab}
              onNewShell={() => newShell()}
              onNewClaude={newClaude}
            />
          )}
          {tabs.length === 0 ? (
            <div className="terminal-empty">
              <div>No terminals</div>
              <div className="actions">
                <button onClick={() => newShell()}>+ New</button>
                <button className="claude" onClick={newClaude}>
                  + Claude
                </button>
              </div>
            </div>
          ) : (
            tabs.map((t) => (
              <TerminalView
                key={t.uiId}
                cwd={t.cwd}
                shell={t.shell}
                initialCommand={t.initialCommand}
                visible={visible && t.uiId === activeId}
                onMeta={(m) => onMeta(t.uiId, m)}
              />
            ))
          )}
        </>
      )}
    </div>
  );
}
