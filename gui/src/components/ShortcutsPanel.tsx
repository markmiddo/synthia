import { useEffect, useMemo, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { writeText } from "@tauri-apps/plugin-clipboard-manager";
import "./ShortcutsPanel.css";

type AliasEntry = { name: string; expansion: string };

type Hotkey = { keys: string; action: string; scope: string };

const SYNTHIA_HOTKEYS: Hotkey[] = [
  { keys: "Right Ctrl", action: "Voice dictation", scope: "Global" },
  { keys: "Right Alt", action: "AI assistant", scope: "Global" },
  { keys: "Alt+T", action: "New terminal tab", scope: "Terminal focused" },
  { keys: "Alt+W", action: "Close active tab", scope: "Terminal focused" },
  { keys: "Ctrl+Shift+Tab", action: "Cycle tabs", scope: "Terminal focused" },
  { keys: "Ctrl+C", action: "Copy selection", scope: "Terminal focused" },
  { keys: "Ctrl+V", action: "Paste from clipboard", scope: "Terminal focused" },
  { keys: "Drag file in", action: "Insert file path", scope: "Terminal focused" },
];

export function ShortcutsPanel() {
  const [aliases, setAliases] = useState<AliasEntry[]>([]);
  const [filter, setFilter] = useState("");
  const [flashName, setFlashName] = useState<string | null>(null);

  useEffect(() => {
    invoke<AliasEntry[]>("get_shell_aliases")
      .then(setAliases)
      .catch((err) => console.error("get_shell_aliases failed", err));
  }, []);

  const needle = filter.trim().toLowerCase();
  const filteredHotkeys = useMemo(
    () =>
      SYNTHIA_HOTKEYS.filter(
        (h) =>
          !needle ||
          h.keys.toLowerCase().includes(needle) ||
          h.action.toLowerCase().includes(needle),
      ),
    [needle],
  );
  const filteredAliases = useMemo(
    () =>
      aliases.filter(
        (a) =>
          !needle ||
          a.name.toLowerCase().includes(needle) ||
          a.expansion.toLowerCase().includes(needle),
      ),
    [aliases, needle],
  );

  async function copyAlias(name: string) {
    try {
      await writeText(name);
      setFlashName(name);
      window.setTimeout(() => setFlashName(null), 600);
    } catch (err) {
      console.error("clipboard write failed", err);
    }
  }

  return (
    <div className="shortcuts-panel">
      <input
        className="shortcuts-search"
        placeholder="Search shortcuts and aliases…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="shortcuts-section-header">Synthia hotkeys</div>
      <div className="shortcuts-table">
        {filteredHotkeys.length === 0 ? (
          <div className="shortcuts-empty">No matches.</div>
        ) : (
          filteredHotkeys.map((h) => (
            <div className="shortcuts-row" key={h.keys}>
              <span className="shortcuts-keys">{h.keys}</span>
              <span className="shortcuts-action">
                {h.action}
                <span className="shortcuts-scope"> · {h.scope}</span>
              </span>
            </div>
          ))
        )}
      </div>

      <div className="shortcuts-section-header">Shell aliases</div>
      <div className="shortcuts-table">
        {aliases.length === 0 ? (
          <div className="shortcuts-empty">
            No aliases found in your shell rc files.
          </div>
        ) : filteredAliases.length === 0 ? (
          <div className="shortcuts-empty">No matches.</div>
        ) : (
          filteredAliases.map((a) => (
            <button
              type="button"
              className={`shortcuts-row clickable${
                flashName === a.name ? " flash" : ""
              }`}
              key={a.name}
              onClick={() => copyAlias(a.name)}
              title="Click to copy alias name"
            >
              <span className="shortcuts-keys">{a.name}</span>
              <span className="shortcuts-action">{a.expansion}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
