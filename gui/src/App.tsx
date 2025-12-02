import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

type Status = "stopped" | "running" | "recording" | "thinking";

interface HistoryEntry {
  id: number;
  text: string;
  mode: "dictation" | "assistant";
  timestamp: string;
  response?: string;
}

interface WordReplacement {
  from: string;
  to: string;
}

function App() {
  const [status, setStatus] = useState<Status>("stopped");
  const [remoteMode, setRemoteMode] = useState(false);
  const [remoteToggling, setRemoteToggling] = useState(false);
  const [dictateKey, setDictateKey] = useState("Right Ctrl");
  const [assistantKey, setAssistantKey] = useState("Right Alt");
  const [editingKey, setEditingKey] = useState<"dictate" | "assistant" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [currentView, setCurrentView] = useState<"main" | "history" | "words">("main");
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [wordReplacements, setWordReplacements] = useState<WordReplacement[]>([]);
  const [newWordFrom, setNewWordFrom] = useState("");
  const [newWordTo, setNewWordTo] = useState("");

  useEffect(() => {
    // Auto-start Synthia when app opens
    async function initAndAutoStart() {
      try {
        const currentStatus = await invoke<string>("get_status");
        setStatus(currentStatus as Status);
        // If stopped, auto-start
        if (currentStatus === "stopped") {
          await invoke("start_synthia");
          setStatus("running");
        }
      } catch (e) {
        setError(String(e));
      }
    }

    // Load saved hotkeys from config
    async function loadHotkeys() {
      try {
        const [dictation, assistant] = await invoke<[string, string]>("get_hotkeys");
        setDictateKey(dictation);
        setAssistantKey(assistant);
      } catch (e) {
        // Use defaults if config can't be read
      }
    }

    initAndAutoStart();
    loadHotkeys();
    checkRemoteStatus();
    loadHistory();
    loadWordReplacements();
    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
      if (currentView === "history") loadHistory();
    }, 2000);
    return () => clearInterval(interval);
  }, [currentView]);

  async function loadWordReplacements() {
    try {
      const result = await invoke<WordReplacement[]>("get_word_replacements");
      setWordReplacements(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleAddWordReplacement() {
    if (!newWordFrom.trim() || !newWordTo.trim()) return;

    const updated = [...wordReplacements, { from: newWordFrom.trim(), to: newWordTo.trim() }];
    try {
      await invoke("save_word_replacements", { replacements: updated });
      setWordReplacements(updated);
      setNewWordFrom("");
      setNewWordTo("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRemoveWordReplacement(index: number) {
    const updated = wordReplacements.filter((_, i) => i !== index);
    try {
      await invoke("save_word_replacements", { replacements: updated });
      setWordReplacements(updated);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    if (!editingKey) return;

    async function handleKeyDown(e: KeyboardEvent) {
      e.preventDefault();
      const key = e.key === "Control" ? (e.location === 2 ? "Right Ctrl" : "Left Ctrl")
        : e.key === "Alt" ? (e.location === 2 ? "Right Alt" : "Left Alt")
        : e.key === "Shift" ? (e.location === 2 ? "Right Shift" : "Left Shift")
        : e.key;

      // Determine new key values
      const newDictateKey = editingKey === "dictate" ? key : dictateKey;
      const newAssistantKey = editingKey === "assistant" ? key : assistantKey;

      // Update state
      if (editingKey === "dictate") {
        setDictateKey(key);
      } else {
        setAssistantKey(key);
      }
      setEditingKey(null);

      // Save to config and restart Synthia to apply
      try {
        await invoke("save_hotkeys", {
          dictationKey: newDictateKey,
          assistantKey: newAssistantKey
        });
      } catch (e) {
        setError(String(e));
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editingKey, dictateKey, assistantKey]);

  async function checkStatus() {
    try {
      const result = await invoke<string>("get_status");
      setStatus(result as Status);
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleStart() {
    try {
      await invoke("start_synthia");
      setStatus("running");
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleStop() {
    try {
      await invoke("stop_synthia");
      setStatus("stopped");
      setError(null);
    } catch (e) {
      setError(String(e));
    }
  }

  async function checkRemoteStatus() {
    // Skip polling if we're in the middle of a toggle action
    if (remoteToggling) return;

    try {
      const result = await invoke<boolean>("get_remote_status");
      setRemoteMode(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleRemoteToggle() {
    // Prevent polling from overriding our state during toggle
    setRemoteToggling(true);

    try {
      if (remoteMode) {
        await invoke("stop_remote_mode");
        setRemoteMode(false);
      } else {
        await invoke("start_remote_mode");
        setRemoteMode(true);
      }
      setError(null);
    } catch (e) {
      setError(String(e));
    }

    // Re-enable polling after a delay to let the backend settle
    setTimeout(() => setRemoteToggling(false), 3000);
  }

  async function loadHistory() {
    try {
      const result = await invoke<HistoryEntry[]>("get_history");
      setHistory(result.reverse()); // Show newest first
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleCopy(text: string, id: number) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (e) {
      setError("Failed to copy");
    }
  }

  async function handleResend(text: string) {
    try {
      await invoke("resend_to_assistant", { text });
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleClearHistory() {
    try {
      await invoke("clear_history");
      setHistory([]);
    } catch (e) {
      setError(String(e));
    }
  }

  function formatTime(timestamp: string) {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  const statusColors: Record<Status, string> = {
    stopped: "#6b7280",
    running: "#22c55e",
    recording: "#ef4444",
    thinking: "#eab308",
  };

  // Word Replacements View
  if (currentView === "words") {
    return (
      <main className="container">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setCurrentView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">WORD DICTIONARY</div>
        </div>

        <div className="words-view-content">
          <p className="words-description">
            Fix common Whisper misrecognitions. Words on the left get replaced with words on the right.
          </p>

          <div className="word-add-form">
            <input
              type="text"
              placeholder="Wrong word"
              value={newWordFrom}
              onChange={(e) => setNewWordFrom(e.target.value)}
              className="word-input"
            />
            <span className="word-arrow">→</span>
            <input
              type="text"
              placeholder="Correct word"
              value={newWordTo}
              onChange={(e) => setNewWordTo(e.target.value)}
              className="word-input"
              onKeyDown={(e) => e.key === "Enter" && handleAddWordReplacement()}
            />
            <button className="word-add-btn" onClick={handleAddWordReplacement}>
              Add
            </button>
          </div>

          <div className="word-list">
            {wordReplacements.length === 0 ? (
              <div className="words-empty-state">
                <p>No word replacements yet</p>
                <p className="empty-hint">Add words that Whisper commonly gets wrong</p>
              </div>
            ) : (
              wordReplacements.map((r, index) => (
                <div key={index} className="word-item">
                  <span className="word-from">{r.from}</span>
                  <span className="word-arrow">→</span>
                  <span className="word-to">{r.to}</span>
                  <button
                    className="word-remove-btn"
                    onClick={() => handleRemoveWordReplacement(index)}
                  >
                    ×
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {error && <div className="error">{error}</div>}
      </main>
    );
  }

  // History View
  if (currentView === "history") {
    return (
      <main className="container">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setCurrentView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">VOICE HISTORY</div>
          {history.length > 0 && (
            <button className="clear-all-btn" onClick={handleClearHistory}>
              Clear All
            </button>
          )}
        </div>

        <div className="history-view-content">
          {history.length === 0 ? (
            <div className="history-empty-state">
              <p>No transcriptions yet</p>
              <p className="empty-hint">Use voice dictation or assistant to see history here</p>
            </div>
          ) : (
            <div className="history-list-full">
              {history.map((entry) => (
                <div key={entry.id} className={`history-item ${entry.mode}`}>
                  <div className="history-item-header">
                    <span className={`history-mode-label ${entry.mode}`}>
                      {entry.mode === "assistant" ? "ASSISTANT" : "DICTATION"}
                    </span>
                    <span className="history-time">{formatTime(entry.timestamp)}</span>
                  </div>
                  <p className="history-text">{entry.text}</p>
                  {entry.response && (
                    <p className="history-response">→ {entry.response}</p>
                  )}
                  <div className="history-item-actions">
                    <button
                      className={`history-btn ${copiedId === entry.id ? 'copied' : ''}`}
                      onClick={() => handleCopy(entry.text, entry.id)}
                    >
                      {copiedId === entry.id ? "✓" : "Copy"}
                    </button>
                    <button
                      className="history-btn resend"
                      onClick={() => handleResend(entry.text)}
                    >
                      Re-send
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {error && <div className="error">{error}</div>}
      </main>
    );
  }

  // Main View
  return (
    <main className="container">
      <div className="header">
        <div className="logo-text">SYNTHIA</div>
        <div className="tagline">AI Voice Assistant</div>
      </div>

      <div className="content">
        <div className="status-section">
          <div
            className={`status-indicator ${status === "running" ? "running" : ""}`}
            style={{ backgroundColor: statusColors[status] }}
          />
          <span className="status-text">{status.charAt(0).toUpperCase() + status.slice(1)}</span>
        </div>

        <div className="controls">
          {status === "stopped" ? (
            <button className="btn btn-start" onClick={handleStart}>
              Start Synthia
            </button>
          ) : (
            <button className="btn btn-stop" onClick={handleStop}>
              Stop Synthia
            </button>
          )}
        </div>

        <div className="card">
          <div className="remote-toggle">
            <span>Remote Mode (Telegram)</span>
            <button
              className={`toggle ${remoteMode ? "active" : ""}`}
              onClick={handleRemoteToggle}
            >
              <div className="toggle-knob" />
            </button>
          </div>
          <p className="remote-description">
            {remoteMode ? "Telegram bot active - control via phone" : "Telegram bot disabled"}
          </p>
        </div>

        <div className="card hotkeys">
          <h3>Hotkeys</h3>
          <div className="hotkey-row">
            <button
              className={`hotkey-btn ${editingKey === "dictate" ? "editing" : ""}`}
              onClick={() => setEditingKey("dictate")}
            >
              {editingKey === "dictate" ? "Press key..." : dictateKey}
            </button>
            <span>Dictation</span>
          </div>
          <div className="hotkey-row">
            <button
              className={`hotkey-btn ${editingKey === "assistant" ? "editing" : ""}`}
              onClick={() => setEditingKey("assistant")}
            >
              {editingKey === "assistant" ? "Press key..." : assistantKey}
            </button>
            <span>AI Assistant</span>
          </div>
        </div>

        <button
          className="history-nav-btn"
          onClick={() => { setCurrentView("history"); loadHistory(); }}
        >
          <span>Voice History</span>
          {history.length > 0 && <span className="history-count">{history.length}</span>}
        </button>

        <button
          className="history-nav-btn"
          onClick={() => { setCurrentView("words"); loadWordReplacements(); }}
        >
          <span>Word Dictionary</span>
          {wordReplacements.length > 0 && <span className="history-count">{wordReplacements.length}</span>}
        </button>

        {error && <div className="error">{error}</div>}
      </div>
    </main>
  );
}

export default App;
