import { useCallback, useEffect, useState } from "react";
import { listTasks } from "../../lib/api";
import type { Task } from "../../lib/types";
import { TaskAddRow } from "./TaskAddRow";
import { TaskRow } from "./TaskRow";

export function TaskList({ projectId }: { projectId: string }) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setTasks(await listTasks({ project_id: projectId }));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => { void load(); }, [load]);

  return (
    <section className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-xs uppercase tracking-widest text-irma-mute">Tasks</h3>
        <TaskAddRow projectId={projectId} onCreated={(t) => setTasks((ts) => [...ts, t])} />
      </div>
      {loading && tasks.length === 0 && (
        <div className="text-xs text-irma-mute">loading…</div>
      )}
      <ul>
        {tasks.map((t) => (
          <TaskRow
            key={t.id}
            task={t}
            onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
            onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))}
          />
        ))}
      </ul>
    </section>
  );
}
