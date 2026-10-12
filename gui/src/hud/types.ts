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
}
