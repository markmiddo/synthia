import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";

interface JournalEntry {
  timestamp: string;
  agent_name: string;
  agent_kind: string;
  agent_role: string;
  project_name: string;
  branch: string | null;
  task_summary: string;
  files_touched: string[];
  activity: string | null;
  session_id: string | null;
  trigger: string;
}

interface JournalDay {
  date_label: string;
  entries: JournalEntry[];
}

type AgentFilter = "all" | "claude" | "opencode" | "kimi" | "codex";
type TimeFilter = "all" | "today" | "7days";

export function JournalPanel() {
  const [entries, setEntries] = useState<JournalDay[]>([]);
  const [loading, setLoading] = useState(true);
  const [agentFilter, setAgentFilter] = useState<AgentFilter>("all");
  const [timeFilter, setTimeFilter] = useState<TimeFilter>("7days");

  useEffect(() => {
    loadEntries();
  }, [agentFilter, timeFilter]);

  async function loadEntries() {
    setLoading(true);
    try {
      const days = timeFilter === "today" ? 1 : 7;
      const result = await invoke<[string, JournalEntry[]][]>(
        "get_journal_entries_by_agent",
        {
          agentKind: agentFilter === "all" ? null : agentFilter,
          days,
        }
      );

      const formatted: JournalDay[] = result.map(([date_label, entries]) => ({
        date_label,
        entries,
      }));

      setEntries(formatted);
    } catch (e) {
      console.error("Failed to load journal entries:", e);
    } finally {
      setLoading(false);
    }
  }

  function formatTime(timestamp: string): string {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function getAgentIcon(kind: string): string {
    switch (kind) {
      case "claude":
        return "🅒";
      case "opencode":
        return "🅞";
      case "kimi":
        return "🅚";
      case "codex":
        return "🅧";
      default:
        return "🤖";
    }
  }

  const totalEntries = entries.reduce(
    (sum, day) => sum + day.entries.length,
    0
  );

  return (
    <div className="journal-panel">
      <div className="journal-header">
        <h3>Daily Journal</h3>
        <span className="journal-count">{totalEntries} entries</span>
      </div>

      <div className="journal-filters">
        <div className="filter-group">
          <button
            className={agentFilter === "all" ? "active" : ""}
            onClick={() => setAgentFilter("all")}
          >
            All
          </button>
          <button
            className={agentFilter === "claude" ? "active" : ""}
            onClick={() => setAgentFilter("claude")}
          >
            Claude
          </button>
          <button
            className={agentFilter === "opencode" ? "active" : ""}
            onClick={() => setAgentFilter("opencode")}
          >
            OpenCode
          </button>
          <button
            className={agentFilter === "kimi" ? "active" : ""}
            onClick={() => setAgentFilter("kimi")}
          >
            Kilo
          </button>
          <button
            className={agentFilter === "codex" ? "active" : ""}
            onClick={() => setAgentFilter("codex")}
          >
            Codex
          </button>
        </div>

        <div className="filter-group">
          <button
            className={timeFilter === "7days" ? "active" : ""}
            onClick={() => setTimeFilter("7days")}
          >
            7 Days
          </button>
          <button
            className={timeFilter === "today" ? "active" : ""}
            onClick={() => setTimeFilter("today")}
          >
            Today
          </button>
        </div>
      </div>

      {loading ? (
        <div className="journal-loading">Loading journal...</div>
      ) : entries.length === 0 ? (
        <div className="journal-empty">
          <p>No journal entries yet.</p>
          <p className="journal-empty-hint">
            Complete a task list to see it here.
          </p>
        </div>
      ) : (
        <div className="journal-entries">
          {entries.map((day) => (
            <div key={day.date_label} className="journal-day">
              <h4 className="journal-day-header">{day.date_label}</h4>
              {day.entries.map((entry, idx) => (
                <div key={idx} className="journal-entry-card">
                  <div className="journal-entry-header">
                    <span className="journal-time">
                      {formatTime(entry.timestamp)}
                    </span>
                    <span className="journal-agent">
                      {getAgentIcon(entry.agent_kind)} {entry.agent_name}
                    </span>
                    <span className="journal-role">{entry.agent_role}</span>
                    <span className="journal-project">
                      {entry.project_name}
                      {entry.branch && (
                        <span className="journal-branch">@{entry.branch}</span>
                      )}
                    </span>
                  </div>
                  <div className="journal-task">
                    <span className="journal-check">✓</span>
                    {entry.task_summary}
                  </div>
                  {entry.files_touched.length > 0 && (
                    <div className="journal-files">
                      → {entry.files_touched.join(", ")}
                    </div>
                  )}
                  {entry.activity && (
                    <div className="journal-activity">{entry.activity}</div>
                  )}
                </div>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
