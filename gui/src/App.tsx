import { useState, useEffect } from "react";
import { invoke } from "@tauri-apps/api/core";
import { openUrl } from "@tauri-apps/plugin-opener";
import Markdown from "react-markdown";
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

interface AgentInfo {
  pid: number;
  kind: string;
  cwd: string;
  project_name: string;
  branch: string | null;
  status: "active" | "idle" | "stale";
  started_at: string;
  last_activity: string | null;
  last_user_msg: string | null;
  last_action: string | null;
  session_id: string | null;
  jsonl_path: string | null;
  risk: "info" | "low" | "medium" | "high" | "critical" | null;
  risk_events: SecurityEvent[];
  role: string;
  role_icon: string;
  topic: string | null;
  current_task: string | null;
  activity: string | null;
  name: string;
}

interface SecurityEvent {
  id: string;
  ts: string;
  agent_pid: number | null;
  agent_kind: string | null;
  agent_cwd: string | null;
  session_id: string | null;
  tool: string;
  rule: string;
  severity: "info" | "low" | "medium" | "high" | "critical";
  matched: string;
  raw: unknown;
  decision: string;
  actor: string;
}

interface RuleInfo {
  title: string;
  what: string;
  why: string;
  recommend: string;
}

const RULE_INFO: Record<string, RuleInfo> = {
  "destructive-rm": {
    title: "Recursive delete of a critical path",
    what: "rm -rf was pointed at /, ~ (home), $HOME, or used --no-preserve-root.",
    why: "These wipe everything inside the target. A single hijacked or buggy command here destroys your work and may take the whole user account or system with it.",
    recommend: "If it ran: stop the agent now and restore from backup or `git restore`. If blocked: leave it blocked, then add a CLAUDE.md note for this repo telling the agent never to use rm -rf on home/system paths.",
  },
  "dd-block-device": {
    title: "Raw write to a disk device",
    what: "dd was given a block device (sd*, nvme*, hd*) as its output.",
    why: "Writing to /dev/sda et al overwrites the partition table and filesystem. Used to wipe drives or install rootkits.",
    recommend: "If it ran: power off and boot from rescue media before continuing — the live disk may be corrupt. If blocked: keep it blocked; legitimate disk imaging belongs in a manual terminal, not an agent.",
  },
  "pipe-to-shell": {
    title: "Run remote script unsupervised",
    what: "A download (curl/wget/fetch) was piped straight into sh/bash.",
    why: "Whatever the URL serves runs immediately as you. If the server is hostile or compromised, the agent has just executed arbitrary code without anyone reading it first.",
    recommend: "Treat as compromise until proven otherwise: audit recent file changes (`find ~ -mmin -60 -type f`), check ~/.cache and /tmp for downloaded payloads, review crontab + systemd --user units, rotate any credential the host could have read.",
  },
  "base64-exec": {
    title: "Decode-and-execute payload",
    what: "base64 -d was piped into a shell or interpreter.",
    why: "Encoded payloads piped to sh/python/node are the standard pattern for hiding malicious code from review tools and scanners.",
    recommend: "Capture the original command from the event detail, decode it manually (`echo '<payload>' | base64 -d | less`) before doing anything else; treat the host as compromised if you cannot identify the source.",
  },
  "sudo": {
    title: "Privilege escalation",
    what: "Command was prefixed with sudo to run as root.",
    why: "Once an agent runs as root there is no permission boundary left. A mistake or a prompt-injection from a fetched page now has full system rights.",
    recommend: "Review what changed: `sudo apt history` (or `journalctl _UID=0 --since=today`). Consider switching policy.yaml `mode` to `prompt` for sudo so each call surfaces a confirm dialog.",
  },
  "setuid-bit": {
    title: "Setuid bit set",
    what: "chmod +s was applied to a file.",
    why: "A setuid binary runs as its owner regardless of who launches it — the standard local-privilege-escalation backdoor.",
    recommend: "Find new setuid binaries with `find / -perm -4000 -newer /etc/hostname 2>/dev/null` and remove anything you don't recognise.",
  },
  "setcap": {
    title: "Linux capability granted",
    what: "setcap was used to grant a binary kernel capabilities.",
    why: "Capabilities like cap_net_admin or cap_dac_read_search hand a regular binary near-root powers without flipping the setuid bit.",
    recommend: "Audit caps with `getcap -r / 2>/dev/null` and revoke unexpected entries via `sudo setcap -r <path>`.",
  },
  "ssh-key-access": {
    title: "Reading or moving SSH keys",
    what: "An SSH key file (~/.ssh/id_*, authorized_keys, known_hosts) was about to be read or copied.",
    why: "SSH private keys unlock every server you access. Reading them is the first step toward exfiltrating them.",
    recommend: "Rotate keys: `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519` and update authorized_keys on every remote. Consider passphrase + ssh-agent so on-disk keys are encrypted.",
  },
  "ssh-key-write": {
    title: "Writing to your SSH key folder",
    what: "A write was directed at ~/.ssh/id_* or authorized_keys.",
    why: "Adding a key to authorized_keys is how attackers persist remote access. Overwriting your private key locks you out and can replace it with one they control.",
    recommend: "Open ~/.ssh/authorized_keys, remove any line you don't recognise, then rotate the local key. If a private key was overwritten, restore from backup before doing anything else over SSH.",
  },
  "gpg-access": {
    title: "Touching your GPG keyring",
    what: "An action targeted ~/.gnupg/.",
    why: "GPG keys sign your commits and decrypt secrets. Exfiltrating them lets others impersonate you or read encrypted data.",
    recommend: "Run `gpg --list-secret-keys` and verify the listed key IDs match yours. If unsure, revoke and re-issue (`gpg --gen-revoke`) and re-encrypt anything sensitive.",
  },
  "aws-credentials": {
    title: "Reading AWS credentials",
    what: "An AWS credentials file was about to be opened.",
    why: "Cloud keys grant full account access — usually with a billing limit measured in tens of thousands of dollars.",
    recommend: "Treat the access key as leaked: rotate immediately in IAM, review CloudTrail for unfamiliar API calls in the last 24h, and switch to short-lived SSO/STS tokens going forward.",
  },
  "credentials-read": {
    title: "Reading a credentials file",
    what: "A read was aimed at .aws/credentials or ~/.gnupg/.",
    why: "Same risk as above — these files contain long-lived secrets that unlock other systems.",
    recommend: "Rotate the credential and audit recent provider activity (CloudTrail / GCP audit logs / etc).",
  },
  "secret-exfil": {
    title: "Network call referencing secrets",
    what: "curl/wget/scp/rsync was used and the command mentioned ssh, aws, gnupg, credentials, secret, token, or api_key.",
    why: "A network tool combined with a secret-shaped string is the canonical exfiltration pattern — one HTTP request and the secret is gone.",
    recommend: "Treat any secret named in the command as compromised: rotate it (API key, token, AWS access key), review provider audit logs since the event timestamp, and flip the egress monitor on so future calls surface the destination host.",
  },
  "shell-rc-tamper": {
    title: "Modifying your shell startup file",
    what: "A redirection wrote to .bashrc / .zshrc / .profile and friends.",
    why: "Shell rc files run on every new terminal. Anything appended here persists invisibly across reboots and is the most common AI-agent persistence trick.",
    recommend: "Diff the file against your dotfiles repo or a backup (`git diff -- ~/.bashrc`). Remove anything you didn't add; open a fresh terminal to verify.",
  },
  "shell-rc-write": {
    title: "Writing your shell startup file",
    what: "Write tool targeted .bashrc / .zshrc / .profile.",
    why: "Same as above — anything here runs every time you open a terminal.",
    recommend: "Same: diff against backup/dotfiles, strip surprises, open a new shell.",
  },
  "env-file-write": {
    title: "Writing a .env file",
    what: "A .env file was about to be written.",
    why: "These usually hold API keys and DB passwords. Overwriting them is silent and easy to miss; injecting a new value lets a future read steal credentials.",
    recommend: "Diff the file against version control or a backup; if a known-good version is hard to recover, rotate every secret it held before re-running the app.",
  },
  "system-config-write": {
    title: "Writing into /etc/",
    what: "A write targeted /etc/.",
    why: "/etc holds system configuration. Most edits there require sudo and persist for every user — high-impact, high-permanence, often invisible.",
    recommend: "Inspect the file (`sudo less <path>`), revert to package default if available (`sudo dpkg --force-confmiss --force-confnew --reinstall <pkg>` for Debian/Ubuntu), or restore from backup.",
  },
  "mass-kill": {
    title: "Aggressive process kill",
    what: "pkill or killall was used with -9 (SIGKILL).",
    why: "SIGKILL skips clean shutdown. Mass-killing system services or dev tools causes data loss and is occasionally used to disable security agents.",
    recommend: "Check what was killed (`journalctl -p warning --since '5 min ago'`) and restart anything important — DB servers, your editor, security agents.",
  },
  "git-remote-rewrite": {
    title: "Repointing a git remote",
    what: "git remote set-url or add was used to change the upstream URL.",
    why: "Silently moves your pushes to a different repo. Used to capture credentials or exfiltrate code on the next push.",
    recommend: "Run `git remote -v` in the affected repo and reset any remote that doesn't match what you expect (`git remote set-url <name> <correct-url>`). Rotate any push token used since.",
  },
  "history-tamper": {
    title: "Clearing shell history",
    what: "history -c was invoked.",
    why: "Wipes the audit trail of what just happened in the shell. Almost never has a legitimate developer reason.",
    recommend: "Cross-reference against the agent's jsonl log (every tool call is recorded there) and review recent file changes via `git status` / `find ~ -mmin -120`.",
  },
  "history-redir-tamper": {
    title: "Truncating shell history file",
    what: "Redirection truncated .bash_history or .zsh_history.",
    why: "Same audit-trail concern as history -c — covers tracks of prior commands.",
    recommend: "Same — fall back to the agent's jsonl session log; that record cannot be edited by a tool call.",
  },
  "fetch-ip-literal": {
    title: "Fetching a raw IP",
    what: "WebFetch URL used a numeric IP instead of a hostname.",
    why: "Bare-IP URLs bypass DNS and TLS hostname checks; common in shellcode/loader hosting.",
    recommend: "Look up the IP (`whois <ip>` or any reputation site) before treating any data fetched as trustworthy. Reject the call if the host doesn't have a clear legitimate name.",
  },
  "fetch-onion": {
    title: "Fetching from a .onion address",
    what: "URL points at a Tor hidden service.",
    why: "Almost always indicates malware C2 or tooling distribution that wants to be hard to attribute.",
    recommend: "Block the call. There is no benign reason an AI coding agent should fetch from .onion in normal development.",
  },
  "egress-unknown-host": {
    title: "Outbound connection to unrecognised host",
    what: "Agent process opened a TCP connection to an IP not on the dev/AI allowlist.",
    why: "Unexpected egress is how data leaves your machine. Worth a glance even if benign — it tells you who your agent is talking to.",
    recommend: "Reverse-lookup the IP (`dig -x <ip>` or whois). If legitimate (e.g. CDN edge for an AI provider), add the hostname to the egress allowlist; if not, suspect a leak and rotate touched credentials.",
  },
  "injection-ignore-previous": {
    title: "Likely prompt injection",
    what: "Tool result contained 'ignore previous instructions' or a close variant.",
    why: "Classic jailbreak phrasing planted in fetched content. Successful injection makes the agent do the attacker's bidding using your permissions.",
    recommend: "Stop the agent before it acts on the fetched content. Re-fetch from a trusted source or paste the relevant info manually after sanitising it.",
  },
  "injection-roleplay": {
    title: "Likely prompt injection (roleplay)",
    what: "Tool result tried to push the model into a 'jailbreak' / 'developer mode' / 'DAN' persona.",
    why: "Same risk as above — these phrasings are designed to switch the model out of its safety posture.",
    recommend: "Same: stop, sanitise, retry without the contaminated content.",
  },
  "injection-system-marker": {
    title: "Possible fake system message",
    what: "Tool result contained [SYSTEM], <system>, or ### system ### markers.",
    why: "External text impersonating a system role is how injectors smuggle privileged-looking instructions into the conversation.",
    recommend: "Strip the markers before letting the agent continue; or re-fetch from a source that doesn't include them.",
  },
  "injection-hidden-unicode": {
    title: "Hidden Unicode in tool result",
    what: "Tool result contained zero-width or Unicode tag characters.",
    why: "Invisible characters can encode instructions the model reads but you don't. Often used to slip injection past human review.",
    recommend: "Pipe the source through `iconv -f utf-8 -t ascii//TRANSLIT` or a unicode-strip tool before re-feeding to the agent.",
  },
};

