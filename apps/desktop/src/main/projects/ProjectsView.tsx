import { useState, useEffect } from "react";
import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  rectSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { Project } from "../../lib/types";
import { ProjectCard } from "./ProjectCard";
import { ProjectForm } from "./ProjectForm";

const ORDER_KEY = "irma_project_order";

function saveOrder(projects: Project[]) {
  localStorage.setItem(ORDER_KEY, JSON.stringify(projects.map((p) => p.id)));
}

function applyOrder(projects: Project[], ids: string[]): Project[] {
  const map = new Map(projects.map((p) => [p.id, p]));
  const ordered = ids.flatMap((id) => (map.has(id) ? [map.get(id)!] : []));
  const rest = projects.filter((p) => !ids.includes(p.id));
  return [...ordered, ...rest];
}

function SortableCard({
  project,
  onChanged,
  onDeleted,
}: {
  project: Project;
  onChanged: (p: Project) => void;
  onDeleted: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: project.id });

  return (
    <div
      ref={setNodeRef}
      style={{
        transform: CSS.Transform.toString(transform),
        transition,
        opacity: isDragging ? 0.4 : 1,
        cursor: isDragging ? "grabbing" : "grab",
        zIndex: isDragging ? 10 : undefined,
      }}
      {...attributes}
      {...listeners}
    >
      <ProjectCard project={project} onChanged={onChanged} onDeleted={onDeleted} />
    </div>
  );
}

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
  const [remindersLinked, setRemindersLinked] = useState<boolean | null>(null);

  useEffect(() => {
    fetch("http://127.0.0.1:8765/api/v1/integrations/google/status")
      .then((r) => r.json())
      .then((d: { reminders_linked: boolean }) => setRemindersLinked(d.reminders_linked))
      .catch(() => {});
  }, []);
  const [orderedIds, setOrderedIds] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem(ORDER_KEY) ?? "[]"); } catch { return []; }
  });

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  const filtered = projects.filter((p) => showArchived || p.status !== "archived");
  const visible = applyOrder(filtered, orderedIds);
  const archivedCount = projects.filter((p) => p.status === "archived").length;

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIdx = visible.findIndex((p) => p.id === active.id);
    const newIdx = visible.findIndex((p) => p.id === over.id);
    const next = arrayMove(visible, oldIdx, newIdx);
    const newIds = next.map((p) => p.id);
    setOrderedIds(newIds);
    saveOrder(next);
  }

  return (
    <div className="px-5 py-4 max-w-5xl mx-auto">
      <div className="flex items-center justify-between gap-3 mb-3">
        {remindersLinked !== null && (
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full" style={{
              background: remindersLinked ? "#22c55e" : "var(--color-red)",
              opacity: remindersLinked ? 1 : 0.7,
            }} />
            <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
              {remindersLinked ? "Reminders synced" : "Reminders unlinked"}
            </span>
          </div>
        )}
        <div className="flex items-center gap-3 ml-auto">
        {archivedCount > 0 && (
          <button onClick={() => setShowArchived((v) => !v)} className="btn-link text-[11px]"
                  style={{ color: "var(--color-ink-faint)" }}>
            {showArchived ? "hide" : "show"} archived ({archivedCount})
          </button>
        )}
        <button onClick={() => setCreating(true)} className="btn-red">+ new project</button>
        </div>
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

      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
        <SortableContext items={visible.map((p) => p.id)} strategy={rectSortingStrategy}>
          <div className="flex gap-3 items-start">
            {[visible.filter((_, i) => i % 2 === 0), visible.filter((_, i) => i % 2 !== 0)].map(
              (col, ci) => (
                <div key={ci} className="flex-1 flex flex-col gap-3">
                  {col.map((p) => (
                    <SortableCard
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
              ),
            )}
          </div>
        </SortableContext>
      </DndContext>
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
