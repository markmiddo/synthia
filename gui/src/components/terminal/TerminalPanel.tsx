import { useCallback, useEffect, useState } from "react";
import { TerminalTabs } from "./TerminalTabs";
import { TerminalView } from "./TerminalView";
import { onSpawnRequest, type SpawnRequest } from "./spawnRequest";
import type { SessionMeta } from "./useTerminalSession";

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
    </div>
  );
}
