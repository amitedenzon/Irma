import type {
  ChatMessage,
  ChatResponse,
  Project,
  ProjectCreate,
  ProjectStatus,
  ProjectUpdate,
  Signal,
  Task,
  TaskCreate,
  TaskStatus,
  TaskUpdate,
} from "./types";

const BASE_URL: string =
  (import.meta.env.VITE_IRMA_API as string | undefined) ??
  "http://127.0.0.1:8765";

export const IRMA_API_BASE = BASE_URL;

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${detail}`);
  }
  return (await res.json()) as T;
}

async function noContent(res: Response): Promise<void> {
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText} — ${detail}`);
  }
}

function url(
  path: string,
  params?: Record<string, string | string[] | undefined>,
): string {
  const u = new URL(`${BASE_URL}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined) continue;
      if (Array.isArray(v)) v.forEach((vi) => u.searchParams.append(k, vi));
      else u.searchParams.append(k, v);
    }
  }
  return u.toString();
}

// --- Projects -------------------------------------------------------------

export async function listProjects(statuses?: ProjectStatus[]): Promise<Project[]> {
  return jsonOrThrow(await fetch(url("/api/v1/projects", { status: statuses })));
}

export async function createProject(p: ProjectCreate): Promise<Project> {
  return jsonOrThrow(
    await fetch(url("/api/v1/projects"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }),
  );
}

export async function getProject(id: string): Promise<Project> {
  return jsonOrThrow(await fetch(url(`/api/v1/projects/${id}`)));
}

export async function updateProject(id: string, patch: ProjectUpdate): Promise<Project> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/projects/${id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteProject(id: string): Promise<void> {
  await noContent(await fetch(url(`/api/v1/projects/${id}`), { method: "DELETE" }));
}

// --- Tasks ----------------------------------------------------------------

export async function listTasks(opts: {
  project_id?: string;
  status?: TaskStatus[];
  scheduled_from?: string;
  scheduled_to?: string;
  due_before?: string;
} = {}): Promise<Task[]> {
  return jsonOrThrow(
    await fetch(
      url("/api/v1/tasks", {
        project_id: opts.project_id,
        status: opts.status,
        scheduled_from: opts.scheduled_from,
        scheduled_to: opts.scheduled_to,
        due_before: opts.due_before,
      }),
    ),
  );
}

export async function createTask(t: TaskCreate): Promise<Task> {
  return jsonOrThrow(
    await fetch(url("/api/v1/tasks"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(t),
    }),
  );
}

export async function updateTask(id: string, patch: TaskUpdate): Promise<Task> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/tasks/${id}`), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    }),
  );
}

export async function deleteTask(id: string): Promise<void> {
  await noContent(await fetch(url(`/api/v1/tasks/${id}`), { method: "DELETE" }));
}

export async function completeTask(id: string): Promise<Task> {
  return jsonOrThrow(
    await fetch(url(`/api/v1/tasks/${id}/complete`), { method: "POST" }),
  );
}

// --- Brief (email-only) ---------------------------------------------------

export async function sendBriefEmail(): Promise<{ status: string; detail: string }> {
  return jsonOrThrow(
    await fetch(url("/api/v1/brief/email"), { method: "POST" }),
  );
}

// --- Signals / refresh / chat (existing, kept) ----------------------------

export async function fetchSignals(): Promise<Signal[]> {
  return jsonOrThrow(await fetch(url("/api/v1/signals")));
}

export async function forceRefresh(): Promise<void> {
  await noContent(await fetch(url("/api/v1/refresh"), { method: "POST" }));
}

export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
  return jsonOrThrow(
    await fetch(url("/api/v1/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages }),
    }),
  );
}
