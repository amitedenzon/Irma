import { useState } from "react";
import type { Project } from "../../lib/types";
import { ProjectCard } from "./ProjectCard";
import { ProjectForm } from "./ProjectForm";

export function ProjectsView({
  projects,
  error,
  onProjectsChanged,
  onReload,
}: {
  projects: Project[];
  error: string | null;
  onProjectsChanged: (next: Project[] | ((cur: Project[]) => Project[])) => void;
  onReload: () => void | Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const [showArchived, setShowArchived] = useState(false);

  const visible = projects.filter((p) => showArchived || p.status !== "archived");

  return (
    <div className="px-6 py-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
          {projects.filter((p) => p.status === "active").length} active
          {projects.length !== projects.filter((p) => p.status === "active").length &&
            ` · ${projects.length - projects.filter((p) => p.status === "active").length} other`}
        </p>
        <div className="flex items-center gap-3">
          {projects.some((p) => p.status === "archived") && (
            <button onClick={() => setShowArchived((v) => !v)} className="btn-link">
              {showArchived ? "hide archived" : "show archived"}
            </button>
          )}
          <button onClick={() => setCreating(true)} className="btn-red">
            + new project
          </button>
        </div>
      </div>

      {error && (
        <div className="card p-3 mb-4 text-[13px]"
             style={{ borderColor: "var(--color-red)", color: "var(--color-red)" }}>
          Couldn't load projects: {error}
          <br />
          <span style={{ color: "var(--color-ink-mute)" }} className="text-[12px]">
            Backend at <code>http://127.0.0.1:8765</code> — check it's running.
          </span>
        </div>
      )}

      {creating && (
        <div className="mb-5">
          <ProjectForm
            initial={null}
            onClose={() => setCreating(false)}
            onSaved={(p) => {
              onProjectsChanged((cur) => [...cur, p]);
              setCreating(false);
            }}
          />
        </div>
      )}

      {visible.length === 0 && !error && !creating && (
        <EmptyState onNew={() => setCreating(true)} />
      )}

      <div className="space-y-4">
        {visible.map((p) => (
          <ProjectCard
            key={p.id}
            project={p}
            onChanged={(updated) =>
              onProjectsChanged((cur) => cur.map((c) => (c.id === updated.id ? updated : c)))
            }
            onDeleted={(id) => {
              onProjectsChanged((cur) => cur.filter((c) => c.id !== id));
              void onReload();
            }}
          />
        ))}
      </div>
    </div>
  );
}

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div className="card p-8 text-center">
      <h2 className="display text-[16px] font-semibold mb-2" style={{ color: "var(--color-ink)" }}>
        No projects yet
      </h2>
      <p className="text-[13px] mb-5" style={{ color: "var(--color-ink-mute)" }}>
        Irma works in projects. Each one holds goals, calendar keywords, and the tasks you owe yourself.
      </p>
      <button onClick={onNew} className="btn-red">+ create your first project</button>
    </div>
  );
}
