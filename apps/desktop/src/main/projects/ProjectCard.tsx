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
  const [showActions, setShowActions] = useState(false);

  const archive = async () => onChanged(await updateProject(project.id, { status: "archived" }));
  const unarchive = async () => onChanged(await updateProject(project.id, { status: "active" }));
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
    <article className="card px-4 py-3"
             onMouseEnter={() => setShowActions(true)}
             onMouseLeave={() => setShowActions(false)}>
      <header className="mb-2">
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            <span className="text-[13px] leading-none">{"🌶️".repeat(4 - project.priority)}</span>
            {project.status !== "active" && (
              <span className="badge">{project.status}</span>
            )}
            {project.target_date && (
              <span className="text-[11px]"
                    style={{
                      color: daysToTarget !== null && daysToTarget < 7
                        ? "var(--color-red)"
                        : "var(--color-ink-faint)",
                      fontFamily: "var(--font-mono)",
                    }}>
                {daysToTarget !== null
                  ? (daysToTarget >= 0 ? `${daysToTarget}d` : `${-daysToTarget}d over`)
                  : project.target_date}
              </span>
            )}
          </div>
          <div
            className="flex items-center gap-3 text-[11px] shrink-0 transition-opacity"
            style={{ color: "var(--color-ink-faint)", opacity: showActions ? 1 : 0 }}
          >
            <button onClick={() => setEditing(true)} className="hover:underline">edit</button>
            {project.status !== "archived" ? (
              <button onClick={() => void archive()} className="hover:underline">archive</button>
            ) : (
              <button onClick={() => void unarchive()} className="hover:underline">restore</button>
            )}
            <button onClick={() => void remove()} className="hover:underline" style={{ color: "var(--color-red)" }}>delete</button>
          </div>
        </div>
        <h2 className="display text-[14px] font-semibold truncate"
            style={{ color: "var(--color-ink)" }}>
          {project.name}
        </h2>
      </header>

      <TaskList projectId={project.id} />
    </article>
  );
}
