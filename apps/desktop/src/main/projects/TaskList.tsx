import { useCallback, useEffect, useState } from "react";
import { listTasks } from "../../lib/api";
import type { Task } from "../../lib/types";
import { TaskAddRow } from "./TaskAddRow";
import { TaskRow } from "./TaskRow";

const COLLAPSED_COUNT = 5;

export function TaskList({ projectId }: { projectId: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDone, setShowDone] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTasks(await listTasks({ project_id: projectId })); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const open = tasks.filter((t) => t.status !== "done");
  const done = tasks.filter((t) => t.status === "done");
  const visibleOpen = expanded ? open : open.slice(0, COLLAPSED_COUNT);
  const hiddenCount = open.length - COLLAPSED_COUNT;

  return (
    <section>
      <ul>
        {visibleOpen.map((t) => (
          <TaskRow key={t.id} task={t}
                   onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
                   onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))} />
        ))}
      </ul>
      {hiddenCount > 0 && !expanded && (
        <button onClick={() => setExpanded(true)} className="btn-link text-[11px] mt-1"
                style={{ color: "var(--color-ink-faint)" }}>
          + {hiddenCount} more
        </button>
      )}
      {expanded && hiddenCount > 0 && (
        <button onClick={() => setExpanded(false)} className="btn-link text-[11px] mt-1"
                style={{ color: "var(--color-ink-faint)" }}>
          − collapse
        </button>
      )}

      <TaskAddRow projectId={projectId}
                  onCreated={(t) => setTasks((cur) => [...cur, t])} />

      {done.length > 0 && (
        <div className="mt-1.5">
          <button onClick={() => setShowDone((v) => !v)} className="btn-link text-[11px]"
                  style={{ color: "var(--color-ink-faint)" }}>
            {showDone ? "− hide" : "+ show"} {done.length} done
          </button>
          {showDone && (
            <ul className="mt-1">
              {done.map((t) => (
                <TaskRow key={t.id} task={t}
                         onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
                         onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))} />
              ))}
            </ul>
          )}
        </div>
      )}
      {open.length === 0 && done.length === 0 && !loading && null}
    </section>
  );
}
