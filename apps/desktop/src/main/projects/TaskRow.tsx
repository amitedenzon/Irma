import { useState } from "react";
import { completeTask, deleteTask, updateTask } from "../../lib/api";
import type { Task, TaskStatus } from "../../lib/types";

const STATUSES: TaskStatus[] = ["todo", "doing", "done", "blocked"];

export function TaskRow({
  task,
  onChanged,
  onDeleted,
}: {
  task: Task;
  onChanged: (t: Task) => void;
  onDeleted: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState(task.notes);
  const [status, setStatus] = useState<TaskStatus>(task.status);
  const [due, setDue] = useState(task.due_date ?? "");
  const [sched, setSched] = useState(task.scheduled_for ?? "");
  const [estimate, setEstimate] = useState(
    task.estimated_minutes !== null ? String(task.estimated_minutes) : "",
  );

  const save = async () => {
    const patch = {
      notes,
      status,
      due_date: due || null,
      scheduled_for: sched || null,
      estimated_minutes: estimate ? Number(estimate) : null,
    };
    const updated = await updateTask(task.id, patch);
    onChanged(updated);
  };

  return (
    <li className="border-b border-irma-border last:border-b-0 py-2">
      <div className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={task.status === "done"}
          onChange={async () => {
            const next =
              task.status === "done"
                ? await updateTask(task.id, { status: "todo" })
                : await completeTask(task.id);
            onChanged(next);
          }}
          className="accent-irma-indigo"
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={
            "flex-1 text-left " + (task.status === "done" ? "line-through text-irma-mute" : "")
          }
        >
          {task.title}
        </button>
        <span className="text-xs text-irma-mute">
          {task.due_date ? `due ${task.due_date}` : ""}
          {task.scheduled_for ? ` · sched ${task.scheduled_for}` : ""}
        </span>
      </div>

      {open && (
        <div className="mt-2 pl-6 grid grid-cols-2 gap-2 text-xs text-irma-mute">
          <label className="col-span-2">notes
            <textarea
              value={notes} onChange={(e) => setNotes(e.target.value)}
              onBlur={() => void save()}
              className="w-full mt-1 bg-irma-bg border border-irma-border rounded px-2 py-1 text-irma-text"
            />
          </label>
          <label>status
            <select value={status} onChange={(e) => { setStatus(e.target.value as TaskStatus); void save(); }}
                    className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
          <label>est min
            <input type="number" min={1} value={estimate}
                   onChange={(e) => setEstimate(e.target.value)} onBlur={() => void save()}
                   className="ml-1 w-16 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <label>due
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} onBlur={() => void save()}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <label>sched
            <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} onBlur={() => void save()}
                   className="ml-1 bg-irma-bg border border-irma-border rounded px-1 text-irma-text" />
          </label>
          <button type="button"
                  onClick={async () => { await deleteTask(task.id); onDeleted(task.id); }}
                  className="col-span-2 text-irma-amber hover:underline text-left">
            delete task
          </button>
        </div>
      )}
    </li>
  );
}
