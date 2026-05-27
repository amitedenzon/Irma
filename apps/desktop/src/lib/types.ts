export type AgentState = "idle" | "observing" | "thinking" | "alert";

export interface SpriteFrameSpec {
  frames: number[];
  fps: number;
  loop: boolean;
}

export interface SpriteManifest {
  image: string;
  frameWidth: number;
  frameHeight: number;
  states: Record<AgentState, SpriteFrameSpec>;
}

export interface ScheduleItem {
  ts: string;
  title: string;
  epic: string | null;
}

export interface StandupBrief {
  generated_at: string;
  velocity: string;
  blockers: string[];
  conflicts: string[];
  schedule: ScheduleItem[];
  recommendation: string;
  narrative: string;
}

export interface Signal {
  source: "calendar" | "codebase";
  kind: string;
  title: string;
  detail: string;
  ts: string;
  meta: Record<string, unknown>;
}
