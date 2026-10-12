import type { Status } from "./format";

export interface SubAgent {
  id: string;
  description: string;
  agentType: string;
  model: string;
  live: boolean;
}

export interface FleetNode {
  paneId: string;
  agent: string;
  status: Status;
  title: string;
  repo: string;
  cwd: string;
  session: string | null;
  sinceMs: number;
  subagents: SubAgent[];
  /** Squad registry fields; all null for an ordinary agent. */
  squad: string | null;
  job: string | null;
  role: string | null;
  roleTitle: string | null;
  /** Pane id of the director a specialist reports to. */
  parent: string | null;
}

export interface Fleet {
  nodes: FleetNode[];
  herdrOk: boolean;
  error: string | null;
}

export interface DaySubAgent {
  description: string;
  agentType: string;
  model: string;
  firstSeen: number;
  lastSeen: number;
  lastLive: boolean;
}

export interface DayNode {
  paneId: string;
  agent: string;
  title: string;
  repo: string;
  session: string | null;
  firstSeen: number;
  lastSeen: number;
  lastStatus: Status;
  subagents: Record<string, DaySubAgent>;
}

export interface DayChart {
  date: string;
  nodes: Record<string, DayNode>;
}

export interface UsageStats {
  five_hour_pct: number;
  five_hour_resets_in: string;
  seven_day_pct: number;
  error: string | null;
}

export interface SynthiaState {
  status: string;
  recording: boolean;
  /** "murmur" when Murmur hears the assistant key. */
  stt_source?: string | null;
  /** Murmur's assistant key label: missing/null = unknown, "" = none set in Murmur. */
  talk_key?: string | null;
}

export const MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"] as const;

export interface RoleInfo {
  id: string;
  title: string;
  model: string;
  hires: string[];
  description: string;
  prompt: string;
  hasAgentFile: boolean;
}

export interface JobInfo {
  id: string;
  path: string;
  state: string;
  updatedMs: number;
  lastLog: string | null;
}

export interface SquadInfo {
  id: string;
  name: string;
  director: string;
  cap: number;
  cwd: string;
  roles: RoleInfo[];
  jobs: JobInfo[];
}

export interface RoleFields {
  title?: string;
  model?: string;
  hires?: string[];
  prompt?: string;
}
