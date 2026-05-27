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
  const archivedCount = projects.filter((p) => p.status === "archived").length;

  return (
    <div className="px-5 py-4 max-w-3xl mx-auto">
      <div className="flex items-center justify-end gap-3 mb-3">
        {archivedCount > 0 && (
          <button onClick={() => setShowArchived((v) => !v)} className="btn-link text-[11px]"
                  style={{ color: "var(--color-ink-faint)" }}>
            {showArchived ? "hide" : "show"} archived ({archivedCount})
          </button>
        )}
        <button onClick={() => setCreating(true)} className="btn-red">+ new project</button>
      </div>

      {error && (
        <div className="card p-3 mb-3 text-[12px]"
             style={{ borderColor: "var(--color-red)", color: "var(--color-red)" }}>
          Couldn't load projects: {error}
          <br />
          <span style={{ color: "var(--color-ink-mute)" }}>
            Backend at <code>http://127.0.0.1:8765</code> — check it's running.
          </span>
        </div>
      )}

      {creating && (
        <div className="mb-3">
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

      <div className="space-y-2">
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
    <div className="card p-6 text-center">
      <p className="text-[13px] mb-4" style={{ color: "var(--color-ink-mute)" }}>
        No projects yet.
      </p>
      <button onClick={onNew} className="btn-red">+ create your first project</button>
    </div>
  );
}
