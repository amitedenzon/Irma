import { useState } from "react";
import { deleteProject, updateProject } from "../../lib/api";
import type { Project } from "../../lib/types";
import { IconArchive, IconPencil, IconTrash } from "../../lib/icons";
import { ProjectForm } from "./ProjectForm";
import { TaskList } from "./TaskList";

export function ProjectDetail({
  project,
  onChanged,
  onDeleted,
}: {
  project: Project;
  onChanged: (p: Project) => void;
  onDeleted: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);

  const archive = async () => {
    const p = await updateProject(project.id, { status: "archived" });
    onChanged(p);
  };
  const unarchive = async () => {
    const p = await updateProject(project.id, { status: "active" });
    onChanged(p);
  };
  const remove = async () => {
    if (!confirm(`Delete "${project.name}"? Existing non-done tasks block this.`)) return;
    try {
      await deleteProject(project.id);
      onDeleted(project.id);
    } catch (e) {
      alert(`cannot delete: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const daysToTarget = project.target_date
    ? Math.ceil((new Date(project.target_date).getTime() - Date.now()) / 86_400_000)
    : null;

  if (editing) {
    return (
      <div className="p-6 max-w-2xl">
        <ProjectForm initial={project} onClose={() => setEditing(false)} onSaved={(p) => { onChanged(p); setEditing(false); }} />
      </div>
    );
  }

  return (
    <div className="p-6 max-w-3xl mx-auto">
      {/* Header card */}
      <div className="paper-inset ink-frame-thin p-4 mb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0 flex-1">
            <div style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
                 className="text-[11px] uppercase tracking-[0.18em] mb-1">
              ▶ project
            </div>
            <h1 style={{ fontFamily: "var(--font-display)" }} className="text-[22px] leading-tight">
              {project.name}
            </h1>
            <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2 text-[11px]"
                 style={{ fontFamily: "var(--font-mono)", color: "var(--color-ink-mute)" }}>
              <Stat label="status" value={project.status} />
              <Stat label="priority" value={`P${project.priority}`} accent={project.priority === 1} />
              {project.target_date && (
                <Stat
                  label="target"
                  value={`${project.target_date}${daysToTarget !== null ? ` · ${daysToTarget >= 0 ? `${daysToTarget}d left` : `${-daysToTarget}d overdue`}` : ""}`}
                  accent={daysToTarget !== null && daysToTarget < 7}
                />
              )}
            </div>
          </div>
          <div className="flex items-center gap-1">
            <ActionBtn onClick={() => setEditing(true)} title="Edit"><IconPencil size={13} /></ActionBtn>
            {project.status !== "archived" ? (
              <ActionBtn onClick={() => void archive()} title="Archive"><IconArchive size={13} /></ActionBtn>
            ) : (
              <ActionBtn onClick={() => void unarchive()} title="Restore">
                <span style={{ fontFamily: "var(--font-mono)" }} className="text-[10px]">restore</span>
              </ActionBtn>
            )}
            <ActionBtn onClick={() => void remove()} title="Delete" danger><IconTrash size={13} /></ActionBtn>
          </div>
        </div>

        {project.description && (
          <p style={{ fontFamily: "var(--font-serif)", color: "var(--color-ink)" }}
             className="mt-3 text-[14px] leading-snug whitespace-pre-wrap">
            {project.description}
          </p>
        )}

        {project.goals.length > 0 && (
          <div className="mt-4">
            <div className="text-[10px] uppercase tracking-widest mb-1.5 flex items-center gap-2"
                 style={{ color: "var(--color-ink-faint)" }}>
              <span>· goals</span>
              <span className="rule-dash flex-1" />
            </div>
            <ul className="space-y-1">
              {project.goals.map((g, i) => (
                <li key={i} className="flex items-start gap-2 text-[13px] leading-snug">
                  <span style={{ color: "var(--color-red-seal)" }}>※</span>
                  <span style={{ fontFamily: "var(--font-serif)" }}>{g}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {project.calendar_keywords.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {project.calendar_keywords.map((kw) => (
              <span key={kw}
                    className="text-[10px] px-1.5 py-0.5"
                    style={{
                      fontFamily: "var(--font-mono)",
                      background: "var(--color-paper-fold)",
                      color: "var(--color-ink-mute)",
                      border: "1px solid var(--color-ink-faint)",
                    }}>
                #{kw}
              </span>
            ))}
          </div>
        )}
      </div>

      <TaskList projectId={project.id} />
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <span className="flex items-baseline gap-1">
      <span style={{ color: "var(--color-ink-faint)" }}>{label}:</span>
      <span style={{ color: accent ? "var(--color-red-seal)" : "var(--color-ink)" }}>{value}</span>
    </span>
  );
}

function ActionBtn({
  children, onClick, title, danger,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className="px-1.5 py-1 transition-colors"
      style={{
        color: danger ? "var(--color-red-seal)" : "var(--color-ink-mute)",
        border: "1px solid transparent",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.borderColor = danger ? "var(--color-red-seal)" : "var(--color-rule)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.borderColor = "transparent"; }}
    >
      {children}
    </button>
  );
}
