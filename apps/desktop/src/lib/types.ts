export type AgentState = "idle" | "observing" | "thinking" | "alert";

export interface SpriteFrameSpec {
  frames: number[];
  fps: number;
  loop: boolean;
}

export interface SpriteManifest {
  image: string;
  /** Source-pixel width of one frame in the sheet. */
  frameWidth: number;
  /** Source-pixel height of one frame in the sheet. */
  frameHeight: number;
  /** Number of frame columns per row. Required for 2D index → (col, row). */
  columns: number;
  /** Optional, for documentation only. */
  rows?: number;
  /** Display multiplier — `1` renders at native pixel size. */
  scale?: number;
  states: Record<AgentState, SpriteFrameSpec>;
  /** Optional named overlay animations (e.g. `cuddle`) Companion can swap in. */
  extras?: Record<string, SpriteFrameSpec>;
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
