export type AgentState = "idle" | "observing" | "thinking" | "alert";

export interface SpriteFrameSpec {
  frames: number[];
  fps: number;
  loop: boolean;
}

export interface SpriteManifest {
  /** Sprite sheet filename, relative to `/sprites/dogs/`. */
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

export interface Signal {
  source: "calendar" | "codebase";
  kind: string;
  title: string;
  detail: string;
  ts: string;
  meta: Record<string, unknown>;
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
  image_b64?: string;  // base64-encoded image for vision models
}

export interface ChatResponse {
  reply: string;
  backend: string;
  model: string;
}

// --- Projects + Tasks ----------------------------------------------------

export type ProjectStatus = "active" | "paused" | "archived";

export interface Project {
  id: string;
  name: string;
  description: string;
  status: ProjectStatus;
  priority: 1 | 2 | 3;
  calendar_keywords: string[];
  goals: string[];
  target_date: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  status?: ProjectStatus;
  priority?: 1 | 2 | 3;
  calendar_keywords?: string[];
  goals?: string[];
  target_date?: string | null;
}

export type ProjectUpdate = Partial<ProjectCreate>;

export type TaskStatus = "todo" | "doing" | "done" | "blocked";

export interface Task {
  id: string;
  project_id: string;
  title: string;
  notes: string;
  status: TaskStatus;
  due_date: string | null;
  scheduled_for: string | null;
  estimated_minutes: number | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
}

export interface TaskCreate {
  project_id: string;
  title: string;
  notes?: string;
  status?: TaskStatus;
  due_date?: string | null;
  scheduled_for?: string | null;
  estimated_minutes?: number | null;
}

export type TaskUpdate = Partial<Omit<TaskCreate, "project_id">>;

// --- Brief ---------------------------------------------------------------

export type Horizon = "day" | "week" | "month" | "all";

export type FocusKind = "task" | "event";

export interface FocusItem {
  kind: FocusKind;
  title: string;
  project_id: string | null;
  project_name: string | null;
  task_id: string | null;
  due_date: string | null;
  scheduled_for: string | null;
  when: string | null;
  note: string;
}

export interface ProjectStatusItem {
  project_id: string;
  project_name: string;
  open_tasks: number;
  done_tasks: number;
  days_to_target: number | null;
  note: string;
}

export interface Brief {
  horizon: Horizon;
  generated_at: string;
  focus: FocusItem[];
  project_status: ProjectStatusItem[];
  conflicts: string[];
  recommendation: string;
  narrative: string;
}
