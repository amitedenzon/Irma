import { useState } from "react";
import { deleteProject, updateProject } from "../../lib/api";
import type { Project } from "../../lib/types";
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

  const remove = async () => {
    try {
      await deleteProject(project.id);
      onDeleted(project.id);
    } catch (e) {
      alert(`cannot delete: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-lg font-medium">{project.name}</h2>
          <div className="text-xs text-irma-mute">
            status {project.status} · priority {project.priority}
            {project.target_date ? ` · target ${project.target_date}` : ""}
          </div>
        </div>
        <div className="flex gap-2 text-xs">
          <button onClick={() => setEditing(true)} className="text-irma-mute hover:text-irma-text">edit</button>
          {project.status !== "archived" && (
            <button onClick={() => void archive()} className="text-irma-mute hover:text-irma-text">archive</button>
          )}
          <button onClick={() => void remove()} className="text-irma-amber">delete</button>
        </div>
      </div>

      {project.description && (
        <p className="text-sm mt-2 whitespace-pre-wrap">{project.description}</p>
      )}

      {project.goals.length > 0 && (
        <section className="mt-3">
          <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-1">Goals</h3>
          <ul className="text-sm list-disc list-inside">
            {project.goals.map((g, i) => <li key={i}>{g}</li>)}
          </ul>
        </section>
      )}

      <TaskList projectId={project.id} />

      {editing && (
        <ProjectForm
          initial={project}
          onClose={() => setEditing(false)}
          onSaved={onChanged}
        />
      )}
    </div>
  );
}
