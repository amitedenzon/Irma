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
      const saved = initial ? await updateProject(initial.id, payload) : await createProject(payload);
      onSaved(saved);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="paper-inset ink-frame-thin p-5 space-y-3">
      <div className="flex items-baseline justify-between mb-1">
        <h2 style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
            className="text-[12px] uppercase tracking-[0.18em]">
          {initial ? "▶ edit project" : "▶ new project"}
        </h2>
        <button type="button" onClick={onClose}
                className="text-[10px] uppercase tracking-wider"
                style={{ color: "var(--color-ink-mute)" }}>
          cancel
        </button>
      </div>

      <Field label="name *">
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus className="field w-full" />
      </Field>

      <Field label="description">
        <textarea value={description} onChange={(e) => setDescription(e.target.value)}
                  rows={2} className="field w-full" />
      </Field>

      <div className="grid grid-cols-3 gap-3">
        <Field label="priority">
          <select value={priority} onChange={(e) => setPriority(Number(e.target.value) as 1 | 2 | 3)}
                  className="field w-full">
            <option value={1}>1 · high</option>
            <option value={2}>2 · medium</option>
            <option value={3}>3 · low</option>
          </select>
        </Field>
        <Field label="status">
          <select value={status} onChange={(e) => setStatus(e.target.value as ProjectStatus)}
                  className="field w-full">
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="target date">
          <input type="date" value={target} onChange={(e) => setTarget(e.target.value)}
                 className="field w-full" />
        </Field>
      </div>

      <Field label="calendar keywords  ·  comma separated">
        <input value={keywords} onChange={(e) => setKeywords(e.target.value)}
               placeholder="gal, thesis, advisor"
               className="field w-full" />
      </Field>

      <Field label="goals  ·  one per line">
        <textarea value={goals} onChange={(e) => setGoals(e.target.value)} rows={3}
                  placeholder={"Submit draft by 2026-07-15\nFinish coursework end of June"}
                  className="field w-full" />
      </Field>

      {error && (
        <div className="text-[12px]" style={{ color: "var(--color-red-seal)" }}>
          !! {error}
        </div>
      )}

      <div className="flex justify-end gap-2 pt-2">
        <button type="button" onClick={onClose}
                className="text-[11px] uppercase tracking-wider px-3 py-1.5"
                style={{ color: "var(--color-ink-mute)", border: "1px solid var(--color-rule)", fontFamily: "var(--font-mono)" }}>
          cancel
        </button>
        <button type="submit" disabled={busy || !name.trim()}
                className="wax-seal text-[11px] uppercase tracking-wider px-4 py-1.5"
                style={{ fontFamily: "var(--font-mono)" }}>
          {initial ? (busy ? "saving…" : "save") : (busy ? "stamping…" : "create")}
        </button>
      </div>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-widest block mb-1"
            style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
        {label}
      </span>
      {children}
    </label>
  );
}
