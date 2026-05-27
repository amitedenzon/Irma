import { useState } from "react";
import { deleteProject, updateProject } from "../../lib/api";
import type { Project } from "../../lib/types";
import { ProjectForm } from "./ProjectForm";
import { TaskList } from "./TaskList";

export function ProjectCard({
  project,
  onChanged,
  onDeleted,
}: {
  project: Project;
  onChanged: (p: Project) => void;
  onDeleted: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [showGoals, setShowGoals] = useState(false);

  const archive = async () => {
    onChanged(await updateProject(project.id, { status: "archived" }));
  };
  const unarchive = async () => {
    onChanged(await updateProject(project.id, { status: "active" }));
  };
  const remove = async () => {
    if (!confirm(`Delete "${project.name}"? Existing non-done tasks block this.`)) return;
    try {
      await deleteProject(project.id);
      onDeleted(project.id);
    } catch (e) {
      alert(`Cannot delete: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const daysToTarget = project.target_date
    ? Math.ceil((new Date(project.target_date).getTime() - Date.now()) / 86_400_000)
    : null;

  if (editing) {
    return (
      <ProjectForm
        initial={project}
        onClose={() => setEditing(false)}
        onSaved={(p) => { onChanged(p); setEditing(false); }}
      />
    );
  }

  return (
    <article className="card p-5">
      <header className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <h2 className="display text-[17px] font-semibold leading-tight"
              style={{ color: "var(--color-ink)" }}>
            {project.name}
          </h2>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[12px]"
               style={{ color: "var(--color-ink-mute)" }}>
            <span className={priorityClass(project.priority)}>P{project.priority}</span>
            {project.status !== "active" && (
              <span className="badge">{project.status}</span>
            )}
            {project.target_date && (
              <span style={{ color: daysToTarget !== null && daysToTarget < 7 ? "var(--color-red)" : undefined }}>
                {project.target_date}
                {daysToTarget !== null &&
                  (daysToTarget >= 0 ? ` · ${daysToTarget}d left` : ` · ${-daysToTarget}d overdue`)}
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
          <button onClick={() => setEditing(true)} className="hover:underline">edit</button>
          {project.status !== "archived" ? (
            <button onClick={() => void archive()} className="hover:underline">archive</button>
          ) : (
            <button onClick={() => void unarchive()} className="hover:underline">restore</button>
          )}
          <button onClick={() => void remove()} className="hover:underline" style={{ color: "var(--color-red)" }}>delete</button>
        </div>
      </header>

      {project.description && (
        <p className="text-[13px] leading-relaxed mb-3" style={{ color: "var(--color-ink)" }}>
          {project.description}
        </p>
      )}

      {project.goals.length > 0 && (
        <div className="mb-3">
          <button onClick={() => setShowGoals((v) => !v)}
                  className="text-[11px] uppercase tracking-wider hover:underline"
                  style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
            {showGoals ? "▾" : "▸"} goals ({project.goals.length})
          </button>
          {showGoals && (
            <ul className="mt-2 space-y-1">
              {project.goals.map((g, i) => (
                <li key={i} className="text-[13px] leading-snug flex gap-2"
                    style={{ color: "var(--color-ink)" }}>
                  <span style={{ color: "var(--color-red)" }}>·</span>
                  <span>{g}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {project.calendar_keywords.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {project.calendar_keywords.map((kw) => (
            <span key={kw} className="badge">#{kw}</span>
          ))}
        </div>
      )}

      <TaskList projectId={project.id} />
    </article>
  );
}

function priorityClass(p: 1 | 2 | 3): string {
  if (p === 1) return "pill pill-p1";
  if (p === 2) return "pill pill-p2";
  return "pill pill-p3";
}
