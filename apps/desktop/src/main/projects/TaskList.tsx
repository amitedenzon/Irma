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
    <section>
      <div className="flex items-baseline justify-between mb-2">
        <h3 style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
            className="text-[11px] uppercase tracking-[0.18em]">
          ── tasks ── <span style={{ color: "var(--color-ink-faint)" }} className="ml-2">
            {open.length} open · {done.length} done
          </span>
        </h3>
        {done.length > 0 && (
          <button onClick={() => setShowDone((v) => !v)}
                  className="text-[10px] uppercase tracking-wider hover:underline"
                  style={{ color: "var(--color-ink-mute)" }}>
            {showDone ? "hide" : "show"} done
          </button>
        )}
      </div>

      <ul className="space-y-px">
        {open.map((t) => (
          <TaskRow key={t.id} task={t}
                   onChanged={(u) => setTasks((cur) => cur.map((c) => (c.id === u.id ? u : c)))}
                   onDeleted={(id) => setTasks((cur) => cur.filter((c) => c.id !== id))} />
        ))}
        {open.length === 0 && !loading && (
          <li className="text-[12px] italic py-2" style={{ color: "var(--color-ink-faint)" }}>
            ── no open tasks · add one below ──
          </li>
        )}
      </ul>

      <TaskAddRow projectId={projectId}
                  onCreated={(t) => setTasks((cur) => [...cur, t])} />

      {showDone && done.length > 0 && (
        <ul className="space-y-px mt-4 pt-2 border-t" style={{ borderColor: "var(--color-rule)" }}>
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
