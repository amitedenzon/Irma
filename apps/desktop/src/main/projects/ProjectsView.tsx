import { useState } from "react";
import type { Project } from "../../lib/types";
import { ProjectDetail } from "./ProjectDetail";
import { ProjectForm } from "./ProjectForm";
import { ProjectList } from "./ProjectList";

export function ProjectsView({
  projects,
  selectedId,
  onSelect,
  onProjectsChanged,
  onReload,
}: {
  projects: Project[];
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onProjectsChanged: (next: Project[] | ((cur: Project[]) => Project[])) => void;
  onReload: () => void | Promise<void>;
}) {
  const [creating, setCreating] = useState(false);
  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="flex h-full min-h-0">
      <ProjectList
        projects={projects}
        selectedId={selectedId}
        onSelect={onSelect}
        onNew={() => setCreating(true)}
      />
      <section className="flex-1 min-w-0 overflow-y-auto">
        {creating ? (
          <div className="p-6 max-w-2xl">
            <ProjectForm
              initial={null}
              onClose={() => setCreating(false)}
              onSaved={(p) => {
                onProjectsChanged((cur) => [...cur, p]);
                onSelect(p.id);
                setCreating(false);
              }}
            />
          </div>
        ) : selected ? (
          <ProjectDetail
            project={selected}
            onChanged={(p) => onProjectsChanged((cur) => cur.map((c) => (c.id === p.id ? p : c)))}
            onDeleted={(id) => {
              onProjectsChanged((cur) => cur.filter((c) => c.id !== id));
              onSelect(null);
              void onReload();
            }}
          />
        ) : (
          <EmptyState onNew={() => setCreating(true)} hasAny={projects.length > 0} />
        )}
      </section>
    </div>
  );
}

function EmptyState({ onNew, hasAny }: { onNew: () => void; hasAny: boolean }) {
  return (
    <div className="h-full flex items-center justify-center p-8">
      <div className="text-center max-w-md">
        <div style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
             className="text-[14px] uppercase tracking-widest mb-3">
          {hasAny ? "── pick a project ──" : "── no projects yet ──"}
        </div>
        <p style={{ fontFamily: "var(--font-serif)", color: "var(--color-ink-mute)" }}
           className="text-[14px] leading-snug mb-6">
          {hasAny
            ? "Click one in the ledger on the left."
            : "Irma works in projects. Each one holds its goals, its calendar keywords, and the tasks you owe yourself."}
        </p>
        {!hasAny && (
          <button type="button" onClick={onNew}
                  className="wax-seal px-4 py-1.5 text-[12px] uppercase tracking-wider"
                  style={{ fontFamily: "var(--font-mono)" }}>
            + new project
          </button>
        )}
      </div>
    </div>
  );
}
