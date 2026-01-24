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

interface WorktreeTask {
  id: string;
  subject: string;
  status: "pending" | "in_progress" | "completed";
  active_form?: string;
  blocked_by: string[];
}

interface WorktreeInfo {
  path: string;
  branch: string;
  issue_number?: number;
  session_id?: string;
  tasks: WorktreeTask[];
}

type Section = "worktrees" | "voice" | "memory" | "config";
type VoiceView = "main" | "history" | "words";

function App() {
  const [status, setStatus] = useState<Status>("stopped");
  const [remoteMode, setRemoteMode] = useState(false);
  const [remoteToggling, setRemoteToggling] = useState(false);
  const [dictateKey, setDictateKey] = useState("Right Ctrl");
  const [assistantKey, setAssistantKey] = useState("Right Alt");
  const [editingKey, setEditingKey] = useState<"dictate" | "assistant" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [currentSection, setCurrentSection] = useState<Section>("worktrees");
  const [voiceView, setVoiceView] = useState<VoiceView>("main");
  const [worktrees, setWorktrees] = useState<WorktreeInfo[]>([]);
  const [selectedWorktree, setSelectedWorktree] = useState<WorktreeInfo | null>(null);
  const [copiedId, setCopiedId] = useState<number | null>(null);
  const [wordReplacements, setWordReplacements] = useState<WordReplacement[]>([]);
  // Note: clipboardHistory and inboxItems removed - features not yet implemented
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
    loadWorktrees();
    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
      if (currentSection === "worktrees") loadWorktrees();
      if (currentSection === "voice" && voiceView === "history") loadHistory();
    }, 2000);
    return () => clearInterval(interval);
  }, [currentSection, voiceView]);

  async function loadWordReplacements() {
    try {
      const result = await invoke<WordReplacement[]>("get_word_replacements");
      setWordReplacements(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadWorktrees() {
    try {
      const result = await invoke<WorktreeInfo[]>("get_worktrees");
      setWorktrees(result);
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

  async function handleResumeSession(worktree: WorktreeInfo) {
    try {
      await invoke("resume_session", {
        path: worktree.path,
        sessionId: worktree.session_id,
      });
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

  // === RENDER FUNCTIONS ===

  function renderSidebar() {
    return (
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">SYNTHIA</div>
        </div>
        <nav className="sidebar-nav">
          <button
            className={`nav-item ${currentSection === "worktrees" ? "active" : ""}`}
            onClick={() => setCurrentSection("worktrees")}
          >
            <span className="nav-item-icon">&#128193;</span>
            Worktrees
          </button>
          <button
            className={`nav-item ${currentSection === "voice" ? "active" : ""}`}
            onClick={() => { setCurrentSection("voice"); setVoiceView("main"); }}
          >
            <span className="nav-item-icon">&#127908;</span>
            Voice
          </button>
          <button
            className={`nav-item ${currentSection === "memory" ? "active" : ""}`}
            onClick={() => setCurrentSection("memory")}
          >
            <span className="nav-item-icon">&#128218;</span>
            Memory
          </button>
          <button
            className={`nav-item ${currentSection === "config" ? "active" : ""}`}
            onClick={() => setCurrentSection("config")}
          >
            <span className="nav-item-icon">&#9881;</span>
            Config
          </button>
        </nav>
      </div>
    );
  }

  function renderWorktreesSection() {
    function getProgressInfo(tasks: WorktreeTask[]) {
      const completed = tasks.filter(t => t.status === "completed").length;
      const inProgress = tasks.filter(t => t.status === "in_progress").length;
      const total = tasks.length;

      if (total === 0) return { text: "No tasks", percent: 0, status: "none" as const };
      if (completed === total) return { text: `${completed}/${total}`, percent: 100, status: "completed" as const };
      if (inProgress > 0 || completed > 0) return { text: `${completed}/${total}`, percent: (completed / total) * 100, status: "in-progress" as const };
      return { text: `0/${total}`, percent: 0, status: "none" as const };
    }

    function getDisplayName(path: string) {
      return path.split('/').pop() || path;
    }

    return (
      <div className="worktrees-layout">
        <div className="worktrees-list">
          {worktrees.length === 0 ? (
            <div className="empty-state">
              <p>No worktrees configured</p>
              <p style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                Add repos to ~/.config/synthia/worktrees.yaml
              </p>
            </div>
          ) : (
            worktrees.map((wt) => {
              const progress = getProgressInfo(wt.tasks);
              return (
                <div
                  key={wt.path}
                  className={`worktree-item ${selectedWorktree?.path === wt.path ? "selected" : ""}`}
                  onClick={() => setSelectedWorktree(wt)}
                >
                  <div className="worktree-branch">{getDisplayName(wt.path)}</div>
                  <div className="worktree-path">{wt.branch}</div>
                  <div className="worktree-meta">
                    {wt.issue_number && (
                      <span className="worktree-issue">#{wt.issue_number}</span>
                    )}
                    <div className="worktree-progress">
                      <div className="progress-bar">
                        <div
                          className={`progress-fill ${progress.status}`}
                          style={{ width: `${progress.percent}%` }}
                        />
                      </div>
                      <span>{progress.text}</span>
                    </div>
                  </div>
                </div>
              );
            })
          )}
        </div>

        {selectedWorktree && (
          <div className="task-panel">
            <div className="task-panel-header">
              <span className="task-panel-title">Tasks</span>
              <div className="task-panel-actions">
                <button
                  className="task-panel-btn primary"
                  onClick={() => handleResumeSession(selectedWorktree)}
                >
                  Resume
                </button>
              </div>
            </div>

            {selectedWorktree.tasks.length === 0 ? (
              <div className="empty-state">No tasks</div>
            ) : (
              <div className="task-list">
                {selectedWorktree.tasks.map((task) => (
                  <div
                    key={task.id}
                    className={`task-item ${task.blocked_by.length > 0 ? "blocked" : ""}`}
                  >
                    <span className={`task-status ${task.status.replace("_", "-")}`}>
                      {task.status === "completed" ? "✓" : task.status === "in_progress" ? "▶" : "○"}
                    </span>
                    <div className="task-content">
                      <div className="task-subject">{task.subject}</div>
                      {task.blocked_by.length > 0 && (
                        <div className="task-blocked-by">
                          blocked by #{task.blocked_by.join(", #")}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    );
  }

  function renderVoiceSection() {
    // History sub-view
    if (voiceView === "history") {
      return (
        <div className="voice-section">
          <div className="header history-view-header">
            <button className="back-btn" onClick={() => setVoiceView("main")}>
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
        </div>
      );
    }

    // Words sub-view
    if (voiceView === "words") {
      return (
        <div className="voice-section">
          <div className="header history-view-header">
            <button className="back-btn" onClick={() => setVoiceView("main")}>
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
        </div>
      );
    }

    // Main voice view
    return (
      <div className="voice-section">
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
          onClick={() => { setVoiceView("history"); loadHistory(); }}
        >
          <span>Voice History</span>
          {history.length > 0 && <span className="history-count">{history.length}</span>}
        </button>

        <button
          className="history-nav-btn"
          onClick={() => { setVoiceView("words"); loadWordReplacements(); }}
        >
          <span>Word Dictionary</span>
          {wordReplacements.length > 0 && <span className="history-count">{wordReplacements.length}</span>}
        </button>

        {error && <div className="error">{error}</div>}
      </div>
    );
  }

  function renderMemorySection() {
    return (
      <div className="empty-state" style={{ marginTop: "4rem" }}>
        <p style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>Memory</p>
        <p>Coming soon - manage bugs, patterns, gotchas, and stack knowledge</p>
      </div>
    );
  }

  function renderConfigSection() {
    return (
      <div className="empty-state" style={{ marginTop: "4rem" }}>
        <p style={{ fontSize: "1.2rem", marginBottom: "0.5rem" }}>Config</p>
        <p>Coming soon - agents, commands, plugins, hooks, settings</p>
      </div>
    );
  }

  return (
    <div className="app-layout">
      {renderSidebar()}
      <main className="main-content">
        {currentSection === "worktrees" && renderWorktreesSection()}
        {currentSection === "voice" && renderVoiceSection()}
        {currentSection === "memory" && renderMemorySection()}
        {currentSection === "config" && renderConfigSection()}
      </main>
    </div>
  );
}

export default App;
