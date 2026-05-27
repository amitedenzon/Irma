import { useState } from "react";
import { createProject, updateProject } from "../../lib/api";
import type { Project, ProjectCreate, ProjectStatus } from "../../lib/types";

const STATUSES: ProjectStatus[] = ["active", "paused", "archived"];

export function ProjectForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: Project | null;
  onClose: () => void;
  onSaved: (p: Project) => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [priority, setPriority] = useState<1 | 2 | 3>(initial?.priority ?? 2);
  const [keywords, setKeywords] = useState(initial?.calendar_keywords.join(", ") ?? "");
  const [goals, setGoals] = useState(initial?.goals.join("\n") ?? "");
  const [target, setTarget] = useState(initial?.target_date ?? "");
  const [status, setStatus] = useState<ProjectStatus>(initial?.status ?? "active");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    try {
      const payload: ProjectCreate = {
        name: name.trim(),
        description,
        priority,
        status,
        calendar_keywords: keywords
          .split(",").map((s) => s.trim()).filter(Boolean),
        goals: goals.split("\n").map((s) => s.trim()).filter(Boolean),
        target_date: target || null,
      };
      const saved = initial
        ? await updateProject(initial.id, payload)
        : await createProject(payload);
      onSaved(saved);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-10">
      <form onSubmit={submit}
            className="bg-irma-surface border border-irma-border rounded-lg p-5 w-[28rem] space-y-3">
        <h2 className="font-medium">{initial ? "Edit project" : "New project"}</h2>
        <label className="block text-xs text-irma-mute">name
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus
                 className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <label className="block text-xs text-irma-mute">description
          <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                    className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <div className="flex gap-3 text-xs text-irma-mute">
          <label>priority
            <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              <option value={1}>1 high</option>
              <option value={2}>2 med</option>
              <option value={3}>3 low</option>
            </select>
          </label>
          <label>status
            <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>target
            <input type="date" value={target} onChange={(e) => setTarget(e.target.value)}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
        </div>
        <label className="block text-xs text-irma-mute">calendar keywords (comma separated)
          <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
                 className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <label className="block text-xs text-irma-mute">goals (one per line)
          <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={3}
                    className="block w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text" />
        </label>
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="px-3 py-1 text-irma-mute">cancel</button>
          <button type="submit" disabled={busy || !name.trim()}
                  className="px-3 py-1 border border-irma-indigo text-irma-indigo rounded">
            {initial ? "save" : "create"}
          </button>
        </div>
      </form>
    </div>
  );
}