function eventOutcome(decision: string, actor: string): { label: string; tone: "blocked" | "ran-warn" | "ran-info" | "pending" } {
  if (decision === "denied") return { label: "Blocked before running", tone: "blocked" };
  if (decision === "allowed") return { label: actor === "user" ? "Allowed by you — ran" : "Allowed — ran", tone: "ran-warn" };
  if (decision === "prompted") return { label: "Awaiting your decision", tone: "pending" };
  if (actor === "egress-monitor") return { label: "Connection observed", tone: "ran-info" };
  if (actor === "rule-engine") return { label: "Already ran (caught after the fact)", tone: "ran-warn" };
  return { label: "Observed", tone: "ran-info" };
}

interface PendingPrompt {
  id: string;
  ts: string;
  tool: string;
  raw: unknown;
  events: Array<{ rule: string; severity: string; matched: string }>;
  agent_pid: number | null;
  timeout_s: number | null;
}

interface CommandConfig {
  filename: string;
  description: string;
  body: string;
}

interface SkillConfig {
  name: string;
  description: string;
  body: string;
  is_dir: boolean;
  has_resources: boolean;
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

interface GitHubLabel {
  name: string;
  color: string;
}

interface GitHubAssignee {
  login: string;
}

interface GitHubMilestone {
  title: string;
}

interface GitHubIssue {
  number: number;
  title: string;
  state: string;
  labels: GitHubLabel[];
  assignees: GitHubAssignee[];
  createdAt: string;
  updatedAt: string;
  url: string;
  body: string;
  milestone: GitHubMilestone | null;
  comments: unknown[];
  repository: string | null;
}

interface GitHubConfig {
  repos: string[];
  refresh_interval_seconds: number;
}

interface GitHubIssuesResponse {
  issues: GitHubIssue[];
  fetched_at: string;
  error: string | null;
}

type Section = "worktrees" | "knowledge" | "agents" | "security" | "voice" | "memory" | "config" | "github";

interface KnowledgeMeta {
  pinned: string[];
  recent: string[];
  expanded_folders: string[];
}

interface NoteEntry {
  name: string;
  path: string;
  is_dir: boolean;
}

type VoiceView = "main" | "history" | "words";
type MemoryCategory = "bug" | "pattern" | "arch" | "gotcha" | "stack" | null;
type ConfigTab = "synthia" | "agents" | "commands" | "skills" | "hooks" | "plugins";

function App() {
  const [status, setStatus] = useState<Status>("stopped");
  const [remoteMode, setRemoteMode] = useState(false);
  const [remoteToggling, setRemoteToggling] = useState(false);
  const [dictateKey, setDictateKey] = useState("Right Ctrl");
  const [assistantKey, setAssistantKey] = useState("Right Alt");
  const [editingKey, setEditingKey] = useState<"dictate" | "assistant" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [currentSection, setCurrentSection] = useState<Section>("agents");
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
  const [skills, setSkills] = useState<SkillConfig[]>([]);
  const [voiceMuted, setVoiceMuted] = useState(false);
  const [securityEvents, setSecurityEvents] = useState<SecurityEvent[]>([]);
  const [securityFilter, setSecurityFilter] = useState<"all" | "high+">("all");
  const [securityTabAutoChosen, setSecurityTabAutoChosen] = useState(false);
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
  const [neuralguardStatus, setNeuralguardStatus] = useState<{
    installed: boolean;
    events_path: string;
    policy_path: string;
    gate_script: string;
  } | null>(null);
  const [pendingPrompts, setPendingPrompts] = useState<PendingPrompt[]>([]);
  const [egressEnabled, setEgressEnabled] = useState(false);
  const [hooks, setHooks] = useState<HookConfig[]>([]);
  const [plugins, setPlugins] = useState<PluginInfo[]>([]);
  const [editingAgent, setEditingAgent] = useState<AgentConfig | null>(null);
  const [editingCommand, setEditingCommand] = useState<CommandConfig | null>(null);
  const [editingSkill, setEditingSkill] = useState<SkillConfig | null>(null);
  const [originalSkillName, setOriginalSkillName] = useState<string | null>(null);
  const [isNewAgent, setIsNewAgent] = useState(false);
  const [isNewCommand, setIsNewCommand] = useState(false);
  const [isNewSkill, setIsNewSkill] = useState(false);

  // Notes state
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
  const [notePreview, setNotePreview] = useState<boolean | null>(null);

  // Knowledge meta state
  const [pinnedNotes, setPinnedNotes] = useState<string[]>([]);
  const [recentNotes, setRecentNotes] = useState<string[]>([]);
  const [knowledgeSearch, setKnowledgeSearch] = useState("");
  // drag-and-drop state removed — replaced by tree view
  const [expandedFolders, setExpandedFolders] = useState<string[]>([]);
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    notePath: string;
  } | null>(null);
  const [copiedPath, setCopiedPath] = useState(false);
  const [allNoteEntries, setAllNoteEntries] = useState<Record<string, NoteEntry[]>>({});
  const [pinnedPreviews, setPinnedPreviews] = useState<Record<string, string>>({});
  const [noteModified, setNoteModified] = useState<Record<string, number>>({});
  const [notesBasePath, setNotesBasePath] = useState("");

  // GitHub state
  const [githubIssues, setGithubIssues] = useState<GitHubIssue[]>([]);
  const [githubConfig, setGithubConfig] = useState<GitHubConfig>({ repos: [], refresh_interval_seconds: 300 });
  const [githubFetchedAt, setGithubFetchedAt] = useState<string>("");
  const [githubError, setGithubError] = useState<string | null>(null);
  const [githubLoading, setGithubLoading] = useState(false);
  const [selectedIssue, setSelectedIssue] = useState<GitHubIssue | null>(null);
  const [githubRepoFilter, setGithubRepoFilter] = useState<string>("all");
  const [githubStateFilter, setGithubStateFilter] = useState<string>("open");
  const [githubConfigOpen, setGithubConfigOpen] = useState(false);
  const [newGithubRepo, setNewGithubRepo] = useState("");

  // Active agents monitor state
  const [activeAgents, setActiveAgents] = useState<AgentInfo[]>([]);
  const [expandedAgentPid, setExpandedAgentPid] = useState<number | null>(null);
  const [activeAgentsLoading, setActiveAgentsLoading] = useState(true);

