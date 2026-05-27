import { useCallback, useEffect, useState } from "react";
import { listProjects } from "../../lib/api";
import type { Project } from "../../lib/types";
import { ProjectDetail } from "./ProjectDetail";
import { ProjectForm } from "./ProjectForm";
import { ProjectList } from "./ProjectList";

export function ProjectsView() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    const all = await listProjects(["active", "paused", "archived"]);
    setProjects(all);
    if (!selectedId && all.length > 0) setSelectedId(all[0].id);
  }, [selectedId]);

  useEffect(() => { void load(); }, [load]);

  const selected = projects.find((p) => p.id === selectedId) ?? null;

  return (
    <div className="flex gap-4 min-h-[24rem]">
      <ProjectList
        projects={projects}
        selectedId={selectedId}
        onSelect={setSelectedId}
        onNew={() => setCreating(true)}
      />
      <main className="flex-1 min-w-0">
        {selected ? (
          <ProjectDetail
            project={selected}
            onChanged={(p) => setProjects((cur) => cur.map((c) => (c.id === p.id ? p : c)))}
            onDeleted={(id) => {
              setProjects((cur) => cur.filter((c) => c.id !== id));
              setSelectedId(null);
            }}
          />
        ) : (
          <div className="text-sm text-irma-mute">Select a project on the left, or create one.</div>
        )}
      </main>

      {creating && (
        <ProjectForm
          initial={null}
          onClose={() => setCreating(false)}
          onSaved={(p) => { setProjects((cur) => [...cur, p]); setSelectedId(p.id); }}
        />
      )}
    </div>
  );
}
