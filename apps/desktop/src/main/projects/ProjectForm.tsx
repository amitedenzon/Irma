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
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const payload: ProjectCreate = {
        name: name.trim(),
        description,
        priority,
        status,
        calendar_keywords: keywords.split(",").map((s) => s.trim()).filter(Boolean),
        goals: goals.split("\n").map((s) => s.trim()).filter(Boolean),
        target_date: target || null,
      };
      onSaved(initial ? await updateProject(initial.id, payload) : await createProject(payload));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="card p-5 space-y-4">
      <div className="flex items-baseline justify-between">
        <h2 className="display text-[15px] font-semibold" style={{ color: "var(--color-ink)" }}>
          {initial ? "Edit project" : "New project"}
        </h2>
        <button type="button" onClick={onClose} className="btn-link" style={{ color: "var(--color-ink-mute)" }}>
          cancel
        </button>
      </div>

      <Field label="Name">
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus className="input" />
      </Field>

      <Field label="Description">
        <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                  rows={2} className="input resize-y" />
      </Field>

      <div className="grid grid-cols-3 gap-3">
        <Field label="Priority">
          <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}
                  className="input">
            <option value={1}>P1 · high</option>
            <option value={2}>P2 · medium</option>
            <option value={3}>P3 · low</option>
          </select>
        </Field>
        <Field label="Status">
          <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)} className="input">
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Target date">
          <input type="date" value={target} onChange={(e) => setTarget(e.target.value)} className="input" />
        </Field>
      </div>

      <Field label="Calendar keywords" hint="comma separated">
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
               placeholder="gal, thesis, advisor" className="input" />
      </Field>

      <Field label="Goals" hint="one per line">
        <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={3}
                  placeholder={"Submit draft by 2026-07-15\nFinish coursework end of June"}
                  className="input resize-y" />
      </Field>

      {error && (
        <div className="text-[13px]" style={{ color: "var(--color-red)" }}>
          {error}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-1">
        <button type="button" onClick={onClose} className="btn-ghost">cancel</button>
        <button type="submit" disabled={busy || !name.trim()} className="btn-red">
          {initial ? (busy ? "saving…" : "save") : (busy ? "creating…" : "create")}
        </button>
      </div>
    </form>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="flex items-baseline gap-2 text-[12px] font-medium mb-1.5"
            style={{ color: "var(--color-ink)" }}>
        {label}
        {hint && <span className="text-[11px] font-normal" style={{ color: "var(--color-ink-faint)" }}>· {hint}</span>}
      </span>
      {children}
    </label>
  );
}