  // Usage stats state
  const [usageStats, setUsageStats] = useState<{
    five_hour_pct: number;
    five_hour_resets_at: string;
    five_hour_resets_in: string;
    seven_day_pct: number;
    seven_day_resets_at: string;
    seven_day_resets_in: string;
    seven_day_opus_pct: number | null;
    seven_day_opus_resets_at: string | null;
    seven_day_opus_resets_in: string | null;
    seven_day_sonnet_pct: number | null;
    seven_day_sonnet_resets_at: string | null;
    seven_day_sonnet_resets_in: string | null;
    subscription_type: string | null;
    error: string | null;
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
      loadSkills();
      loadHooks();
      loadPlugins();
    }

    if (currentSection === "knowledge") {
      loadNotes("");
      loadKnowledgeMeta();
      loadTreeEntries("");
    }

    invoke<string>("get_notes_base_path_cmd").then(setNotesBasePath).catch(() => {});

    if (currentSection === "github") {
      loadGithubConfig();
      loadGithubIssues();
    }

    const interval = setInterval(() => {
      checkStatus();
      checkRemoteStatus();
      if (currentSection === "worktrees") loadWorktrees();
      if (currentSection === "voice" && voiceView === "history") loadHistory();
    }, 2000);

    return () => {
      clearInterval(interval);
    };
  }, [currentSection, voiceView, memoryFilter]);

  // Load note metadata (previews for pinned, timestamps for pinned + recent)
  useEffect(() => {
    if (currentSection === "knowledge" && (pinnedNotes.length > 0 || recentNotes.length > 0)) {
      loadNoteMetadata(pinnedNotes, recentNotes);
    }
  }, [pinnedNotes, recentNotes, currentSection]);

  // Restore expanded folder state when entering knowledge section
  useEffect(() => {
    if (currentSection === "knowledge" && expandedFolders.length > 0) {
      expandedFolders.forEach((folder) => loadTreeEntries(folder));
    }
  }, [currentSection]);

  // Refresh GitHub issues when config modal closes
  useEffect(() => {
    if (!githubConfigOpen && currentSection === "github") {
      loadGithubIssues(true);
    }
  }, [githubConfigOpen]);

  // Active agents polling
  useEffect(() => {
    if (currentSection !== "agents") return;
    loadActiveAgents();
    const id = setInterval(loadActiveAgents, 5000);
    return () => clearInterval(id);
  }, [currentSection]);

  // Voice mute state - load on mount, refresh periodically (file may be edited externally)
  useEffect(() => {
    loadVoiceMuted();
    const id = setInterval(loadVoiceMuted, 5000);
    return () => clearInterval(id);
  }, []);

  // Security events polling
  useEffect(() => {
    if (currentSection !== "security") return;
    loadSecurityEvents();
    loadNeuralguardStatus();
    const id = setInterval(loadSecurityEvents, 4000);
    return () => clearInterval(id);
  }, [currentSection]);

  // Smart default tab: auto-pick "high+" if any HIGH/CRITICAL exists on first event load.
  useEffect(() => {
    if (securityTabAutoChosen || securityEvents.length === 0) return;
    const hasHigh = securityEvents.some(
      (e) => e.severity === "high" || e.severity === "critical",
    );
    setSecurityFilter(hasHigh ? "high+" : "all");
    setSecurityTabAutoChosen(true);
  }, [securityEvents, securityTabAutoChosen]);

  // Pending security prompts poll (runs always so modal can interrupt anywhere)
  useEffect(() => {
    loadPendingPrompts();
    const id = setInterval(loadPendingPrompts, 1500);
    return () => clearInterval(id);
  }, []);

  async function loadPendingPrompts() {
    try {
      const list = await invoke<PendingPrompt[]>("list_pending_prompts");
      setPendingPrompts(list);
    } catch (e) {
      // Ignore
    }
  }

  async function handlePromptDecision(id: string, decision: "allow" | "deny") {
    try {
      await invoke("respond_to_prompt", { id, decision });
      setPendingPrompts((prev) => prev.filter((p) => p.id !== id));
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadNeuralguardStatus() {
    try {
      const s = await invoke<typeof neuralguardStatus>("neuralguard_status");
      setNeuralguardStatus(s);
    } catch (e) {
      // Ignore
    }
    try {
      const enabled = await invoke<boolean>("get_egress_enabled");
      setEgressEnabled(enabled);
    } catch (e) {
      // Ignore
    }
  }

  async function handleToggleEgress() {
    const next = !egressEnabled;
    setEgressEnabled(next);
    try {
      await invoke("set_egress_enabled", { enabled: next });
    } catch (e) {
      setEgressEnabled(!next);
      setError(String(e));
    }
  }

  async function handleInstallHooks() {
    try {
      await invoke<string>("install_neuralguard_hooks");
      loadNeuralguardStatus();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleUninstallHooks() {
    if (!confirm("Remove AI Security hooks from Claude Code?")) return;
    try {
      await invoke<string>("uninstall_neuralguard_hooks");
      loadNeuralguardStatus();
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadSecurityEvents() {
    try {
      const list = await invoke<SecurityEvent[]>("list_security_events", { limit: 200 });
      setSecurityEvents(list);
    } catch (e) {
      // Ignore
    }
  }

  async function handleClearSecurityEvents() {
    if (!confirm("Clear all security events?")) return;
    try {
      await invoke("clear_security_events");
      loadSecurityEvents();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleRescanSessions() {
    try {
      await invoke("scan_all_sessions");
      loadSecurityEvents();
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadVoiceMuted() {
    try {
      const muted = await invoke<boolean>("get_voice_muted");
      setVoiceMuted(muted);
    } catch (e) {
      // Ignore
    }
  }

  async function handleToggleVoiceMute() {
    const next = !voiceMuted;
    setVoiceMuted(next);
    try {
      await invoke("set_voice_muted", { muted: next });
    } catch (e) {
      setVoiceMuted(!next);
      setError(String(e));
    }
  }

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

  async function loadGithubConfig() {
    try {
      const result = await invoke<GitHubConfig>("get_github_config");
      setGithubConfig(result);
    } catch (e) {
      // Ignore errors
    }
  }

  async function loadGithubIssues(forceRefresh = false) {
    setGithubLoading(true);
    try {
      const result = await invoke<GitHubIssuesResponse>("get_github_issues", {
        forceRefresh,
      });
      setGithubIssues(result.issues);
      setGithubFetchedAt(result.fetched_at);
      setGithubError(result.error);
      // Refresh selectedIssue to avoid stale data in detail panel
      setSelectedIssue(prev => {
        if (!prev) return null;
        return result.issues.find(
          i => i.number === prev.number && i.repository === prev.repository
        ) || null;
      });
    } catch (e) {
      setGithubError(String(e));
    } finally {
      setGithubLoading(false);
    }
  }

  async function saveGithubConfig(repos: string[], refreshInterval: number) {
    try {
      await invoke("save_github_config", {
        repos,
        refreshIntervalSeconds: refreshInterval,
      });
      setGithubConfig({ repos, refresh_interval_seconds: refreshInterval });
    } catch (e) {
      setGithubError(String(e));
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

  async function loadActiveAgents() {
    try {
      const result = await invoke<AgentInfo[]>("list_active_agents");
      setActiveAgents(result);
    } catch (e) {
      console.error("Failed to load agents:", e);
    } finally {
      setActiveAgentsLoading(false);
    }
  }

  async function handleKillAgent(pid: number) {
    if (!confirm(`Send SIGTERM to agent ${pid}?`)) return;
    try {
      await invoke("kill_agent", { pid });
      loadActiveAgents();
    } catch (e) {
      alert(`Failed to kill agent: ${e}`);
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

  async function loadSkills() {
    try {
      const result = await invoke<SkillConfig[]>("list_skills");
      setSkills(result);
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
      setNotePreview(null);
      trackRecentNote(path);
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
    setNotePreview(null);
    // Refresh the notes list to show any new or updated notes
    loadNotes("");
  }

  async function handleDeleteNote(path: string) {
    try {
      await invoke("delete_note", { path });
      // Clean up pinned/recent references
      const newPinned = pinnedNotes.filter((p) => p !== path);
      const newRecent = recentNotes.filter((p) => p !== path);
      setPinnedNotes(newPinned);
      setRecentNotes(newRecent);
      saveKnowledgeMeta(newPinned, newRecent);
      if (selectedNote === path) {
        handleCloseNote();
      } else {
        loadNotes("");
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
      // Update pinned/recent references to the new path
      const newPinned = pinnedNotes.map((p) => p === selectedNote ? newPath : p);
      const newRecent = recentNotes.map((p) => p === selectedNote ? newPath : p);
      setPinnedNotes(newPinned);
      setRecentNotes(newRecent);
      saveKnowledgeMeta(newPinned, newRecent);
      setSelectedNote(newPath);
      setEditingNoteName(false);
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleCreateNote() {
    if (!newNoteName.trim()) return;

    // Ensure .md extension
    let filename = newNoteName.trim();
    if (!filename.endsWith(".md")) {
      filename += ".md";
    }

    const fullPath = filename;

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

  async function handleCreateFolder() {
    if (!newNoteName.trim()) return;

    const fullPath = newNoteName.trim();

    try {
      await invoke("create_folder", { path: fullPath });
      setShowNewNote(false);
      setNewNoteName("");
      loadNotes("");
    } catch (e) {
      setError(String(e));
    }
  }

  async function loadKnowledgeMeta() {
    try {
      const meta = await invoke<KnowledgeMeta>("get_knowledge_meta");
      setPinnedNotes(meta.pinned || []);
      setRecentNotes(meta.recent || []);
      setExpandedFolders(meta.expanded_folders || []);
    } catch {
      // Use empty defaults
    }
  }

  async function saveKnowledgeMeta(
    pinned?: string[],
    recent?: string[],
    expanded?: string[]
  ) {
    try {
      const meta: KnowledgeMeta = {
        pinned: pinned ?? pinnedNotes,
        recent: recent ?? recentNotes,
        expanded_folders: expanded ?? expandedFolders,
      };
      await invoke("save_knowledge_meta", { meta });
    } catch {
      // Ignore save errors
    }
  }

  function togglePinNote(path: string) {
    const isPinned = pinnedNotes.includes(path);
    const newPinned = isPinned
      ? pinnedNotes.filter((p) => p !== path)
      : [...pinnedNotes, path];
    setPinnedNotes(newPinned);
    saveKnowledgeMeta(newPinned, recentNotes);
  }

  function trackRecentNote(path: string) {
    const deduped = recentNotes.filter((p) => p !== path);
    const newRecent = [path, ...deduped].slice(0, 6);
    setRecentNotes(newRecent);
    saveKnowledgeMeta(pinnedNotes, newRecent);
  }

  async function copyNotePath(relativePath: string): Promise<boolean> {
    const fullPath = notesBasePath
      ? `${notesBasePath}/${relativePath}`
      : relativePath;
    try {
      await navigator.clipboard.writeText(fullPath);
      return true;
    } catch {
      return false;
    }
  }
  function handleNoteContextMenu(e: React.MouseEvent, notePath: string) {
    e.preventDefault();
    setContextMenu({ x: e.clientX, y: e.clientY, notePath });
  }

  useEffect(() => {
    if (!contextMenu) return;
    const dismiss = () => setContextMenu(null);
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") dismiss();
    };
    // Use mousedown instead of click+contextmenu to avoid conflicting
    // with React's onContextMenu handler (both fire on same event at
    // different DOM levels, causing the menu to immediately dismiss)
    document.addEventListener("mousedown", dismiss);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", dismiss);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [contextMenu]);

  async function handleCopyPath(relativePath: string) {
    const success = await copyNotePath(relativePath);
    if (success) {
      setCopiedPath(true);
      setTimeout(() => setCopiedPath(false), 1500);
    }
  }

  async function loadNoteMetadata(pinned: string[], recent: string[]) {
    const previews: Record<string, string> = {};
    const modified: Record<string, number> = {};

    // Load previews and timestamps for pinned notes
    for (const path of pinned) {
      try {
        const preview: string = await invoke("get_note_preview", { path });
        previews[path] = preview;
        const mod: number = await invoke("get_note_modified", { path });
        modified[path] = mod;
      } catch {
        previews[path] = "";
        modified[path] = 0;
      }
    }

    // Load timestamps for recent notes (skip if already loaded from pinned)
    for (const path of recent) {
      if (!modified[path] && modified[path] !== 0) {
        try {
          const mod: number = await invoke("get_note_modified", { path });
          modified[path] = mod;
        } catch {
          modified[path] = 0;
        }
      }
    }

    setPinnedPreviews(previews);
    setNoteModified(modified);
  }

  async function loadTreeEntries(subpath: string) {
    try {
      const entries: NoteEntry[] = await invoke("list_notes", {
        subpath: subpath || null,
      });
      setAllNoteEntries((prev) => ({ ...prev, [subpath]: entries }));
    } catch (e) {
      console.error("Failed to load tree entries:", e);
    }
  }

  async function toggleFolder(folderPath: string) {
    const isExpanded = expandedFolders.includes(folderPath);
    let newExpanded: string[];
    if (isExpanded) {
      newExpanded = expandedFolders.filter((f) => f !== folderPath);
    } else {
      newExpanded = [...expandedFolders, folderPath];
      if (!allNoteEntries[folderPath]) {
        await loadTreeEntries(folderPath);
      }
    }
    setExpandedFolders(newExpanded);
    saveKnowledgeMeta(undefined, undefined, newExpanded);
  }

  function getRelativeTime(timestamp: number): string {
    if (!timestamp) return "";
    const now = Math.floor(Date.now() / 1000);
    const diff = now - timestamp;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
    return `${Math.floor(diff / 604800)}w ago`;
  }

  async function loadUsageStats() {
    try {
      const result = await invoke<typeof usageStats>("get_usage_stats");
      setUsageStats(result);
    } catch (e) {
      // Ignore errors
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

  async function handleSaveSkill(skill: SkillConfig) {
    try {
      if (originalSkillName && originalSkillName !== skill.name) {
        await invoke("delete_skill", { name: originalSkillName });
      }
      await invoke("save_skill", { skill });
      setEditingSkill(null);
      setIsNewSkill(false);
      setOriginalSkillName(null);
      loadSkills();
    } catch (e) {
      setError(String(e));
    }
  }

  async function handleDeleteSkill(name: string) {
    if (!confirm(`Delete skill "${name}"?`)) return;
    try {
      await invoke("delete_skill", { name });
      loadSkills();
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

  function renderAgentsSection() {
    function elapsedSince(iso: string): string {
      const then = new Date(iso).getTime();
      const now = Date.now();
      const secs = Math.max(0, Math.floor((now - then) / 1000));
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      if (h > 0) return `${h}h ${m}m`;
      if (m > 0) return `${m}m ${s}s`;
      return `${s}s`;
    }

    function shortenCwd(cwd: string): string {
      const home = "/home/markmiddo";
      const p = cwd.startsWith(home) ? "~" + cwd.slice(home.length) : cwd;
      const parts = p.split("/").filter(Boolean);
      if (parts.length <= 3) return p;
      return parts.slice(-3).join("/");
    }

    return (
      <div className="agents-section">
        <div className="agents-header">
          <h2>AI Agents</h2>
          <span className="agents-count">
            {activeAgents.length} {activeAgents.length === 1 ? "agent" : "agents"} running
          </span>
        </div>

        {activeAgentsLoading && activeAgents.length === 0 ? (
          <div className="agents-loading">Scanning…</div>
        ) : activeAgents.length === 0 ? (
          <div className="agents-empty">No AI agents running</div>
        ) : (
          <ul className="agents-list">
            {activeAgents.map((a) => {
              const expanded = expandedAgentPid === a.pid;
              return (
                <li
                  key={a.pid}
                  className={`agent-row agent-${a.status} ${expanded ? "expanded" : ""}`}
                >
                  <button
                    className="agent-summary"
                    onClick={() => setExpandedAgentPid(expanded ? null : a.pid)}
                  >
                    <span className={`agent-status-dot status-${a.status}`} />
                    <span className="agent-avatar" title={a.role}>{a.role_icon}</span>
                    <span className="agent-identity">
                      <span className="agent-identity-line">
                        <span className="agent-name">{a.name}</span>
                        <span className="agent-project">{a.project_name}</span>
                        <span className="agent-role">{a.role}</span>
                        <span className={`agent-kind kind-${a.kind}`}>{a.kind}</span>
                        {a.risk && (
                          <span
                            className={`agent-risk risk-${a.risk}`}
                            title={`Security risk: ${a.risk} — ${
                              a.risk_events.length
                                ? a.risk_events.slice(-3).map((e) => e.rule).join(", ")
                                : "expand for details"
                            }`}
                          >
                            {"⛨"}
                          </span>
                        )}
                        {a.branch && <span className="agent-branch">{a.branch}</span>}
                      </span>
                      {(a.current_task || a.topic) && (
                        <span
                          className="agent-topic"
                          title={a.topic || a.current_task || undefined}
                        >
                          {a.current_task || a.topic}
                        </span>
                      )}
                    </span>
                    <span className="agent-tail">
                      {a.activity && (
                        <span className="agent-activity" title={a.activity}>
                          {a.activity}
                        </span>
                      )}
                      <span className="agent-cwd" title={a.cwd}>
                        {shortenCwd(a.cwd)}
                      </span>
                      <span className="agent-elapsed">{elapsedSince(a.started_at)}</span>
                    </span>
                  </button>
                  {expanded && (
                    <div className="agent-detail">
                      {a.last_user_msg && (
                        <div className="agent-detail-block">
                          <div className="agent-detail-label">Last message</div>
                          <pre className="agent-detail-msg">{a.last_user_msg}</pre>
                        </div>
                      )}
                      {a.last_action && (
                        <div className="agent-detail-block">
                          <div className="agent-detail-label">Last action</div>
                          <code>{a.last_action}</code>
                        </div>
                      )}
                      {a.risk_events && a.risk_events.length > 0 && (
                        <div className="agent-detail-block">
                          <div className="agent-detail-label">
                            Security events ({a.risk_events.length})
                          </div>
                          <div className="agent-risk-events">
                            {a.risk_events.slice(-10).reverse().map((e) => {
                              const info = RULE_INFO[e.rule];
                              return (
                                <div key={e.id} className={`agent-risk-event sev-${e.severity}`}>
                                  <span className={`severity-pill sev-${e.severity}`}>
                                    {e.severity.toUpperCase()}
                                  </span>
                                  <span
                                    className="agent-risk-event-rule"
                                    title={info ? info.why : e.rule}
                                  >
                                    {info ? info.title : e.rule}
                                  </span>
                                  <span className="agent-risk-event-match">{e.matched}</span>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                      <div className="agent-detail-block agent-meta">
                        <div>PID: {a.pid}</div>
                        <div>cwd: {a.cwd}</div>
                        {a.session_id && <div>session: {a.session_id}</div>}
                      </div>
                      <button
                        className="agent-kill-btn"
                        onClick={() => handleKillAgent(a.pid)}
                      >
                        Kill agent
                      </button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  function renderSecuritySection() {
    const sevRank: Record<string, number> = {
      info: 0, low: 1, medium: 2, high: 3, critical: 4,
    };
    const filtered = securityEvents.filter((e) =>
      securityFilter === "all" ? true : sevRank[e.severity] >= 3,
    );
    const counts: Record<string, number> = { critical: 0, high: 0, medium: 0, low: 0, info: 0 };
    for (const e of securityEvents) counts[e.severity] = (counts[e.severity] || 0) + 1;

    function formatTs(iso: string) {
      try {
        const d = new Date(iso);
        return d.toLocaleString();
      } catch {
        return iso;
      }
    }

    function destFromMatched(matched: string): string {
      // Forms produced by egress.rs:
      //   IPv4 → "35.190.46.17:443 (proc claude)"
      //   IPv6 → "[2600:1901:0:3084::]:443 (proc claude)"
      const v6 = matched.match(/^\[([^\]]+)\]/);
      if (v6) return v6[1];
      const v4 = matched.match(/^([0-9.]+)/);
      if (v4) return v4[1];
      // Fallback: take everything before the first " (".
      const space = matched.indexOf(" (");
      return space > 0 ? matched.slice(0, space) : matched;
    }

    type EventGroup = { key: string; events: SecurityEvent[]; latest: SecurityEvent };

    function groupEvents(evts: SecurityEvent[]): EventGroup[] {
      const groups = new Map<string, SecurityEvent[]>();
      for (const e of evts) {
        // Group by agent KIND (e.g. "claude") not pid — different process
        // instances of the same agent talking to the same host should collapse.
        const kind = e.agent_kind ?? "?";
        const key = `${e.rule}::${kind}::${destFromMatched(e.matched)}`;
        const arr = groups.get(key) ?? [];
        arr.push(e);
        groups.set(key, arr);
      }
      return [...groups.entries()]
        .map(([key, arr]) => {
          const sorted = arr.sort((a, b) => b.ts.localeCompare(a.ts));
          return { key, events: sorted, latest: sorted[0] };
        })
        .sort((a, b) => b.latest.ts.localeCompare(a.latest.ts));
    }

    const groups = groupEvents(filtered);

    async function handleAllowHost(evt: SecurityEvent) {
      const host = destFromMatched(evt.matched);
      try {
        await invoke("add_to_allowlist", { host });
        // Optimistically remove this group's events from view.
        setSecurityEvents((prev) =>
          prev.filter((e) => destFromMatched(e.matched) !== host),
        );
      } catch (err) {
        console.error("add_to_allowlist failed", err);
      }
    }

    const installed = neuralguardStatus?.installed ?? false;

    return (
      <div className="security-section">
        <div className="security-header">
          <div>
            <h2>AI Security</h2>
            <div className="security-subhead">
              Local AI agent runtime monitor — flags risky actions before they happen
            </div>
          </div>
          <div className="security-actions">
            <button className="claude-btn" onClick={handleRescanSessions}>
              Rescan sessions
            </button>
            <button className="claude-btn danger" onClick={handleClearSecurityEvents}>
              Clear events
            </button>
          </div>
        </div>

        <div className={`neuralguard-install ${installed ? "installed" : ""}`}>
          <div className="neuralguard-install-text">
            <div className="neuralguard-install-title">
              {installed ? "AI Security hooks active" : "AI Security hooks not installed"}
            </div>
            <div className="neuralguard-install-sub">
              {installed
                ? "Claude Code calls go through the gate. Critical rules deny by default; edit policy.yaml to add prompt/strict modes."
                : "Install hooks so Claude Code asks AI Security before each tool call. Until then this view is observe-only over jsonl logs."}
            </div>
          </div>
          <div className="neuralguard-install-actions">
            {installed ? (
              <button className="claude-btn danger" onClick={handleUninstallHooks}>
                Uninstall
              </button>
            ) : (
              <button className="claude-btn primary" onClick={handleInstallHooks}>
                Install hooks
              </button>
            )}
          </div>
        </div>

        <div className={`neuralguard-install ${egressEnabled ? "installed" : ""}`}>
          <div className="neuralguard-install-text">
            <div className="neuralguard-install-title">
              {egressEnabled ? "Egress monitor on" : "Egress monitor off"}
            </div>
            <div className="neuralguard-install-sub">
              Polls established TCP connections from claude/opencode/kimi/codex
              processes every 30s and flags traffic to hosts not on the
              allowlist (api.anthropic.com, github.com, registry.npmjs.org,
              pypi.org, etc.).
            </div>
          </div>
          <div className="neuralguard-install-actions">
            <button
              className={`claude-btn ${egressEnabled ? "danger" : "primary"}`}
              onClick={handleToggleEgress}
            >
              {egressEnabled ? "Disable" : "Enable"}
            </button>
          </div>
        </div>

        <div className="security-stats">
          <div className="security-stat critical">
            <div className="security-stat-value">{counts.critical}</div>
            <div className="security-stat-label">Critical</div>
          </div>
          <div className="security-stat high">
            <div className="security-stat-value">{counts.high}</div>
            <div className="security-stat-label">High</div>
          </div>
          <div className="security-stat medium">
            <div className="security-stat-value">{counts.medium}</div>
            <div className="security-stat-label">Medium</div>
          </div>
          <div className="security-stat low">
            <div className="security-stat-value">{counts.low}</div>
            <div className="security-stat-label">Low</div>
          </div>
        </div>

        <div className="security-toolbar">
          <button
            className={`claude-btn ${securityFilter === "all" ? "primary" : ""}`}
            onClick={() => setSecurityFilter("all")}
          >
            All ({securityEvents.length})
          </button>
          <button
            className={`claude-btn ${securityFilter === "high+" ? "primary" : ""}`}
            onClick={() => setSecurityFilter("high+")}
          >
            High &amp; above ({counts.high + counts.critical})
          </button>
        </div>

        <div className="security-feed">
          {groups.length === 0 ? (
            <div className="security-empty">
              No security events. Run an agent and any flagged tool calls will appear here.
            </div>
          ) : (
            groups.map((g) => {
              const e = g.latest;
              const info = RULE_INFO[e.rule];
              const outcome = eventOutcome(e.decision, e.actor);
              const isOpen = !!expandedGroups[g.key];
              const isEgress = e.rule === "egress-unknown-host";
              return (
                <div key={g.key} className={`security-row severity-${e.severity}`}>
                  <div className="security-row-head">
                    <span className={`severity-pill sev-${e.severity}`}>
                      {e.severity.toUpperCase()}
                    </span>
                    <span className="security-rule">
                      {info ? info.title : e.rule}
                    </span>
                    {g.events.length > 1 && (
                      <span
                        className="security-count-badge"
                        title={`${g.events.length} events grouped — click to expand`}
                      >
                        ×{g.events.length}
                      </span>
                    )}
                    <span className={`outcome-pill outcome-${outcome.tone}`}>
                      {outcome.label}
                    </span>
                    <span className="security-tool">{e.tool}</span>
                    <span className="security-ts">{formatTs(e.ts)}</span>
                  </div>
                  <div className="security-matched">{e.matched}</div>
                  {info && (
                    <div className="security-explain">
                      <div><strong>What:</strong> {info.what}</div>
                      <div><strong>Why risky:</strong> {info.why}</div>
                      <div><strong>What to do:</strong> {info.recommend}</div>
                    </div>
                  )}
                  <div className="security-meta">
                    <span className="security-rule-id">rule: {e.rule}</span>
                    {e.agent_kind && <span>{e.agent_kind}</span>}
                    {e.agent_pid && <span>pid {e.agent_pid}</span>}
                    {e.agent_cwd && <span title={e.agent_cwd}>{e.agent_cwd.split("/").slice(-2).join("/")}</span>}
                    <span>· {e.actor} → {e.decision}</span>
                  </div>
                  <div className="security-row-actions">
                    {isEgress && (
                      <button
                        className="claude-btn small"
                        onClick={() => handleAllowHost(e)}
                        title="Add this host to your egress allowlist"
                      >
                        Allow host
                      </button>
                    )}
                    {g.events.length > 1 && (
                      <button
                        className="claude-btn small"
                        onClick={() =>
                          setExpandedGroups((prev) => ({
                            ...prev,
                            [g.key]: !prev[g.key],
                          }))
                        }
                      >
                        {isOpen ? "Collapse" : `Show ${g.events.length} occurrences`}
                      </button>
                    )}
                  </div>
                  {isOpen && g.events.length > 1 && (
                    <ul className="security-occurrences">
                      {g.events.map((occ) => (
                        <li key={occ.id}>
                          <span className="security-occ-ts">{formatTs(occ.ts)}</span>
                          <span className="security-occ-matched">{occ.matched}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    );
  }

  function usageBarColor(pct: number): string {
    if (pct >= 80) return "#ef4444";
    if (pct >= 50) return "#f59e0b";
    return "#22c55e";
  }

  function formatPct(pct: number): string {
    if (pct <= 0) return "0%";
    if (pct < 1) return `${pct.toFixed(1)}%`;
    if (pct < 10) return `${pct.toFixed(1)}%`;
    return `${Math.round(pct)}%`;
  }

  function renderSidebar() {
    return (
      <div className="sidebar">
        <div className="sidebar-header">
          <div className="sidebar-logo">SYNTHIA</div>
        </div>
        <div className="sidebar-scroll">
        <nav className="sidebar-nav">
          <button
            className={`nav-item ${currentSection === "agents" ? "active" : ""}`}
            onClick={() => setCurrentSection("agents")}
          >
            <span className="nav-item-icon">&#9881;</span>
            Agents
          </button>
          <button
            className={`nav-item ${currentSection === "security" ? "active" : ""}`}
            onClick={() => setCurrentSection("security")}
          >
            <span className="nav-item-icon">&#128737;</span>
            Security
          </button>
          <button
            className={`nav-item ${currentSection === "knowledge" ? "active" : ""}`}
            onClick={() => { setCurrentSection("knowledge"); loadNotes(""); loadKnowledgeMeta(); }}
          >
            <span className="nav-item-icon">{"\ud83e\udde0"}</span>
            Knowledge
          </button>
          <button
            className={`nav-item ${currentSection === "worktrees" ? "active" : ""}`}
            onClick={() => setCurrentSection("worktrees")}
          >
            <span className="nav-item-icon">&#128193;</span>
            Worktrees
          </button>
          <button
            className={`nav-item ${currentSection === "github" ? "active" : ""}`}
            onClick={() => setCurrentSection("github")}
          >
            <span className="nav-item-icon">&#128025;</span>
            GitHub
            {(() => { const c = githubIssues.filter(i => i.state === "OPEN").length; return c > 0 ? <span className="nav-badge">{c}</span> : null; })()}
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

            {usageStats.error ? (
              <div className="usage-error">
                Usage unavailable
                <div className="usage-error-detail">{usageStats.error}</div>
              </div>
            ) : (
              <>
                <div className="usage-section">
                  <div className="usage-label">5-hour</div>
                  <div className="usage-bar-row">
                    <div className="usage-bar">
                      <div
                        className="usage-bar-fill"
                        style={{
                          width: `${Math.min(100, usageStats.five_hour_pct)}%`,
                          background: usageBarColor(usageStats.five_hour_pct),
                        }}
                      />
                    </div>
                    <span className="usage-pct">
                      {formatPct(usageStats.five_hour_pct)}
                    </span>
                  </div>
                  {usageStats.five_hour_resets_in && (
                    <div className="usage-meta">
                      Resets in {usageStats.five_hour_resets_in}
                    </div>
                  )}
                </div>

                <div className="usage-section">
                  <div className="usage-label">7-day</div>
                  <div className="usage-bar-row">
                    <div className="usage-bar">
                      <div
                        className="usage-bar-fill"
                        style={{
                          width: `${Math.min(100, usageStats.seven_day_pct)}%`,
                          background: usageBarColor(usageStats.seven_day_pct),
                        }}
                      />
                    </div>
                    <span className="usage-pct">
                      {formatPct(usageStats.seven_day_pct)}
                    </span>
                  </div>
                  {usageStats.seven_day_resets_in && (
                    <div className="usage-meta">
                      Resets in {usageStats.seven_day_resets_in}
                    </div>
                  )}
                </div>

                {usageStats.seven_day_opus_pct !== null && (
                  <div className="usage-section">
                    <div className="usage-label">7-day Opus</div>
                    <div className="usage-bar-row">
                      <div className="usage-bar">
                        <div
                          className="usage-bar-fill"
                          style={{
                            width: `${Math.min(100, usageStats.seven_day_opus_pct ?? 0)}%`,
                            background: usageBarColor(usageStats.seven_day_opus_pct ?? 0),
                          }}
                        />
                      </div>
                      <span className="usage-pct">
                        {formatPct(usageStats.seven_day_opus_pct ?? 0)}
                      </span>
                    </div>
                    {usageStats.seven_day_opus_resets_in && (
                      <div className="usage-meta">
                        Resets in {usageStats.seven_day_opus_resets_in}
                      </div>
                    )}
                  </div>
                )}

                {usageStats.seven_day_sonnet_pct !== null && (
                  <div className="usage-section">
                    <div className="usage-label">7-day Sonnet</div>
                    <div className="usage-bar-row">
                      <div className="usage-bar">
                        <div
                          className="usage-bar-fill"
                          style={{
                            width: `${Math.min(100, usageStats.seven_day_sonnet_pct ?? 0)}%`,
                            background: usageBarColor(usageStats.seven_day_sonnet_pct ?? 0),
                          }}
                        />
                      </div>
                      <span className="usage-pct">
                        {formatPct(usageStats.seven_day_sonnet_pct ?? 0)}
                      </span>
                    </div>
                    {usageStats.seven_day_sonnet_resets_in && (
                      <div className="usage-meta">
                        Resets in {usageStats.seven_day_sonnet_resets_in}
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        )}
        </div>

        <div className="sidebar-footer">
          <button
            type="button"
            className={`voice-toggle-row ${voiceMuted ? "muted" : ""}`}
            onClick={() => handleToggleVoiceMute()}
            title={voiceMuted ? "Voice muted — click to unmute" : "Voice on — click to mute"}
            aria-pressed={!voiceMuted}
          >
            <span className="voice-toggle-icon" aria-hidden="true">
              {voiceMuted ? (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><line x1="23" y1="9" x2="17" y2="15" /><line x1="17" y1="9" x2="23" y2="15" /></svg>
              ) : (
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5" /><path d="M15.54 8.46a5 5 0 0 1 0 7.07" /><path d="M19.07 4.93a10 10 0 0 1 0 14.14" /></svg>
              )}
            </span>
            <span className="voice-toggle-label">
              <span className="voice-toggle-title">Voice output</span>
              <span className="voice-toggle-state">{voiceMuted ? "Muted" : "On"}</span>
            </span>
            <span className={`voice-toggle-switch ${voiceMuted ? "off" : "on"}`} aria-hidden="true">
              <span className="voice-toggle-switch-thumb" />
            </span>
          </button>
        </div>
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

  function renderGithubSection() {
    function timeAgo(dateStr: string): string {
      const date = new Date(dateStr);
      const now = new Date();
      const diffMs = now.getTime() - date.getTime();
      const diffMins = Math.floor(diffMs / 60000);
      if (diffMins < 60) return `${diffMins}m ago`;
      const diffHours = Math.floor(diffMins / 60);
      if (diffHours < 24) return `${diffHours}h ago`;
      const diffDays = Math.floor(diffHours / 24);
      if (diffDays < 30) return `${diffDays}d ago`;
      return date.toLocaleDateString();
    }

    function addGithubRepo() {
      const trimmed = newGithubRepo.trim();
      if (trimmed.includes("/") && !githubConfig.repos.includes(trimmed)) {
        const updated = [...githubConfig.repos, trimmed];
        saveGithubConfig(updated, githubConfig.refresh_interval_seconds);
        setNewGithubRepo("");
      }
    }

    function getRepoColorClass(repo: string): string {
      let hash = 0;
      for (let i = 0; i < repo.length; i++) {
        hash = repo.charCodeAt(i) + ((hash << 5) - hash);
      }
      return `repo-${Math.abs(hash) % 8}`;
    }

    const filteredIssues = githubIssues.filter(issue => {
      if (githubRepoFilter !== "all" && issue.repository !== githubRepoFilter) return false;
      if (githubStateFilter === "open" && issue.state !== "OPEN") return false;
      if (githubStateFilter === "closed" && issue.state !== "CLOSED") return false;
      return true;
    });

    const repos = [...new Set(githubIssues.map(i => i.repository).filter(Boolean))] as string[];
    const groupedByRepo = repos
      .filter(r => githubRepoFilter === "all" || r === githubRepoFilter)
      .map(repo => ({
        repo,
        issues: filteredIssues.filter(i => i.repository === repo),
      }))
      .filter(g => g.issues.length > 0);

    return (
      <div className="github-layout">
        <div className="github-list">
          {/* Header */}
          <div className="github-header">
            <div className="github-title-row">
              <h2 style={{ margin: 0, fontSize: "1.1rem" }}>GitHub Issues</h2>
              <div className="github-header-actions">
                <span className="github-count">{filteredIssues.length} issues</span>
                <button
                  className="github-refresh-btn"
                  onClick={() => loadGithubIssues(true)}
                  disabled={githubLoading}
                  title="Sync issues from GitHub"
                >
                  {githubLoading ? "⟳ Syncing…" : "↻ Sync"}
                </button>
                <button
                  className="github-config-btn"
                  onClick={() => setGithubConfigOpen(true)}
                  title="Configure repos"
                >
                  ⚙
                </button>
              </div>
            </div>
            {githubFetchedAt && (
              <div className="github-fetched">Updated {timeAgo(githubFetchedAt)}</div>
            )}
            {githubError && (
              <div className="github-error">{githubError}</div>
            )}

            {/* Filters */}
            <div className="github-filters">
              <select
                className="github-filter-select"
                value={githubRepoFilter}
                onChange={(e) => setGithubRepoFilter(e.target.value)}
              >
                <option value="all">All repos</option>
                {repos.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <div className="github-state-toggle">
                <button
                  className={`github-state-btn ${githubStateFilter === "open" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("open")}
                >
                  Open
                </button>
                <button
                  className={`github-state-btn ${githubStateFilter === "closed" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("closed")}
                >
                  Closed
                </button>
                <button
                  className={`github-state-btn ${githubStateFilter === "all" ? "active" : ""}`}
                  onClick={() => setGithubStateFilter("all")}
                >
                  All
                </button>
              </div>
            </div>
          </div>

          {/* Empty states */}
          {githubConfig.repos.length === 0 ? (
            <div className="empty-state">
              <p>No repos configured</p>
              <p style={{ fontSize: "0.8rem", marginTop: "0.5rem" }}>
                Click ⚙ to add GitHub repos to track
              </p>
            </div>
          ) : filteredIssues.length === 0 && !githubLoading ? (
            <div className="empty-state">
              <p>No issues assigned to you</p>
            </div>
          ) : (
            /* Issue list grouped by repo */
            groupedByRepo.map(({ repo, issues }) => (
              <div key={repo} className="github-repo-group">
                <div className="github-repo-header">
                  <span className={`worktree-repo ${getRepoColorClass(repo)}`}>
                    {repo}
                  </span>
                  <span className="github-repo-count">{issues.length}</span>
                </div>
                {issues.map(issue => (
                  <div
                    key={`${issue.repository}-${issue.number}`}
                    className={`github-issue-item ${selectedIssue?.number === issue.number && selectedIssue?.repository === issue.repository ? "selected" : ""}`}
                    onClick={() => setSelectedIssue(
                      selectedIssue?.number === issue.number && selectedIssue?.repository === issue.repository ? null : issue
                    )}
                  >
                    <div className="github-issue-header">
                      <span className={`github-issue-number ${issue.state === "OPEN" ? "open" : "closed"}`}>
                        #{issue.number}
                      </span>
                      <span className="github-issue-title">{issue.title}</span>
                    </div>
                    <div className="github-issue-meta">
                      {issue.labels.map(label => (
                        <span
                          key={label.name}
                          className="github-label"
                          style={{
                            backgroundColor: `#${label.color}33`,
                            color: `#${label.color}`,
                            border: `1px solid #${label.color}66`,
                          }}
                        >
                          {label.name}
                        </span>
                      ))}
                      {issue.milestone && (
                        <span className="github-milestone">🎯 {issue.milestone.title}</span>
                      )}
                      <span className="github-time">{timeAgo(issue.updatedAt)}</span>
                    </div>
                  </div>
                ))}
              </div>
            ))
          )}
        </div>

        {/* Detail panel */}
        {selectedIssue && (
          <div className="task-panel" style={{ minWidth: "350px" }}>
            <div className="task-panel-header">
              <span className="task-panel-title">#{selectedIssue.number}</span>
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <button
                  className="task-panel-btn primary"
                  onClick={() => {
                    if (selectedIssue.url) {
                      openUrl(selectedIssue.url);
                    }
                  }}
                >
                  Open in GitHub
                </button>
                <button
                  className="task-panel-btn"
                  onClick={() => setSelectedIssue(null)}
                  title="Close panel"
                >
                  ✕
                </button>
              </div>
            </div>
            <h3 style={{ margin: "0 0 0.75rem", fontSize: "1rem", fontWeight: 500 }}>
              {selectedIssue.title}
            </h3>
            <div className="github-detail-meta">
              <span className={`github-state-badge ${selectedIssue.state === "OPEN" ? "open" : "closed"}`}>
                {selectedIssue.state === "OPEN" ? "● Open" : "● Closed"}
              </span>
              {selectedIssue.assignees.map(a => (
                <span key={a.login} className="github-assignee">@{a.login}</span>
              ))}
              <span className="github-comments">{selectedIssue.comments.length} comments</span>
            </div>
            {selectedIssue.labels.length > 0 && (
              <div className="github-detail-labels">
                {selectedIssue.labels.map(label => (
                  <span
                    key={label.name}
                    className="github-label"
                    style={{
                      backgroundColor: `#${label.color}33`,
                      color: `#${label.color}`,
                      border: `1px solid #${label.color}66`,
                    }}
                  >
                    {label.name}
                  </span>
                ))}
              </div>
            )}
            {selectedIssue.body && (
              <div className="github-issue-body">
                <pre style={{
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  fontSize: "0.85rem",
                  lineHeight: 1.5,
                  color: "#e2e8f0",
                  margin: 0,
                  fontFamily: "inherit",
                }}>
                  {selectedIssue.body}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Config modal */}
        {githubConfigOpen && (
          <div className="modal-overlay" onClick={() => setGithubConfigOpen(false)}>
            <div className="modal-content" onClick={(e) => e.stopPropagation()}>
              <h3 style={{ margin: "0 0 1rem" }}>GitHub Repos</h3>
              <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
                <input
                  className="github-repo-input"
                  type="text"
                  placeholder="owner/repo"
                  value={newGithubRepo}
                  onChange={(e) => setNewGithubRepo(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") addGithubRepo();
                  }}
                />
                <button
                  className="task-panel-btn primary"
                  onClick={addGithubRepo}
                >
                  Add
                </button>
              </div>
              <div className="github-repo-list">
                {githubConfig.repos.map((repo, i) => (
                  <div key={repo} className="github-repo-list-item">
                    <span>{repo}</span>
                    <button
                      className="github-repo-remove"
                      onClick={() => {
                        const updated = githubConfig.repos.filter((_, idx) => idx !== i);
                        saveGithubConfig(updated, githubConfig.refresh_interval_seconds);
                      }}
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
              <button
                className="task-panel-btn primary"
                style={{ marginTop: "1rem" }}
                onClick={() => setGithubConfigOpen(false)}
              >
                Done
              </button>
            </div>
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

    // Skill edit modal
    if (editingSkill) {
      return (
        <div className="config-section">
          <div className="claude-modal">
            <div className="claude-modal-header">
              <span>{isNewSkill ? "New Skill" : `Edit: ${editingSkill.name}`}</span>
              <button
                className="claude-modal-close"
                onClick={() => { setEditingSkill(null); setIsNewSkill(false); setOriginalSkillName(null); }}
              >×</button>
            </div>
            <div className="claude-modal-body">
              {editingSkill.has_resources && !isNewSkill && (
                <div className="claude-edit-warning">
                  This skill has additional resource files; only SKILL.md is edited here.
                </div>
              )}
              <div className="claude-edit-field">
                <label>Name:</label>
                <input
                  type="text"
                  value={editingSkill.name}
                  onChange={(e) => setEditingSkill({ ...editingSkill, name: e.target.value })}
                  placeholder="my-skill"
                />
              </div>
              <div className="claude-edit-field">
                <label>Description:</label>
                <input
                  type="text"
                  value={editingSkill.description}
                  onChange={(e) => setEditingSkill({ ...editingSkill, description: e.target.value })}
                  placeholder="Use when... (trigger phrase guides the model)"
                />
              </div>
              <div className="claude-edit-field">
                <label>Body (markdown):</label>
                <textarea
                  value={editingSkill.body}
                  onChange={(e) => setEditingSkill({ ...editingSkill, body: e.target.value })}
                  rows={18}
                />
              </div>
            </div>
            <div className="claude-modal-footer">
              <button
                className="claude-btn primary"
                onClick={() => handleSaveSkill(editingSkill)}
              >
                Save
              </button>
              <button
                className="claude-btn"
                onClick={() => { setEditingSkill(null); setIsNewSkill(false); setOriginalSkillName(null); }}
              >
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
            className={`config-tab ${configTab === "skills" ? "active" : ""}`}
            onClick={() => setConfigTab("skills")}
          >
            Skills
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

        {configTab === "skills" && (
          <div className="claude-list-section">
            <div className="claude-list-header">
              <span>Skills ({skills.length})</span>
              <button
                className="claude-btn primary"
                onClick={() => {
                  setEditingSkill({
                    name: "new-skill",
                    description: "",
                    body: "",
                    is_dir: true,
                    has_resources: false,
                  });
                  setOriginalSkillName(null);
                  setIsNewSkill(true);
                }}
              >
                + New Skill
              </button>
            </div>
            <div className="claude-list">
              {skills.length === 0 ? (
                <div className="claude-empty">No user skills found</div>
              ) : (
                skills.map((skill) => (
                  <div key={skill.name} className="claude-item">
                    <div className="claude-item-main">
                      <div className="claude-item-info">
                        <div className="claude-item-name">
                          {skill.name}
                          {skill.has_resources && (
                            <span className="claude-item-badge" title="Has additional files in skill folder">
                              + files
                            </span>
                          )}
                        </div>
                        <div className="claude-item-desc">{skill.description || "No description"}</div>
                      </div>
                    </div>
                    <div className="claude-item-actions">
                      <button
                        className="claude-btn"
                        onClick={() => {
                          setEditingSkill(skill);
                          setOriginalSkillName(skill.name);
                          setIsNewSkill(false);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="claude-btn danger"
                        onClick={() => handleDeleteSkill(skill.name)}
                      >
                        Delete
                      </button>
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

  function renderFolderTree(parentPath: string, depth: number = 0) {
    const entries = allNoteEntries[parentPath] || [];
    const folders = entries.filter((e) => e.is_dir).sort((a, b) => a.name.localeCompare(b.name));
    const files = entries.filter((e) => !e.is_dir).sort((a, b) => a.name.localeCompare(b.name));

    return (
      <div className="knowledge-tree-level">
        {folders.map((folder) => {
          const isExpanded = expandedFolders.includes(folder.path);
          return (
            <div key={folder.path}>
              <button
                className="knowledge-tree-item knowledge-tree-folder"
                style={{ paddingLeft: `${12 + depth * 16}px` }}
                onClick={() => toggleFolder(folder.path)}
              >
                <span className="knowledge-tree-arrow">
                  {isExpanded ? "\u25BE" : "\u25B8"}
                </span>
                <span className="knowledge-tree-name">{folder.name}</span>
              </button>
              {isExpanded && renderFolderTree(folder.path, depth + 1)}
            </div>
          );
        })}
        {files.map((file) => (
          <button
            key={file.path}
            className="knowledge-tree-item knowledge-tree-file"
            style={{ paddingLeft: `${28 + depth * 16}px` }}
            onClick={() => handleOpenNote(file.path)}
            onContextMenu={(e) => handleNoteContextMenu(e, file.path)}
          >
            <span className="knowledge-tree-name">{file.name}</span>
          </button>
        ))}
      </div>
    );
  }

  function renderKnowledgeSection() {
    // Editor view
    if (noteEditing && selectedNote) {
      const fileName = selectedNote.split("/").pop() || selectedNote;
      const isPinned = pinnedNotes.includes(selectedNote);
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
                className={`notes-pin-btn ${isPinned ? "active" : ""}`}
                onClick={() => togglePinNote(selectedNote)}
                title={isPinned ? "Unpin" : "Pin"}
              >
                {isPinned ? "Unpin" : "Pin"}
              </button>
              <button
                className={`notes-preview-btn ${notePreview === false ? "active" : ""}`}
                onClick={() => setNotePreview(notePreview === false ? null : false)}
              >
                Edit
              </button>
              <button
                className={`notes-preview-btn ${notePreview === true ? "active" : ""}`}
                onClick={() => setNotePreview(notePreview === true ? null : true)}
              >
                Preview
              </button>
              <button
                className={`notes-copy-path-btn ${copiedPath ? "copied" : ""}`}
                onClick={() => handleCopyPath(selectedNote)}
                title="Copy file path"
              >
                {copiedPath ? "Copied!" : "Copy Path"}
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
          {notePreview === true ? (
            <div className="notes-preview">
              <Markdown>{noteContent}</Markdown>
            </div>
          ) : notePreview === false ? (
            <textarea
              className="notes-editor"
              value={noteContent}
              onChange={(e) => setNoteContent(e.target.value)}
              spellCheck={false}
            />
          ) : (
            <div className="notes-split-pane">
              <textarea
                className="notes-editor"
                value={noteContent}
                onChange={(e) => setNoteContent(e.target.value)}
                spellCheck={false}
              />
              <div className="notes-preview">
                <Markdown>{noteContent}</Markdown>
              </div>
            </div>
          )}
          {contextMenu && (
            <div
              className="note-context-menu"
              style={{ top: contextMenu.y, left: contextMenu.x }}
              onMouseDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              <button
                className="note-context-menu-item"
                onClick={() => {
                  handleCopyPath(contextMenu.notePath);
                  setContextMenu(null);
                }}
              >
                Copy file path
              </button>
            </div>
          )}
        </div>
      );
    }

    // Dashboard view
    return (
      <div className="knowledge-dashboard">
        {/* Full-width search bar */}
        <div className="knowledge-top-bar">
          <div className="knowledge-search">
            <span className="knowledge-search-icon">{"\ud83d\udd0d"}</span>
            <input
              type="text"
              placeholder="Search notes..."
              value={knowledgeSearch}
              onChange={(e) => setKnowledgeSearch(e.target.value)}
              className="knowledge-search-input"
            />
            {knowledgeSearch && (
              <button
                className="knowledge-search-clear"
                onClick={() => setKnowledgeSearch("")}
              >
                {"\u2715"}
              </button>
            )}
          </div>
          <button
            className="knowledge-new-btn"
            onClick={() => setShowNewNote(true)}
          >
            + New
          </button>
        </div>

        {/* New note modal */}
        {showNewNote && (
          <div className="new-note-modal">
            <input
              type="text"
              placeholder="Note or folder name..."
              value={newNoteName}
              onChange={(e) => setNewNoteName(e.target.value)}
              className="new-note-input"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === "Enter") handleCreateNote();
                if (e.key === "Escape") setShowNewNote(false);
              }}
            />
            <button className="new-note-create" onClick={handleCreateNote}>
              Note
            </button>
            <button
              className="new-note-create folder"
              onClick={handleCreateFolder}
            >
              Folder
            </button>
            <button
              className="new-note-create"
              onClick={() => setShowNewNote(false)}
              style={{ background: "rgba(100,100,100,0.3)" }}
            >
              Cancel
            </button>
          </div>
        )}

        {/* Two-column layout */}
        <div className="knowledge-columns">
          {/* Left column - folder tree */}
          <div className="knowledge-tree-panel">
            <div className="knowledge-section-label">FOLDERS</div>
            <div className="knowledge-tree-scroll">
              {renderFolderTree("")}
            </div>
          </div>

          {/* Right column - pinned cards + recent */}
          <div className="knowledge-content-panel">
            {knowledgeSearch ? (
              <div className="knowledge-search-results">
                <div className="knowledge-section-label">RESULTS</div>
                {noteEntries
                  .filter((e) =>
                    !e.is_dir &&
                    e.name.toLowerCase().includes(knowledgeSearch.toLowerCase())
                  )
                  .map((entry) => (
                    <button
                      key={entry.path}
                      className="knowledge-search-result-item"
                      onClick={() => handleOpenNote(entry.path)}
                      onContextMenu={(e) => handleNoteContextMenu(e, entry.path)}
                    >
                      <span className="knowledge-result-name">{entry.name}</span>
                      <span className="knowledge-result-path">
                        {entry.path.split("/").slice(0, -1).join(" / ")}
                      </span>
                    </button>
                  ))}
              </div>
            ) : (
              <>
                {pinnedNotes.length > 0 && (
                  <div className="knowledge-pinned-section">
                    <div className="knowledge-section-label">PINNED</div>
                    <div className="knowledge-cards-grid">
                      {pinnedNotes.map((path) => {
                        const name = path.split("/").pop() || path;
                        const preview = pinnedPreviews[path] || "";
                        const modified = noteModified[path] || 0;
                        return (
                          <button
                            key={path}
                            className="knowledge-card"
                            onClick={() => handleOpenNote(path)}
                            onContextMenu={(e) => handleNoteContextMenu(e, path)}
                          >
                            <div className="knowledge-card-title">{name.replace(/\.md$/, "")}</div>
                            <div className="knowledge-card-preview">
                              {preview.replace(/^#+ .*/gm, "").trim().slice(0, 120)}
                            </div>
                            <div className="knowledge-card-meta">
                              {getRelativeTime(modified)}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}

                {recentNotes.length > 0 && (
                  <div className="knowledge-recent-section">
                    <div className="knowledge-section-label">RECENT</div>
                    <div className="knowledge-recent-list">
                      {recentNotes.map((path) => {
                        const name = path.split("/").pop() || path;
                        return (
                          <button
                            key={path}
                            className="knowledge-recent-item"
                            onClick={() => handleOpenNote(path)}
                            onContextMenu={(e) => handleNoteContextMenu(e, path)}
                          >
                            <span className="knowledge-recent-name">
                              {name.replace(/\.md$/, "")}
                            </span>
                            <span className="knowledge-recent-time">
                              {getRelativeTime(noteModified[path] || 0)}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
        {contextMenu && (
          <div
            className="note-context-menu"
            style={{ top: contextMenu.y, left: contextMenu.x }}
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => e.stopPropagation()}
          >
            <button
              className="note-context-menu-item"
              onClick={() => {
                handleCopyPath(contextMenu.notePath);
                setContextMenu(null);
              }}
            >
              Copy file path
            </button>
          </div>
        )}
      </div>
    );
  }

  function renderPromptModal() {
    if (pendingPrompts.length === 0) return null;
    const p = pendingPrompts[0];
    const raw = (p.raw ?? {}) as Record<string, unknown>;
    const command =
      (raw.command as string | undefined) ??
      (raw.file_path as string | undefined) ??
      (raw.url as string | undefined) ??
      JSON.stringify(p.raw, null, 2);
    return (
      <div className="prompt-modal-backdrop">
        <div className="prompt-modal">
          <div className="prompt-modal-header">
            <span className="prompt-modal-title">⛨ AI Security — confirm tool call</span>
            <span className="prompt-modal-pid">pid {p.agent_pid ?? "?"}</span>
          </div>
          <div className="prompt-modal-body">
            <div className="prompt-modal-tool">{p.tool}</div>
            <pre className="prompt-modal-cmd">{command}</pre>
            <div className="prompt-modal-rules">
              {p.events.map((ev, i) => {
                const info = RULE_INFO[ev.rule];
                return (
                  <div key={i} className={`prompt-rule sev-${ev.severity}`}>
                    <span className={`severity-pill sev-${ev.severity}`}>{ev.severity.toUpperCase()}</span>
                    <span title={info ? info.why : ev.rule}>{info ? info.title : ev.rule}</span>
                    <span className="prompt-rule-match">{ev.matched}</span>
                  </div>
                );
              })}
            </div>
          </div>
          <div className="prompt-modal-footer">
            <button className="claude-btn danger" onClick={() => handlePromptDecision(p.id, "deny")}>
              Deny
            </button>
            <button className="claude-btn primary" onClick={() => handlePromptDecision(p.id, "allow")}>
              Allow once
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-layout">
      {renderSidebar()}
      {renderPromptModal()}
      <main className="main-content">
        {currentSection === "agents" && renderAgentsSection()}
        {currentSection === "security" && renderSecuritySection()}
        {currentSection === "worktrees" && renderWorktreesSection()}
        {currentSection === "github" && renderGithubSection()}
        {currentSection === "knowledge" && renderKnowledgeSection()}
        {currentSection === "voice" && renderVoiceSection()}
        {currentSection === "memory" && renderMemorySection()}
        {currentSection === "config" && renderConfigSection()}
      </main>
    </div>
  );
}

export default App;
