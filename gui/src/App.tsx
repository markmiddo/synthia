import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import "./App.css";

type Status = "stopped" | "running" | "recording" | "thinking";

function App() {
  const [status, setStatus] = useState<Status>("stopped");
  const [remoteMode, setRemoteMode] = useState(false);
  const [dictateKey, setDictateKey] = useState("Right Ctrl");
  const [assistantKey, setAssistantKey] = useState("Right Alt");
  const [editingKey, setEditingKey] = useState<"dictate" | "assistant" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    checkStatus();
    checkRemoteStatus();
    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
    }, 2000);
    return () => clearInterval(interval);
  }, []);

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

  const statusColors: Record<Status, string> = {
    stopped: "#6b7280",
    running: "#22c55e",
    recording: "#ef4444",
    thinking: "#eab308",
  };

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

        {error && <div className="error">{error}</div>}
      </div>
    </main>
  );
}

export default App;
