import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import Markdown from "react-markdown";
import "./App.css";

function DatePicker({ value, onChange }: { value: string; onChange: (val: string) => void }) {
  const [open, setOpen] = useState(false);
  const [viewDate, setViewDate] = useState(() => {
    if (value) {
      const [y, m] = value.split("-").map(Number);
      return { year: y, month: m - 1 };
    }
    const now = new Date();
    return { year: now.getFullYear(), month: now.getMonth() };
  });

  const today = new Date();
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;

  const daysInMonth = new Date(viewDate.year, viewDate.month + 1, 0).getDate();
  const firstDayOfWeek = new Date(viewDate.year, viewDate.month, 1).getDay();

  const monthNames = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  const prevMonth = () => {
    setViewDate((v) => v.month === 0
      ? { year: v.year - 1, month: 11 }
      : { year: v.year, month: v.month - 1 });
  };

  const nextMonth = () => {
    setViewDate((v) => v.month === 11
      ? { year: v.year + 1, month: 0 }
      : { year: v.year, month: v.month + 1 });
  };

  const selectDay = (day: number) => {
    const dateStr = `${viewDate.year}-${String(viewDate.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    onChange(dateStr);
    setOpen(false);
  };

  const handleToggle = () => {
    if (!open && value) {
      const [y, m] = value.split("-").map(Number);
      setViewDate({ year: y, month: m - 1 });
    }
    setOpen(!open);
  };

  const formatDisplay = (val: string) => {
    if (!val) return "";
    const [y, m, d] = val.split("-").map(Number);
    return `${monthNames[m - 1]} ${d}, ${y}`;
  };

  const days: (number | null)[] = [];
  for (let i = 0; i < firstDayOfWeek; i++) days.push(null);
  for (let d = 1; d <= daysInMonth; d++) days.push(d);

  return (
    <div className="datepicker-wrapper">
      <button type="button" className="datepicker-trigger" onClick={handleToggle}>
        <span className={value ? "datepicker-value" : "datepicker-placeholder"}>
          {value ? formatDisplay(value) : "Select date..."}
        </span>
        <span className="datepicker-icon">&#x25BC;</span>
      </button>
      {open && (
        <>
          <div className="datepicker-backdrop" onClick={() => setOpen(false)} />
          <div className="datepicker-dropdown">
            <div className="datepicker-header">
              <button type="button" className="datepicker-nav" onClick={prevMonth}>&lsaquo;</button>
              <span className="datepicker-month-label">
                {monthNames[viewDate.month]} {viewDate.year}
              </span>
              <button type="button" className="datepicker-nav" onClick={nextMonth}>&rsaquo;</button>
            </div>
            <div className="datepicker-weekdays">
              {["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"].map((d) => (
                <span key={d} className="datepicker-weekday">{d}</span>
              ))}
            </div>
            <div className="datepicker-grid">
              {days.map((day, i) => {
                if (day === null) return <span key={`empty-${i}`} className="datepicker-empty" />;
                const dateStr = `${viewDate.year}-${String(viewDate.month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
                const isSelected = dateStr === value;
                const isToday = dateStr === todayStr;
                return (
                  <button
                    key={day}
                    type="button"
                    className={`datepicker-day${isSelected ? " selected" : ""}${isToday ? " today" : ""}`}
                    onClick={() => selectDay(day)}
                  >
                    {day}
                  </button>
                );
              })}
            </div>
            {value && (
              <div className="datepicker-footer">
                <button
                  type="button"
                  className="datepicker-clear"
                  onClick={() => { onChange(""); setOpen(false); }}
                >
                  Clear
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const TAG_COLORS = [
  { bg: "rgba(6, 182, 212, 0.15)", text: "#06b6d4" },   // Cyan
  { bg: "rgba(168, 85, 247, 0.15)", text: "#a855f7" },   // Purple
  { bg: "rgba(34, 197, 94, 0.15)", text: "#22c55e" },    // Green
  { bg: "rgba(249, 115, 22, 0.15)", text: "#f97316" },   // Orange
  { bg: "rgba(236, 72, 153, 0.15)", text: "#ec4899" },   // Pink
  { bg: "rgba(59, 130, 246, 0.15)", text: "#3b82f6" },   // Blue
  { bg: "rgba(234, 179, 8, 0.15)", text: "#eab308" },    // Yellow
  { bg: "rgba(239, 68, 68, 0.15)", text: "#ef4444" },    // Red
];

function getTagColor(tag: string) {
  let hash = 0;
  for (let i = 0; i < tag.length; i++) {
    hash = ((hash << 5) - hash + tag.charCodeAt(i)) | 0;
  }
  return TAG_COLORS[Math.abs(hash) % TAG_COLORS.length];
}

function TagInput({ tags, onChange }: { tags: string[]; onChange: (tags: string[]) => void }) {
  const [input, setInput] = useState("");

  const addTag = (val: string) => {
    const trimmed = val.trim();
    if (trimmed && !tags.includes(trimmed)) {
      onChange([...tags, trimmed]);
    }
    setInput("");
  };

  const removeTag = (index: number) => {
    onChange(tags.filter((_, i) => i !== index));
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      addTag(input);
    } else if (e.key === "Backspace" && !input && tags.length > 0) {
      removeTag(tags.length - 1);
    }
  };

  return (
    <div className="tag-input-container">
      {tags.map((tag, i) => {
        const color = getTagColor(tag);
        return (
          <span key={tag} className="tag-chip" style={{ background: color.bg, color: color.text }}>
            {tag}
            <button type="button" className="tag-chip-remove" style={{ color: color.text }} onClick={() => removeTag(i)}>
              &times;
            </button>
          </span>
        );
      })}
      <input
        type="text"
        className="tag-input-field"
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={() => { if (input.trim()) addTag(input); }}
        placeholder={tags.length === 0 ? "Add tags..." : ""}
      />
    </div>
  );
}

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
  activeForm?: string;
  blockedBy: string[];
}

interface MemoryEntry {
  category: string;
  data: Record<string, string>;
  tags: string[];
  date?: string;
  line_number: number;
}

interface MemoryStats {
  total: number;
  categories: Record<string, number>;
  tags: [string, number][];
}

interface SynthiaConfig {
  use_local_stt: boolean;
  use_local_llm: boolean;
  use_local_tts: boolean;
  local_stt_model: string;
  local_llm_model: string;
  local_tts_voice: string;
  assistant_model: string;
  tts_voice: string;
  tts_speed: number;
  conversation_memory: number;
  show_notifications: boolean;
  play_sound_on_record: boolean;
}

interface AgentConfig {
  filename: string;
  name: string;
  description: string;
  model: string;
  color: string;
  body: string;
}

interface CommandConfig {
  filename: string;
  description: string;
  body: string;
}

interface HookConfig {
  event: string;
  command: string;
  timeout: number;
  hook_type: string;
}

interface PluginInfo {
  name: string;
  version: string;
  enabled: boolean;
}

interface WorktreeInfo {
  path: string;
  branch: string;
  repo_name: string;
  issue_number?: number;
  session_id?: string;
  tasks: WorktreeTask[];
  completed_tasks: WorktreeTask[];
  status?: string;
}

const WORKTREE_STATUSES = ["in-progress", "reviewing", "merged", "ready-to-close"] as const;

type Section = "worktrees" | "notes" | "tasks" | "voice" | "memory" | "config";

interface NoteEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

interface Task {
  id: string;
  title: string;
  description?: string;
  status: "todo" | "in_progress" | "done";
  tags: string[];
  due_date?: string;
  created_at: string;
  completed_at?: string;
}
type VoiceView = "main" | "history" | "words";
type MemoryCategory = "bug" | "pattern" | "arch" | "gotcha" | "stack" | null;
type ConfigTab = "synthia" | "agents" | "commands" | "hooks" | "plugins";

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

  // Memory state
  const [memoryStats, setMemoryStats] = useState<MemoryStats | null>(null);
  const [memoryEntries, setMemoryEntries] = useState<MemoryEntry[]>([]);
  const [memoryFilter, setMemoryFilter] = useState<MemoryCategory>(null);
  const [memorySearch, setMemorySearch] = useState("");
  const [selectedMemory, setSelectedMemory] = useState<MemoryEntry | null>(null);
  const [editingMemory, setEditingMemory] = useState<MemoryEntry | null>(null);
  const [editData, setEditData] = useState<Record<string, string>>({});
  const [editTags, setEditTags] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<MemoryEntry | null>(null);

  // Config state
  const [synthiaConfig, setSynthiaConfig] = useState<SynthiaConfig | null>(null);
  const [worktreeRepos, setWorktreeRepos] = useState<string[]>([]);
  const [newRepoPath, setNewRepoPath] = useState("");
  const [configSaving, setConfigSaving] = useState(false);
  const [configSaved, setConfigSaved] = useState(false);
  const [configTab, setConfigTab] = useState<ConfigTab>("synthia");

  // Claude config state
  const [agents, setAgents] = useState<AgentConfig[]>([]);
  const [commands, setCommands] = useState<CommandConfig[]>([]);
  const [hooks, setHooks] = useState<HookConfig[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
  const [editingCommand, setEditingCommand] = useState<CommandConfig | null>(null);
  const [isNewAgent, setIsNewAgent] = useState(false);
  const [isNewCommand, setIsNewCommand] = useState(false);

  // Notes state
  const [notesPath, setNotesPath] = useState<string[]>([]);
  const [noteEntries, setNoteEntries] = useState<NoteEntry[]>([]);
  const [selectedNote, setSelectedNote] = useState<string | null>(null);
  const [noteContent, setNoteContent] = useState("");
  const [noteEditing, setNoteEditing] = useState(false);
  const [noteSaving, setNoteSaving] = useState(false);
  const [noteSaved, setNoteSaved] = useState(false);
  const [showNewNote, setShowNewNote] = useState(false);
  const [newNoteName, setNewNoteName] = useState("");
  const [editingNoteName, setEditingNoteName] = useState(false);
  const [noteNameInput, setNoteNameInput] = useState("");
  const [notePreview, setNotePreview] = useState(false);

  // Tasks state
  const [tasks, setTasks] = useState<Task[]>([]);
  const [showAddTask, setShowAddTask] = useState(false);
  const [editingTask, setEditingTask] = useState<Task | null>(null);
  const [newTaskTitle, setNewTaskTitle] = useState("");
  const [newTaskDesc, setNewTaskDesc] = useState("");
  const [newTaskTags, setNewTaskTags] = useState<string[]>([]);
  const [newTaskDue, setNewTaskDue] = useState("");
  const [draggedTaskId, setDraggedTaskId] = useState<string | null>(null);
  const [dragOverColumn, setDragOverColumn] = useState<string | null>(null);

  // Usage stats state
  const [usageStats, setUsageStats] = useState<{
    session_tokens: number;
    session_pct: number;
    session_resets_at: string;
    week_tokens: number;
    week_pct: number;
    week_resets_at: string;
    sonnet_week_tokens: number;
    sonnet_week_pct: number;
    subscription_type: string;
  } | null>(null);

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
    loadUsageStats();
    if (currentSection === "memory") {
      loadMemoryStats();
      loadMemoryEntries(memoryFilter);
    }

    if (currentSection === "config") {
      loadSynthiaConfig();
      loadWorktreeRepos();
      loadAgents();
      loadCommands();
      loadHooks();
      loadPlugins();
    }

    if (currentSection === "notes") {
      loadNotes(notesPath.join("/"));
    }

    if (currentSection === "tasks") {
      loadTasks();
    }

    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
      if (currentSection === "worktrees") loadWorktrees();
      if (currentSection === "voice" && voiceView === "history") loadHistory();
    }, 2000);
    return () => clearInterval(interval);
  }, [currentSection, voiceView, memoryFilter]);

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

  async function loadMemoryStats() {
    try {
      const result = await invoke<MemoryStats>("get_memory_stats");
      setMemoryStats(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadMemoryEntries(category?: MemoryCategory) {
    try {
      const result = await invoke<MemoryEntry[]>("get_memory_entries", {
        category: category || null,
      });
      setMemoryEntries(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleMemorySearch() {
    if (!memorySearch.trim()) {
      loadMemoryEntries(memoryFilter);
      return;
    }
    try {
      const result = await invoke<MemoryEntry[]>("search_memory", {
        query: memorySearch,
      });
      setMemoryEntries(result);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleUpdateMemory(entry: MemoryEntry, newData: Record<string, string>, newTags: string[]) {
    try {
      await invoke("update_memory_entry", {
        category: entry.category,
        lineNumber: entry.line_number,
        data: newData,
        tags: newTags,
      });
      setEditingMemory(null);
      loadMemoryStats();
      loadMemoryEntries(memoryFilter);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteMemory(entry: MemoryEntry) {
    try {
      await invoke("delete_memory_entry", {
        category: entry.category,
        lineNumber: entry.line_number,
      });
      setDeleteConfirm(null);
      setSelectedMemory(null);
      loadMemoryStats();
      loadMemoryEntries(memoryFilter);
    } catch (e) {
      setError(String(e));
    }
  }

  function startEditingMemory(entry: MemoryEntry) {
    setEditingMemory(entry);
    setEditData({ ...entry.data });
    setEditTags(entry.tags.join(", "));
  }

  function cancelEditingMemory() {
    setEditingMemory(null);
    setEditData({});
    setEditTags("");
  }

  async function loadSynthiaConfig() {
    try {
      const result = await invoke<SynthiaConfig>("get_synthia_config");
      setSynthiaConfig(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadWorktreeRepos() {
    try {
      const result = await invoke<string[]>("get_worktree_repos");
      setWorktreeRepos(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadAgents() {
    try {
      const result = await invoke<AgentConfig[]>("list_agents");
      setAgents(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadCommands() {
    try {
      const result = await invoke<CommandConfig[]>("list_commands");
      setCommands(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadHooks() {
    try {
      const result = await invoke<HookConfig[]>("list_hooks");
      setHooks(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadPlugins() {
    try {
      const result = await invoke<PluginInfo[]>("list_plugins");
      setPlugins(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadNotes(subpath?: string) {
    try {
      const result = await invoke<NoteEntry[]>("list_notes", { subpath: subpath || "" });
      setNoteEntries(result);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleOpenNote(path: string) {
    try {
      const content = await invoke<string>("read_note", { path });
      setSelectedNote(path);
      setNoteContent(content);
      setNoteEditing(true);
      setNotePreview(false);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSaveNote() {
    if (!selectedNote) return;
    setNoteSaving(true);
    try {
      await invoke("save_note", { path: selectedNote, content: noteContent });
      setNoteSaving(false);
      setNoteSaved(true);
      setTimeout(() => setNoteSaved(false), 2000);
    } catch (e) {
      setError(String(e));
      setNoteSaving(false);
    }
  }

  function handleCloseNote() {
    setSelectedNote(null);
    setNoteContent("");
    setNoteEditing(false);
    setEditingNoteName(false);
    setNotePreview(false);
    // Refresh the notes list to show any new or updated notes
    loadNotes(notesPath.join("/"));
  }

  async function handleDeleteNote(path: string) {
    try {
      await invoke("delete_note", { path });
      if (selectedNote === path) {
        handleCloseNote();
      } else {
        loadNotes(notesPath.join("/"));
      }
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRenameNote() {
    if (!selectedNote || !noteNameInput.trim()) return;

    let newName = noteNameInput.trim();
    if (!newName.endsWith(".md")) {
      newName += ".md";
    }

    // Build new path with same directory
    const pathParts = selectedNote.split("/");
    pathParts.pop(); // Remove old filename
    const newPath = pathParts.length > 0
      ? `${pathParts.join("/")}/${newName}`
      : newName;

    if (newPath === selectedNote) {
      setEditingNoteName(false);
      return;
    }

    try {
      await invoke("rename_note", { oldPath: selectedNote, newPath });
      setSelectedNote(newPath);
      setEditingNoteName(false);
    } catch (e) {
      setError(String(e));
    }
  }

  function navigateToFolder(path: string) {
    const parts = path ? path.split("/").filter(Boolean) : [];
    setNotesPath(parts);
    loadNotes(path);
  }

  function navigateUp() {
    const newPath = notesPath.slice(0, -1);
    setNotesPath(newPath);
    loadNotes(newPath.join("/"));
  }

  async function handleCreateNote() {
    if (!newNoteName.trim()) return;

    // Ensure .md extension
    let filename = newNoteName.trim();
    if (!filename.endsWith(".md")) {
      filename += ".md";
    }

    // Build full path
    const fullPath = notesPath.length > 0
      ? `${notesPath.join("/")}/${filename}`
      : filename;

    try {
      // Create empty note
      await invoke("save_note", { path: fullPath, content: "" });

      // Reset modal state
      setShowNewNote(false);
      setNewNoteName("");

      // Open the new note for editing
      setSelectedNote(fullPath);
      setNoteContent("");
      setNoteEditing(true);
      setNotePreview(false);
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadUsageStats() {
    try {
      const result = await invoke<typeof usageStats>("get_usage_stats");
      setUsageStats(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadTasks() {
    try {
      const result = await invoke<Task[]>("list_tasks");
      setTasks(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function handleAddTask() {
    if (!newTaskTitle.trim()) return;
    try {
      await invoke("add_task", {
        title: newTaskTitle,
        description: newTaskDesc || null,
        tags: newTaskTags,
        dueDate: newTaskDue || null,
      });
      setNewTaskTitle("");
      setNewTaskDesc("");
      setNewTaskTags([]);
      setNewTaskDue("");
      setShowAddTask(false);
      loadTasks();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleUpdateTask() {
    if (!editingTask) return;
    try {
      await invoke("update_task", {
        id: editingTask.id,
        title: editingTask.title,
        description: editingTask.description || null,
        tags: editingTask.tags,
        dueDate: editingTask.due_date || null,
        status: editingTask.status,
      });
      setEditingTask(null);
      loadTasks();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleMoveTask(id: string, status: string) {
    try {
      await invoke("move_task", { id, status });
      loadTasks();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteTask(id: string) {
    try {
      await invoke("delete_task", { id });
      loadTasks();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSaveAgent(agent: AgentConfig) {
    try {
      await invoke("save_agent", { agent });
      setEditingAgent(null);
      setIsNewAgent(false);
      loadAgents();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteAgent(filename: string) {
    try {
      await invoke("delete_agent", { filename });
      loadAgents();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSaveCommand(command: CommandConfig) {
    try {
      await invoke("save_command", { command });
      setEditingCommand(null);
      setIsNewCommand(false);
      loadCommands();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteCommand(filename: string) {
    try {
      await invoke("delete_command", { filename });
      loadCommands();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleTogglePlugin(name: string, enabled: boolean) {
    try {
      await invoke("toggle_plugin", { name, enabled });
      loadPlugins();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleSaveConfig() {
    if (!synthiaConfig) return;
    setConfigSaving(true);
    setConfigSaved(false);
    try {
      await invoke("save_synthia_config", { config: synthiaConfig });
      setError(null);
      setConfigSaved(true);
      setTimeout(() => setConfigSaved(false), 2000);
    } catch (e) {
      setError(String(e));
    }
    setConfigSaving(false);
  }

  async function handleAddRepo() {
    if (!newRepoPath.trim()) return;
    const updated = [...worktreeRepos, newRepoPath.trim()];
    try {
      await invoke("save_worktree_repos", { repos: updated });
      setWorktreeRepos(updated);
      setNewRepoPath("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRemoveRepo(index: number) {
    const updated = worktreeRepos.filter((_, i) => i !== index);
    try {
      await invoke("save_worktree_repos", { repos: updated });
      setWorktreeRepos(updated);
    } catch (e) {
      setError(String(e));
    }
  }

  function updateConfig<K extends keyof SynthiaConfig>(key: K, value: SynthiaConfig[K]) {
    if (!synthiaConfig) return;
    setSynthiaConfig({ ...synthiaConfig, [key]: value });
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

  async function handleSetWorktreeStatus(worktree: WorktreeInfo, status: string | null) {
    try {
      await invoke("set_worktree_status", {
        path: worktree.path,
        status: status,
      });
      // Refresh worktrees to show updated status
      const wts = await invoke<WorktreeInfo[]>("get_worktrees");
      setWorktrees(wts);
      // Update selected worktree if it's the one we changed
      if (selectedWorktree?.path === worktree.path) {
        const updated = wts.find(w => w.path === worktree.path);
        if (updated) setSelectedWorktree(updated);
      }
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

  function formatTokens(n: number): string {
    if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
    if (n >= 1000) return `${(n / 1000).toFixed(1)}K`;
    return n.toString();
  }

  function usageBarColor(pct: number): string {
    if (pct >= 80) return "#ef4444";
    if (pct >= 50) return "#eab308";
    return "#06b6d4";
  }

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
            className={`nav-item ${currentSection === "notes" ? "active" : ""}`}
            onClick={() => { setCurrentSection("notes"); loadNotes(notesPath.join("/")); }}
          >
            <span className="nav-item-icon">&#128221;</span>
            Notes
          </button>
          <button
            className={`nav-item ${currentSection === "tasks" ? "active" : ""}`}
            onClick={() => { setCurrentSection("tasks"); loadTasks(); }}
          >
            <span className="nav-item-icon">&#9745;</span>
            Tasks
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

        {usageStats && (
          <div className="usage-widget">
            <div className="usage-header">
              <span className="usage-title">Claude Usage</span>
              {usageStats.subscription_type && (
                <span className="usage-badge">{usageStats.subscription_type}</span>
              )}
            </div>
            <div className="usage-section">
              <div className="usage-label">Current session</div>
              <div className="usage-bar-row">
                <div className="usage-bar">
                  <div
                    className="usage-bar-fill"
                    style={{ width: `${usageStats.session_pct}%`, background: usageBarColor(usageStats.session_pct) }}
                  />
                </div>
                <span className="usage-pct">{Math.round(usageStats.session_pct)}%</span>
              </div>
              <div className="usage-details">
                <span className="usage-tokens">{formatTokens(usageStats.session_tokens)} tokens</span>
                {usageStats.session_resets_at && (
                  <span className="usage-reset">Resets {usageStats.session_resets_at}</span>
                )}
              </div>
            </div>
            <div className="usage-section">
              <div className="usage-label">Current week</div>
              <div className="usage-bar-row">
                <div className="usage-bar">
                  <div
                    className="usage-bar-fill"
                    style={{ width: `${usageStats.week_pct}%`, background: usageBarColor(usageStats.week_pct) }}
                  />
                </div>
                <span className="usage-pct">{Math.round(usageStats.week_pct)}%</span>
              </div>
              <div className="usage-details">
                <span className="usage-tokens">{formatTokens(usageStats.week_tokens)} tokens</span>
                {usageStats.week_resets_at && (
                  <span className="usage-reset">Resets {usageStats.week_resets_at}</span>
                )}
              </div>
            </div>
            <div className="usage-section">
              <div className="usage-label">Sonnet (weekly)</div>
              <div className="usage-bar-row">
                <div className="usage-bar">
                  <div
                    className="usage-bar-fill"
                    style={{ width: `${usageStats.sonnet_week_pct}%`, background: usageBarColor(usageStats.sonnet_week_pct) }}
                  />
                </div>
                <span className="usage-pct">{Math.round(usageStats.sonnet_week_pct)}%</span>
              </div>
              <div className="usage-details">
                <span className="usage-tokens">{formatTokens(usageStats.sonnet_week_tokens)} tokens</span>
                {usageStats.week_resets_at && (
                  <span className="usage-reset">Resets {usageStats.week_resets_at}</span>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  function renderWorktreesSection() {
    function getProgressInfo(tasks: WorktreeTask[], completedTasks: WorktreeTask[]) {
      const completed = tasks.filter(t => t.status === "completed").length;
      const inProgress = tasks.filter(t => t.status === "in_progress").length;
      const total = tasks.length;

      // If no active tasks but we have completed tasks from session history
      if (total === 0 && completedTasks.length > 0) {
        return { text: `${completedTasks.length} done`, percent: 100, status: "completed" as const };
      }
      if (total === 0) return { text: "No tasks", percent: 0, status: "none" as const };
      if (completed === total) return { text: `${completed}/${total}`, percent: 100, status: "completed" as const };
      if (inProgress > 0 || completed > 0) return { text: `${completed}/${total}`, percent: (completed / total) * 100, status: "in-progress" as const };
      return { text: `0/${total}`, percent: 0, status: "none" as const };
    }

    function getDisplayName(path: string) {
      return path.split('/').pop() || path;
    }

    function getRepoColorClass(repoName: string) {
      // Simple hash to get consistent color per repo
      let hash = 0;
      for (let i = 0; i < repoName.length; i++) {
        hash = repoName.charCodeAt(i) + ((hash << 5) - hash);
      }
      return `repo-${Math.abs(hash) % 8}`;
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
            [...worktrees]
              .sort((a, b) => {
                // Sort by activity: in_progress first, then completed, then no tasks
                const aInProgress = a.tasks.some(t => t.status === "in_progress");
                const bInProgress = b.tasks.some(t => t.status === "in_progress");
                if (aInProgress !== bInProgress) return aInProgress ? -1 : 1;

                const aHasTasks = a.tasks.length > 0 || a.completed_tasks.length > 0;
                const bHasTasks = b.tasks.length > 0 || b.completed_tasks.length > 0;
                if (aHasTasks !== bHasTasks) return aHasTasks ? -1 : 1;

                return 0;
              })
              .map((wt) => {
              const progress = getProgressInfo(wt.tasks, wt.completed_tasks);
              return (
                <div
                  key={wt.path}
                  className={`worktree-item ${selectedWorktree?.path === wt.path ? "selected" : ""}`}
                  onClick={() => setSelectedWorktree(wt)}
                >
                  <div className="worktree-header">
                    <div className="worktree-branch">{getDisplayName(wt.path)}</div>
                    <div className="worktree-badges">
                      {wt.status && (
                        <span className={`worktree-status ${wt.status}`}>
                          {wt.status.replace("-", " ")}
                        </span>
                      )}
                      <div className={`worktree-repo ${getRepoColorClass(wt.repo_name)}`}>{wt.repo_name}</div>
                    </div>
                  </div>
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

            <div className="status-selector">
              <span className="status-label">Status:</span>
              <div className="status-tags">
                {WORKTREE_STATUSES.map((s) => (
                  <button
                    key={s}
                    className={`status-tag ${s} ${selectedWorktree.status === s ? "active" : ""}`}
                    onClick={() => handleSetWorktreeStatus(
                      selectedWorktree,
                      selectedWorktree.status === s ? null : s
                    )}
                  >
                    {s.replace("-", " ")}
                  </button>
                ))}
              </div>
            </div>

            {selectedWorktree.tasks.length === 0 && selectedWorktree.completed_tasks.length === 0 ? (
              <div className="empty-state">No tasks</div>
            ) : selectedWorktree.tasks.length === 0 && selectedWorktree.completed_tasks.length > 0 ? (
              <div className="task-list">
                {selectedWorktree.completed_tasks.map((task) => (
                  <div key={task.id} className="task-item">
                    <span className="task-status completed">✓</span>
                    <div className="task-content">
                      <div className="task-subject">{task.subject}</div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="task-list">
                {selectedWorktree.tasks.map((task) => (
                  <div
                    key={task.id}
                    className={`task-item ${task.blockedBy.length > 0 ? "blocked" : ""}`}
                  >
                    <span className={`task-status ${task.status.replace("_", "-")}`}>
                      {task.status === "completed" ? "✓" : task.status === "in_progress" ? "▶" : "○"}
                    </span>
                    <div className="task-content">
                      <div className="task-subject">{task.subject}</div>
                      {task.blockedBy.length > 0 && (
                        <div className="task-blocked-by">
                          blocked by #{task.blockedBy.join(", #")}
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
    const categoryLabels: Record<string, string> = {
      bug: "BUG",
      pattern: "PATTERN",
      arch: "ARCH",
      gotcha: "GOTCHA",
      stack: "STACK",
    };

    const categoryFields: Record<string, string[]> = {
      bug: ["error", "cause", "fix"],
      pattern: ["topic", "rule", "why"],
      arch: ["decision", "why"],
      gotcha: ["area", "gotcha"],
      stack: ["tool", "note"],
    };

    function getEntryPreview(entry: MemoryEntry): string {
      const data = entry.data;
      if (entry.category === "bug") return data.error || "N/A";
      if (entry.category === "pattern") return data.topic || "N/A";
      if (entry.category === "arch") return data.decision || "N/A";
      if (entry.category === "gotcha") return data.area || "N/A";
      if (entry.category === "stack") return data.tool || "N/A";
      return "Unknown";
    }

    function renderDetail(entry: MemoryEntry) {
      const fields = categoryFields[entry.category] || [];
      return (
        <div className="memory-detail">
          {fields.map((field) => (
            <div key={field} className="memory-detail-field">
              <span className="memory-detail-label">{field}:</span>
              <span className="memory-detail-value">{entry.data[field] || "N/A"}</span>
            </div>
          ))}
          <div className="memory-detail-field">
            <span className="memory-detail-label">Tags:</span>
            <span className="memory-detail-value">{entry.tags.join(", ") || "None"}</span>
          </div>
        </div>
      );
    }

    // Edit modal
    if (editingMemory) {
      const fields = categoryFields[editingMemory.category] || [];

      return (
        <div className="memory-section">
          <div className="memory-modal">
            <div className="memory-modal-header">
              <span>Edit {categoryLabels[editingMemory.category]} Entry</span>
              <button className="memory-modal-close" onClick={cancelEditingMemory}>×</button>
            </div>
            <div className="memory-modal-body">
              {fields.map((field) => (
                <div key={field} className="memory-edit-field">
                  <label>{field}:</label>
                  <textarea
                    value={editData[field] || ""}
                    onChange={(e) => setEditData({ ...editData, [field]: e.target.value })}
                  />
                </div>
              ))}
              <div className="memory-edit-field">
                <label>Tags (comma-separated):</label>
                <input
                  type="text"
                  value={editTags}
                  onChange={(e) => setEditTags(e.target.value)}
                />
              </div>
            </div>
            <div className="memory-modal-footer">
              <button
                className="memory-btn primary"
                onClick={() => handleUpdateMemory(
                  editingMemory,
                  editData,
                  editTags.split(",").map((t) => t.trim()).filter(Boolean)
                )}
              >
                Save
              </button>
              <button className="memory-btn" onClick={cancelEditingMemory}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      );
    }

    // Delete confirmation modal
    if (deleteConfirm) {
      return (
        <div className="memory-section">
          <div className="memory-modal delete-modal">
            <div className="memory-modal-header">
              <span>Delete Entry?</span>
            </div>
            <div className="memory-modal-body">
              <p>Category: {categoryLabels[deleteConfirm.category]}</p>
              <p className="delete-preview">{getEntryPreview(deleteConfirm)}</p>
            </div>
            <div className="memory-modal-footer">
              <button
                className="memory-btn danger"
                onClick={() => handleDeleteMemory(deleteConfirm)}
              >
                Yes, Delete
              </button>
              <button className="memory-btn" onClick={() => setDeleteConfirm(null)}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="memory-section">
        <div className="memory-layout">
          {/* Stats Panel */}
          <div className="memory-stats-panel">
            <div className="memory-stats-title">Memory Statistics</div>
            {memoryStats && (
              <>
                <div className="memory-stats-content">
                  <div className="memory-stat-row">Total entries: {memoryStats.total}</div>
                  {Object.entries(memoryStats.categories).map(([cat, count]) => (
                    <div key={cat} className="memory-stat-row indent">
                      {cat}: {count}
                    </div>
                  ))}
                </div>
                <div className="memory-stats-title" style={{ marginTop: "1rem" }}>Popular Tags</div>
                <div className="memory-stats-content">
                  {memoryStats.tags.length === 0 ? (
                    <div className="memory-stat-row indent">No tags yet</div>
                  ) : (
                    memoryStats.tags.map(([tag, count]) => (
                      <div key={tag} className="memory-stat-row indent">
                        {tag} ({count})
                      </div>
                    ))
                  )}
                </div>
              </>
            )}
          </div>

          {/* Main Panel */}
          <div className="memory-main-panel">
            <div className="memory-search-row">
              <input
                type="text"
                placeholder="Search tags or text..."
                value={memorySearch}
                onChange={(e) => setMemorySearch(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleMemorySearch()}
                className="memory-search-input"
              />
              <button className="memory-btn" onClick={handleMemorySearch}>Search</button>
            </div>

            <div className="memory-filter-row">
              {(["bug", "pattern", "gotcha", "arch", "stack"] as MemoryCategory[]).map((cat) => (
                <button
                  key={cat}
                  className={`memory-filter-btn ${memoryFilter === cat ? "active" : ""}`}
                  onClick={() => {
                    setMemoryFilter(memoryFilter === cat ? null : cat);
                    setMemorySearch("");
                  }}
                >
                  {categoryLabels[cat!]}
                </button>
              ))}
              <button
                className={`memory-filter-btn ${memoryFilter === null ? "active" : ""}`}
                onClick={() => {
                  setMemoryFilter(null);
                  setMemorySearch("");
                  loadMemoryEntries(null);
                }}
              >
                All
              </button>
            </div>

            <div className="memory-list">
              {memoryEntries.length === 0 ? (
                <div className="memory-empty">No entries found</div>
              ) : (
                memoryEntries.map((entry, idx) => (
                  <div
                    key={`${entry.category}-${entry.line_number}-${idx}`}
                    className={`memory-item ${selectedMemory === entry ? "selected" : ""}`}
                    onClick={() => setSelectedMemory(entry)}
                  >
                    <span className={`memory-badge ${entry.category}`}>
                      {categoryLabels[entry.category]}
                    </span>
                    <span className="memory-preview">
                      {getEntryPreview(entry).slice(0, 60)}
                      {getEntryPreview(entry).length > 60 ? "..." : ""}
                    </span>
                  </div>
                ))
              )}
            </div>

            {/* Detail Panel */}
            <div className="memory-detail-panel">
              {selectedMemory ? (
                <>
                  {renderDetail(selectedMemory)}
                  <div className="memory-detail-actions">
                    <button
                      className="memory-btn"
                      onClick={() => startEditingMemory(selectedMemory)}
                    >
                      Edit
                    </button>
                    <button
                      className="memory-btn danger"
                      onClick={() => setDeleteConfirm(selectedMemory)}
                    >
                      Delete
                    </button>
                  </div>
                </>
              ) : (
                <div className="memory-detail-placeholder">
                  Select an entry to view details
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    );
  }

  function renderConfigSection() {
    // Agent edit modal
    if (editingAgent) {
      return (
        <div className="config-section">
          <div className="claude-modal">
            <div className="claude-modal-header">
              <span>{isNewAgent ? "New Agent" : `Edit: ${editingAgent.name}`}</span>
              <button className="claude-modal-close" onClick={() => { setEditingAgent(null); setIsNewAgent(false); }}>×</button>
            </div>
            <div className="claude-modal-body">
              <div className="claude-edit-field">
                <label>Name:</label>
                <input
                  type="text"
                  value={editingAgent.name}
                  onChange={(e) => setEditingAgent({ ...editingAgent, name: e.target.value })}
                />
              </div>
              <div className="claude-edit-field">
                <label>Description:</label>
                <input
                  type="text"
                  value={editingAgent.description}
                  onChange={(e) => setEditingAgent({ ...editingAgent, description: e.target.value })}
                />
              </div>
              <div className="claude-edit-row">
                <div className="claude-edit-field">
                  <label>Model:</label>
                  <select
                    value={editingAgent.model}
                    onChange={(e) => setEditingAgent({ ...editingAgent, model: e.target.value })}
                  >
                    <option value="sonnet">Sonnet</option>
                    <option value="opus">Opus</option>
                    <option value="haiku">Haiku</option>
                  </select>
                </div>
                <div className="claude-edit-field">
                  <label>Color:</label>
                  <select
                    value={editingAgent.color}
                    onChange={(e) => setEditingAgent({ ...editingAgent, color: e.target.value })}
                  >
                    {["green", "blue", "red", "yellow", "purple", "orange", "cyan", "magenta"].map(c => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="claude-edit-field">
                <label>Content:</label>
                <textarea
                  value={editingAgent.body}
                  onChange={(e) => setEditingAgent({ ...editingAgent, body: e.target.value })}
                  rows={12}
                />
              </div>
            </div>
            <div className="claude-modal-footer">
              <button
                className="claude-btn primary"
                onClick={() => {
                  const filename = isNewAgent ? `${editingAgent.name}.md` : editingAgent.filename;
                  handleSaveAgent({ ...editingAgent, filename });
                }}
              >
                Save
              </button>
              <button className="claude-btn" onClick={() => { setEditingAgent(null); setIsNewAgent(false); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      );
    }

    // Command edit modal
    if (editingCommand) {
      return (
        <div className="config-section">
          <div className="claude-modal">
            <div className="claude-modal-header">
              <span>{isNewCommand ? "New Command" : `Edit: /${editingCommand.filename.replace(".md", "")}`}</span>
              <button className="claude-modal-close" onClick={() => { setEditingCommand(null); setIsNewCommand(false); }}>×</button>
            </div>
            <div className="claude-modal-body">
              <div className="claude-edit-field">
                <label>Name (without .md):</label>
                <input
                  type="text"
                  value={editingCommand.filename.replace(".md", "")}
                  onChange={(e) => setEditingCommand({ ...editingCommand, filename: `${e.target.value}.md` })}
                />
              </div>
              <div className="claude-edit-field">
                <label>Description:</label>
                <input
                  type="text"
                  value={editingCommand.description}
                  onChange={(e) => setEditingCommand({ ...editingCommand, description: e.target.value })}
                />
              </div>
              <div className="claude-edit-field">
                <label>Content:</label>
                <textarea
                  value={editingCommand.body}
                  onChange={(e) => setEditingCommand({ ...editingCommand, body: e.target.value })}
                  rows={12}
                />
              </div>
            </div>
            <div className="claude-modal-footer">
              <button
                className="claude-btn primary"
                onClick={() => handleSaveCommand(editingCommand)}
              >
                Save
              </button>
              <button className="claude-btn" onClick={() => { setEditingCommand(null); setIsNewCommand(false); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      );
    }

    return (
      <div className="config-section">
        {/* Config Tabs */}
        <div className="config-tabs">
          <button
            className={`config-tab ${configTab === "synthia" ? "active" : ""}`}
            onClick={() => setConfigTab("synthia")}
          >
            Synthia
          </button>
          <button
            className={`config-tab ${configTab === "agents" ? "active" : ""}`}
            onClick={() => setConfigTab("agents")}
          >
            Agents
          </button>
          <button
            className={`config-tab ${configTab === "commands" ? "active" : ""}`}
            onClick={() => setConfigTab("commands")}
          >
            Commands
          </button>
          <button
            className={`config-tab ${configTab === "hooks" ? "active" : ""}`}
            onClick={() => setConfigTab("hooks")}
          >
            Hooks
          </button>
          <button
            className={`config-tab ${configTab === "plugins" ? "active" : ""}`}
            onClick={() => setConfigTab("plugins")}
          >
            Plugins
          </button>
        </div>

        {/* Synthia Tab */}
        {configTab === "synthia" && (
          <div className="config-layout">
            <div className="config-panel">
              <div className="config-panel-title">Synthia Settings</div>

              {synthiaConfig ? (
                <>
                  <div className="config-group">
                    <div className="config-group-title">Processing Mode</div>

                    <div className="config-toggle-row">
                      <span>Speech-to-Text</span>
                      <div className="config-toggle-group">
                        <button
                          className={`config-toggle-btn ${!synthiaConfig.use_local_stt ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_stt", false)}
                        >
                          Cloud
                        </button>
                        <button
                          className={`config-toggle-btn ${synthiaConfig.use_local_stt ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_stt", true)}
                        >
                          Local
                        </button>
                      </div>
                    </div>

                    <div className="config-toggle-row">
                      <span>AI Assistant</span>
                      <div className="config-toggle-group">
                        <button
                          className={`config-toggle-btn ${!synthiaConfig.use_local_llm ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_llm", false)}
                        >
                          Cloud
                        </button>
                        <button
                          className={`config-toggle-btn ${synthiaConfig.use_local_llm ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_llm", true)}
                        >
                          Local
                        </button>
                      </div>
                    </div>

                    <div className="config-toggle-row">
                      <span>Text-to-Speech</span>
                      <div className="config-toggle-group">
                        <button
                          className={`config-toggle-btn ${!synthiaConfig.use_local_tts ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_tts", false)}
                        >
                          Cloud
                        </button>
                        <button
                          className={`config-toggle-btn ${synthiaConfig.use_local_tts ? "active" : ""}`}
                          onClick={() => updateConfig("use_local_tts", true)}
                        >
                          Local
                        </button>
                      </div>
                    </div>
                  </div>

                  <div className="config-group">
                    <div className="config-group-title">Models</div>

                    <div className="config-field">
                      <label>Local STT Model</label>
                      <select
                        value={synthiaConfig.local_stt_model}
                        onChange={(e) => updateConfig("local_stt_model", e.target.value)}
                      >
                        <option value="tiny">Tiny (fastest)</option>
                        <option value="base">Base</option>
                        <option value="small">Small</option>
                        <option value="medium">Medium</option>
                        <option value="large">Large (best)</option>
                      </select>
                    </div>

                    <div className="config-field">
                      <label>Local LLM Model</label>
                      <input
                        type="text"
                        value={synthiaConfig.local_llm_model}
                        onChange={(e) => updateConfig("local_llm_model", e.target.value)}
                        placeholder="e.g., qwen2.5:7b-instruct-q4_0"
                      />
                    </div>

                    <div className="config-field">
                      <label>Cloud Assistant Model</label>
                      <input
                        type="text"
                        value={synthiaConfig.assistant_model}
                        onChange={(e) => updateConfig("assistant_model", e.target.value)}
                        placeholder="e.g., claude-sonnet-4-20250514"
                      />
                    </div>
                  </div>

                  <div className="config-group">
                    <div className="config-group-title">Other Settings</div>

                    <div className="config-field">
                      <label>TTS Speed</label>
                      <input
                        type="number"
                        value={synthiaConfig.tts_speed}
                        onChange={(e) => updateConfig("tts_speed", parseFloat(e.target.value) || 1.0)}
                        step="0.1"
                        min="0.5"
                        max="2.0"
                      />
                    </div>

                    <div className="config-field">
                      <label>Conversation Memory</label>
                      <input
                        type="number"
                        value={synthiaConfig.conversation_memory}
                        onChange={(e) => updateConfig("conversation_memory", parseInt(e.target.value) || 10)}
                        min="1"
                        max="50"
                      />
                    </div>

                    <div className="config-checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          checked={synthiaConfig.show_notifications}
                          onChange={(e) => updateConfig("show_notifications", e.target.checked)}
                        />
                        Show notifications
                      </label>
                    </div>

                    <div className="config-checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          checked={synthiaConfig.play_sound_on_record}
                          onChange={(e) => updateConfig("play_sound_on_record", e.target.checked)}
                        />
                        Play sound when recording
                      </label>
                    </div>
                  </div>

                  <button
                    className={`config-save-btn ${configSaved ? "saved" : ""}`}
                    onClick={handleSaveConfig}
                    disabled={configSaving}
                  >
                    {configSaving ? "Saving..." : configSaved ? "Saved!" : "Save Settings"}
                  </button>
                </>
              ) : (
                <div className="config-loading">Loading...</div>
              )}
            </div>

            <div className="config-panel">
              <div className="config-panel-title">Worktree Repositories</div>
              <p className="config-description">
                Git repositories to scan for worktrees in the Worktrees tab.
              </p>

              <div className="config-repo-add">
                <input
                  type="text"
                  value={newRepoPath}
                  onChange={(e) => setNewRepoPath(e.target.value)}
                  placeholder="/path/to/git/repo"
                  onKeyDown={(e) => e.key === "Enter" && handleAddRepo()}
                />
                <button onClick={handleAddRepo}>Add</button>
              </div>

              <div className="config-repo-list">
                {worktreeRepos.length === 0 ? (
                  <div className="config-repo-empty">No repositories configured</div>
                ) : (
                  worktreeRepos.map((repo, index) => (
                    <div key={index} className="config-repo-item">
                      <span className="config-repo-path">{repo}</span>
                      <button
                        className="config-repo-remove"
                        onClick={() => handleRemoveRepo(index)}
                      >
                        ×
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        {/* Agents Tab */}
        {configTab === "agents" && (
          <div className="claude-list-section">
            <div className="claude-list-header">
              <span>Agents ({agents.length})</span>
              <button
                className="claude-btn primary"
                onClick={() => {
                  setEditingAgent({
                    filename: "new-agent.md",
                    name: "new-agent",
                    description: "",
                    model: "sonnet",
                    color: "green",
                    body: "",
                  });
                  setIsNewAgent(true);
                }}
              >
                + New Agent
              </button>
            </div>
            <div className="claude-list">
              {agents.length === 0 ? (
                <div className="claude-empty">No agents configured</div>
              ) : (
                agents.map((agent) => (
                  <div key={agent.filename} className="claude-item">
                    <div className="claude-item-main">
                      <span className={`claude-item-color ${agent.color}`}></span>
                      <div className="claude-item-info">
                        <div className="claude-item-name">{agent.name}</div>
                        <div className="claude-item-desc">{agent.description || "No description"}</div>
                      </div>
                      <span className="claude-item-model">{agent.model}</span>
                    </div>
                    <div className="claude-item-actions">
                      <button className="claude-btn" onClick={() => setEditingAgent(agent)}>Edit</button>
                      <button className="claude-btn danger" onClick={() => handleDeleteAgent(agent.filename)}>Delete</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Commands Tab */}
        {configTab === "commands" && (
          <div className="claude-list-section">
            <div className="claude-list-header">
              <span>Commands ({commands.length})</span>
              <button
                className="claude-btn primary"
                onClick={() => {
                  setEditingCommand({
                    filename: "new-command.md",
                    description: "",
                    body: "",
                  });
                  setIsNewCommand(true);
                }}
              >
                + New Command
              </button>
            </div>
            <div className="claude-list">
              {commands.length === 0 ? (
                <div className="claude-empty">No commands configured</div>
              ) : (
                commands.map((cmd) => (
                  <div key={cmd.filename} className="claude-item">
                    <div className="claude-item-main">
                      <div className="claude-item-info">
                        <div className="claude-item-name">/{cmd.filename.replace(".md", "")}</div>
                        <div className="claude-item-desc">{cmd.description || "No description"}</div>
                      </div>
                    </div>
                    <div className="claude-item-actions">
                      <button className="claude-btn" onClick={() => setEditingCommand(cmd)}>Edit</button>
                      <button className="claude-btn danger" onClick={() => handleDeleteCommand(cmd.filename)}>Delete</button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* Hooks Tab */}
        {configTab === "hooks" && (
          <div className="claude-list-section">
            <div className="claude-list-header">
              <span>Hooks ({hooks.length})</span>
            </div>
            <div className="claude-list">
              {hooks.length === 0 ? (
                <div className="claude-empty">No hooks configured</div>
              ) : (
                hooks.map((hook, idx) => (
                  <div key={`${hook.event}-${idx}`} className="claude-item">
                    <div className="claude-item-main">
                      <div className="claude-item-info">
                        <div className="claude-item-name">{hook.event}</div>
                        <div className="claude-item-desc claude-item-command">{hook.command}</div>
                      </div>
                      <span className="claude-item-model">{hook.timeout}s</span>
                    </div>
                  </div>
                ))
              )}
            </div>
            <p className="claude-note">Edit hooks in ~/.claude/settings.json</p>
          </div>
        )}

        {/* Plugins Tab */}
        {configTab === "plugins" && (
          <div className="claude-list-section">
            <div className="claude-list-header">
              <span>Plugins ({plugins.length})</span>
            </div>
            <div className="claude-list">
              {plugins.length === 0 ? (
                <div className="claude-empty">No plugins installed</div>
              ) : (
                plugins.map((plugin) => (
                  <div key={plugin.name} className="claude-item">
                    <div className="claude-item-main">
                      <div className="claude-item-info">
                        <div className="claude-item-name">{plugin.name.split("@")[0]}</div>
                        <div className="claude-item-desc">{plugin.version || "No version"}</div>
                      </div>
                      <button
                        className={`toggle ${plugin.enabled ? "active" : ""}`}
                        onClick={() => handleTogglePlugin(plugin.name, !plugin.enabled)}
                      >
                        <div className="toggle-knob" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {error && <div className="error">{error}</div>}
      </div>
    );
  }

  function renderTasksSection() {
    const todoTasks = tasks.filter(t => t.status === "todo");
    const inProgressTasks = tasks.filter(t => t.status === "in_progress");
    const doneTasks = tasks.filter(t => t.status === "done");

    function formatDate(dateStr?: string) {
      if (!dateStr) return null;
      const date = new Date(dateStr);
      return date.toLocaleDateString("en-AU", { day: "numeric", month: "short" });
    }

    function isOverdue(dueDate?: string) {
      if (!dueDate) return false;
      return new Date(dueDate) < new Date();
    }

    function renderTaskCard(task: Task) {
      return (
        <div
          key={task.id}
          className={`task-card ${draggedTaskId === task.id ? "dragging" : ""}`}
          onClick={() => setEditingTask(task)}
          draggable
          onDragStart={(e) => {
            setDraggedTaskId(task.id);
            e.dataTransfer.effectAllowed = "move";
            e.dataTransfer.setData("text/plain", task.id);
          }}
          onDragEnd={() => { setDraggedTaskId(null); setDragOverColumn(null); }}
        >
          <div className="task-card-title">{task.title}</div>
          {task.description && (
            <div className="task-card-desc">{task.description}</div>
          )}
          <div className="task-card-meta">
            {task.due_date && (
              <span className={`task-due ${isOverdue(task.due_date) && task.status !== "done" ? "overdue" : ""}`}>
                {formatDate(task.due_date)}
              </span>
            )}
            {task.tags.map(tag => {
              const color = getTagColor(tag);
              return (
                <span key={tag} className="task-tag" style={{ background: color.bg, color: color.text }}>{tag}</span>
              );
            })}
          </div>
        </div>
      );
    }

    // Add/Edit task modal
    if (showAddTask || editingTask) {
      const isEditing = !!editingTask;
      const title = isEditing ? editingTask.title : newTaskTitle;
      const desc = isEditing ? (editingTask.description || "") : newTaskDesc;
      const tags = isEditing ? editingTask.tags : newTaskTags;
      const due = isEditing ? (editingTask.due_date || "") : newTaskDue;

      return (
        <div className="tasks-section">
          <div className="task-modal">
            <div className="task-modal-header">
              <span>{isEditing ? "Edit Task" : "New Task"}</span>
              <button className="task-modal-close" onClick={() => { setShowAddTask(false); setEditingTask(null); }}>×</button>
            </div>
            <div className="task-modal-body">
              <div className="task-field">
                <label>Title</label>
                <input
                  type="text"
                  value={title}
                  onChange={(e) => isEditing ? setEditingTask({ ...editingTask, title: e.target.value }) : setNewTaskTitle(e.target.value)}
                  placeholder="What needs to be done?"
                  autoFocus
                />
              </div>
              <div className="task-field">
                <label>Description</label>
                <textarea
                  value={desc}
                  onChange={(e) => isEditing ? setEditingTask({ ...editingTask, description: e.target.value }) : setNewTaskDesc(e.target.value)}
                  placeholder="Optional details..."
                  rows={3}
                />
              </div>
              <div className="task-field-row">
                <div className="task-field">
                  <label>Due Date</label>
                  <DatePicker
                    value={due}
                    onChange={(val) => isEditing ? setEditingTask({ ...editingTask, due_date: val }) : setNewTaskDue(val)}
                  />
                </div>
                <div className="task-field">
                  <label>Tags</label>
                  <TagInput
                    tags={tags}
                    onChange={(t) => isEditing ? setEditingTask({ ...editingTask, tags: t }) : setNewTaskTags(t)}
                  />
                </div>
              </div>
              {isEditing && (
                <div className="task-field">
                  <label>Status</label>
                  <select
                    value={editingTask.status}
                    onChange={(e) => setEditingTask({ ...editingTask, status: e.target.value as Task["status"] })}
                  >
                    <option value="todo">To Do</option>
                    <option value="in_progress">In Progress</option>
                    <option value="done">Done</option>
                  </select>
                </div>
              )}
            </div>
            <div className="task-modal-footer">
              <button className="task-btn primary" onClick={isEditing ? handleUpdateTask : handleAddTask}>
                {isEditing ? "Save" : "Add Task"}
              </button>
              {isEditing && (
                <button className="task-btn danger" onClick={() => { handleDeleteTask(editingTask.id); setEditingTask(null); }}>
                  Delete
                </button>
              )}
              <button className="task-btn" onClick={() => { setShowAddTask(false); setEditingTask(null); }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      );
    }

    // Kanban board
    return (
      <div className="tasks-section">
        <div className="tasks-header">
          <button className="add-task-btn" onClick={() => setShowAddTask(true)}>
            + Add Task
          </button>
        </div>
        <div className="kanban-board">
          <div
            className={`kanban-column ${dragOverColumn === "todo" ? "drag-over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverColumn("todo"); }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={(e) => {
              e.preventDefault();
              const taskId = e.dataTransfer.getData("text/plain");
              if (taskId) handleMoveTask(taskId, "todo");
              setDragOverColumn(null);
            }}
          >
            <div className="kanban-column-header">
              <span className="kanban-column-title">To Do</span>
              <span className="kanban-column-count">{todoTasks.length}</span>
            </div>
            <div className="kanban-column-content">
              {todoTasks.map(renderTaskCard)}
            </div>
          </div>
          <div
            className={`kanban-column ${dragOverColumn === "in_progress" ? "drag-over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverColumn("in_progress"); }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={(e) => {
              e.preventDefault();
              const taskId = e.dataTransfer.getData("text/plain");
              if (taskId) handleMoveTask(taskId, "in_progress");
              setDragOverColumn(null);
            }}
          >
            <div className="kanban-column-header">
              <span className="kanban-column-title">In Progress</span>
              <span className="kanban-column-count">{inProgressTasks.length}</span>
            </div>
            <div className="kanban-column-content">
              {inProgressTasks.map(renderTaskCard)}
            </div>
          </div>
          <div
            className={`kanban-column done ${dragOverColumn === "done" ? "drag-over" : ""}`}
            onDragOver={(e) => { e.preventDefault(); setDragOverColumn("done"); }}
            onDragLeave={() => setDragOverColumn(null)}
            onDrop={(e) => {
              e.preventDefault();
              const taskId = e.dataTransfer.getData("text/plain");
              if (taskId) handleMoveTask(taskId, "done");
              setDragOverColumn(null);
            }}
          >
            <div className="kanban-column-header">
              <span className="kanban-column-title">Done</span>
              <span className="kanban-column-count">{doneTasks.length}</span>
            </div>
            <div className="kanban-column-content">
              {doneTasks.map(renderTaskCard)}
            </div>
          </div>
        </div>
      </div>
    );
  }

  function renderNotesSection() {
    // Editor view
    if (noteEditing && selectedNote) {
      const fileName = selectedNote.split("/").pop() || selectedNote;
      return (
        <div className="notes-section">
          <div className="notes-editor-header">
            <button className="back-btn" onClick={handleCloseNote}>
              ← Back
            </button>
            {editingNoteName ? (
              <div className="notes-filename-edit">
                <input
                  type="text"
                  value={noteNameInput}
                  onChange={(e) => setNoteNameInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") handleRenameNote();
                    if (e.key === "Escape") setEditingNoteName(false);
                  }}
                  autoFocus
                />
                <button className="notes-rename-btn" onClick={handleRenameNote}>Rename</button>
                <button className="notes-rename-cancel" onClick={() => setEditingNoteName(false)}>Cancel</button>
              </div>
            ) : (
              <div
                className="notes-filename"
                onClick={() => {
                  setNoteNameInput(fileName.replace(/\.md$/, ""));
                  setEditingNoteName(true);
                }}
                title="Click to rename"
              >
                {fileName}
              </div>
            )}
            <div className="notes-header-actions">
              <button
                className={`notes-preview-btn ${notePreview ? "active" : ""}`}
                onClick={() => setNotePreview(!notePreview)}
              >
                {notePreview ? "Edit" : "Preview"}
              </button>
              <button
                className={`notes-save-btn ${noteSaving ? "saving" : ""} ${noteSaved ? "saved" : ""}`}
                onClick={handleSaveNote}
                disabled={noteSaving}
              >
                {noteSaving ? "Saving..." : noteSaved ? "Saved!" : "Save"}
              </button>
              <button
                className="notes-delete-btn"
                onClick={() => { if (confirm("Delete this note?")) handleDeleteNote(selectedNote); }}
              >
                Delete
              </button>
            </div>
          </div>
          {notePreview ? (
            <div className="notes-preview">
              <Markdown>{noteContent}</Markdown>
            </div>
          ) : (
            <textarea
              className="notes-editor"
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              spellCheck={false}
            />
          )}
        </div>
      );
    }

    // File browser view
    return (
      <div className="notes-section">
        <div className="notes-header">
          <div className="notes-breadcrumb">
            <button
              className="breadcrumb-item"
              onClick={() => { setNotesPath([]); loadNotes(""); }}
            >
              docs
            </button>
            {notesPath.map((part, idx) => (
              <span key={idx}>
                <span className="breadcrumb-sep">/</span>
                <button
                  className="breadcrumb-item"
                  onClick={() => {
                    const newPath = notesPath.slice(0, idx + 1);
                    setNotesPath(newPath);
                    loadNotes(newPath.join("/"));
                  }}
                >
                  {part}
                </button>
              </span>
            ))}
          </div>
          <button className="new-note-btn" onClick={() => setShowNewNote(true)}>
            + New Note
          </button>
        </div>

        {showNewNote && (
          <div className="new-note-modal">
            <input
              type="text"
              className="new-note-input"
              placeholder="Note name (e.g., my-note.md)"
              value={newNoteName}
              onChange={(e) => setNewNoteName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateNote();
                if (e.key === "Escape") { setShowNewNote(false); setNewNoteName(""); }
              }}
              autoFocus
            />
            <div className="new-note-actions">
              <button className="new-note-create" onClick={handleCreateNote}>Create</button>
              <button className="new-note-cancel" onClick={() => { setShowNewNote(false); setNewNoteName(""); }}>Cancel</button>
            </div>
          </div>
        )}

        <div className="notes-list">
          {notesPath.length > 0 && (
            <div className="notes-item folder" onClick={navigateUp}>
              <span className="notes-icon">📁</span>
              <span className="notes-name">..</span>
            </div>
          )}
          {noteEntries.length === 0 && notesPath.length === 0 ? (
            <div className="empty-state">
              <p>No markdown files found</p>
            </div>
          ) : (
            noteEntries.map((entry) => (
              <div
                key={entry.path}
                className={`notes-item ${entry.is_dir ? "folder" : "file"}`}
                onClick={() => {
                  if (entry.is_dir) {
                    navigateToFolder(entry.path);
                  } else {
                    handleOpenNote(entry.path);
                  }
                }}
              >
                <span className="notes-icon">{entry.is_dir ? "📁" : "📄"}</span>
                <span className="notes-name">{entry.name}</span>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="app-layout">
      {renderSidebar()}
      <main className="main-content">
        {currentSection === "worktrees" && renderWorktreesSection()}
        {currentSection === "notes" && renderNotesSection()}
        {currentSection === "tasks" && renderTasksSection()}
        {currentSection === "voice" && renderVoiceSection()}
        {currentSection === "memory" && renderMemorySection()}
        {currentSection === "config" && renderConfigSection()}
      </main>
    </div>
  );
}

export default App;
