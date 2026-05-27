import { useCallback, useEffect, useState } from "react";
import { listTasks } from "../../lib/api";
import type { Task } from "../../lib/types";
import { TaskAddRow } from "./TaskAddRow";
import { TaskRow } from "./TaskRow";

export function TaskList({ projectId }: { projectId: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [showDone, setShowDone] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setTasks(await listTasks({ project_id: projectId })); }
    finally { setLoading(false); }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  const open = tasks.filter((t) => t.status !== "done");
  const done = tasks.filter((t) => t.status === "done");

  return (
    <section className="border-t pt-3" style={{ borderColor: "var(--color-border)" }}>
      <div className="flex items-center justify-between mb-2 text-[12px]"
           style={{ color: "var(--color-ink-mute)" }}>
        <span>{open.length} open · {done.length} done</span>
        {done.length > 0 && (
          <button onClick={() => setShowDone((v) => !v)} className="btn-link">
            {showDone ? "hide done" : "show done"}
          </button>
        )}
      </div>

      <ul>
        {open.map((t) => (
          <TaskRow key={t.id} task={t}
                   onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
                   onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))} />
        ))}
        {open.length === 0 && !loading && (
          <li className="text-[13px] italic py-1" style={{ color: "var(--color-ink-faint)" }}>
            No open tasks
          </li>
        )}
      </ul>

      <TaskAddRow projectId={projectId}
                  onCreated={(t) => setTasks((cur) => [...cur, t])} />

      {showDone && done.length > 0 && (
        <ul className="mt-3 pt-2 border-t" style={{ borderColor: "var(--color-border)" }}>
          {done.map((t) => (
            <TaskRow key={t.id} task={t}
                     onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
                     onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))} />
          ))}
        </ul>
      )}
    </section>
  );
}
