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

function App() {
  const [status, setStatus] = useState<Status>("stopped");
  const [remoteMode, setRemoteMode] = useState(false);
  const [dictateKey, setDictateKey] = useState("Right Ctrl");
  const [assistantKey, setAssistantKey] = useState("Right Alt");
  const [editingKey, setEditingKey] = useState<"dictate" | "assistant" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [currentView, setCurrentView] = useState<"main" | "history">("main");
  const [copiedId, setCopiedId] = useState<number | null>(null);

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

    initAndAutoStart();
    checkRemoteStatus();
    loadHistory();
    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
      if (currentView === "history") loadHistory();
    }, 2000);
    return () => clearInterval(interval);
  }, [currentView]);

  useEffect(() => {
    if (!editingKey) return;

    function handleKeyDown(e: KeyboardEvent) {
      e.preventDefault();
      const key = e.key === "Control" ? (e.location === 2 ? "Right Ctrl" : "Left Ctrl")
        : e.key === "Alt" ? (e.location === 2 ? "Right Alt" : "Left Alt")
        : e.key === "Shift" ? (e.location === 2 ? "Right Shift" : "Left Shift")
        : e.key;

      if (editingKey === "dictate") {
        setDictateKey(key);
      } else {
        setAssistantKey(key);
      }
      setEditingKey(null);
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [editingKey]);

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
    try {
      const result = await invoke<boolean>("get_remote_status");
      setRemoteMode(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleRemoteToggle() {
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

        {error && <div className="error">{error}</div>}
      </div>
    </main>
  );
}

export default App;
