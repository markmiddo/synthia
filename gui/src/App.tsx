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

interface ClipboardEntry {
  id: number;
  content: string;
  timestamp: string;
  hash: string;
}

interface InboxItem {
  id: string;
  type: "file" | "url" | "image";
  filename: string;
  path?: string;
  url?: string;
  received_at: string;
  size_bytes?: number;
  from_user?: string;
  opened: boolean;
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
  const [clipboardHistory, setClipboardHistory] = useState<ClipboardEntry[]>([]);
  const [inboxItems, setInboxItems] = useState<InboxItem[]>([]);
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
    loadClipboardHistory();
    loadInboxItems();
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

  async function loadClipboardHistory() {
    try {
      const result = await invoke<ClipboardEntry[]>("get_clipboard_history");
      setClipboardHistory(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleCopyFromHistory(content: string) {
    try {
      await invoke("copy_from_clipboard_history", { content });
      // Show brief feedback by setting copied state
      setCopiedId(-1); // Use -1 to indicate clipboard copy
      setTimeout(() => setCopiedId(null), 1500);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadInboxItems() {
    try {
      const result = await invoke<InboxItem[]>("get_inbox_items");
      setInboxItems(result);
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

  async function handleOpenInboxItem(item: InboxItem) {
    try {
      await invoke("open_inbox_item", {
        id: item.id,
        itemType: item.type,
        path: item.path,
        url: item.url,
      });
      // Reload to reflect opened status
      loadInboxItems();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteInboxItem(id: string) {
    try {
      await invoke("delete_inbox_item", { id });
      setInboxItems(inboxItems.filter((i) => i.id !== id));
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleClearInbox() {
    try {
      await invoke("clear_inbox");
      setInboxItems([]);
    } catch (e) {
      setError(String(e));
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

  // Clipboard History View
  if (currentView === "clipboard") {
    return (
      <main className="container">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setCurrentView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">CLIPBOARD</div>
        </div>

        <div className="clipboard-view-content">
          <p className="clipboard-description">
            Recent clipboard items. Click to copy back to clipboard.
          </p>

          <div className="clipboard-list">
            {clipboardHistory.length === 0 ? (
              <div className="clipboard-empty-state">
                <p>No clipboard history yet</p>
                <p className="empty-hint">Copy something to see it here</p>
              </div>
            ) : (
              clipboardHistory.map((entry) => (
                <div
                  key={entry.id}
                  className="clipboard-item"
                  onClick={() => handleCopyFromHistory(entry.content)}
                >
                  <div className="clipboard-content">
                    {entry.content.length > 100
                      ? entry.content.substring(0, 100) + "..."
                      : entry.content}
                  </div>
                  <div className="clipboard-meta">
                    <span className="clipboard-time">{formatTime(entry.timestamp)}</span>
                    <span className="clipboard-copy-hint">Click to copy</span>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {error && <div className="error">{error}</div>}
      </main>
    );
  }

  // Phone Inbox View
  if (currentView === "inbox") {
    return (
      <main className="container">
        <div className="header history-view-header">
          <button className="back-btn" onClick={() => setCurrentView("main")}>
            ← Back
          </button>
          <div className="logo-text-small">PHONE INBOX</div>
          {inboxItems.length > 0 && (
            <button className="clear-all-btn" onClick={handleClearInbox}>
              Clear All
            </button>
          )}
        </div>

        <div className="inbox-view-content">
          <p className="inbox-description">
            Files and links sent from your phone via Telegram.
          </p>

          <div className="inbox-list">
            {inboxItems.length === 0 ? (
              <div className="inbox-empty-state">
                <p>No items in inbox</p>
                <p className="empty-hint">Send files or URLs via Telegram to see them here</p>
              </div>
            ) : (
              inboxItems.map((item) => (
                <div
                  key={item.id}
                  className={`inbox-item ${item.type} ${item.opened ? "opened" : "unread"}`}
                >
                  <div className="inbox-item-icon">
                    {item.type === "url" ? "🔗" : item.type === "image" ? "🖼️" : "📄"}
                  </div>
                  <div className="inbox-item-info">
                    <span className="inbox-filename">{item.filename}</span>
                    <span className="inbox-meta">
                      {item.from_user && `From ${item.from_user} • `}
                      {formatTime(item.received_at)}
                    </span>
                  </div>
                  <div className="inbox-item-actions">
                    <button
                      className="inbox-open-btn"
                      onClick={() => handleOpenInboxItem(item)}
                    >
                      Open
                    </button>
                    <button
                      className="inbox-delete-btn"
                      onClick={() => handleDeleteInboxItem(item.id)}
                    >
                      ×
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        {error && <div className="error">{error}</div>}
      </main>
    );
  }

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

        <button
          className="history-nav-btn"
          onClick={() => { setCurrentView("clipboard"); loadClipboardHistory(); }}
        >
          <span>Clipboard</span>
          {clipboardHistory.length > 0 && <span className="history-count">{clipboardHistory.length}</span>}
        </button>

        <button
          className="history-nav-btn"
          onClick={() => { setCurrentView("inbox"); loadInboxItems(); }}
        >
          <span>Phone Inbox</span>
          {inboxItems.filter((i) => !i.opened).length > 0 && (
            <span className="history-count unread">{inboxItems.filter((i) => !i.opened).length}</span>
          )}
        </button>

        {error && <div className="error">{error}</div>}
      </div>
    </main>
  );
}

export default App;
