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

  const isDone = task.status === "done";

  const toggle = async () => {
    const next = isDone
      ? await updateTask(task.id, { status: "todo" })
      : await completeTask(task.id);
    onChanged(next);
    setStatus(next.status);
  };

  const save = async () => {
    const updated = await updateTask(task.id, {
      notes,
      status,
      due_date: due || null,
      scheduled_for: sched || null,
      estimated_minutes: estimate ? Number(estimate) : null,
    });
    onChanged(updated);
  };

  const dueChip = task.due_date ? overdueLabel(task.due_date) : null;

  return (
    <li className="border-b last:border-b-0" style={{ borderColor: "var(--color-border)" }}>
      <div className="flex items-center gap-3 py-2 group">
        <input
          type="checkbox"
          checked={isDone}
          onChange={() => void toggle()}
          aria-label={`mark ${isDone ? "open" : "done"}`}
          style={{ accentColor: "var(--color-red)" }}
        />
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 text-left text-[13.5px] truncate"
          style={{
            color: isDone ? "var(--color-ink-faint)" : "var(--color-ink)",
            textDecoration: isDone ? "line-through" : "none",
          }}
        >
          {task.title}
        </button>

        {task.status === "blocked" && (
          <span className="badge" style={{ color: "var(--color-red)", borderColor: "var(--color-red)" }}>
            blocked
          </span>
        )}
        {task.status === "doing" && !isDone && (
          <span className="badge" style={{ color: "var(--color-amber)" }}>
            doing
          </span>
        )}
        {dueChip && !isDone && (
          <span className={`badge ${dueChip.urgent ? "badge-urgent" : ""}`}>{dueChip.label}</span>
        )}
        {task.scheduled_for && !isDone && (
          <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
            ↦ {task.scheduled_for.slice(5)}
          </span>
        )}
      </div>

      {open && (
        <div className="grid grid-cols-2 gap-3 pb-3 pl-7 pr-1 text-[12px]">
          <label className="col-span-2">
            <span className="block mb-1 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>notes</span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => void save()}
                      rows={2} className="input resize-y" />
          </label>
          <FieldS label="status">
            <select value={status}
                    onChange={(e) => { const s = e.target.value as TaskStatus; setStatus(s); void save(); }}
                    className="input">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </FieldS>
          <FieldS label="est. min">
            <input type="number" min={1} value={estimate}
                   onChange={(e) => setEstimate(e.target.value)} onBlur={() => void save()}
                   className="input" />
          </FieldS>
          <FieldS label="due">
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} onBlur={() => void save()}
                   className="input" />
          </FieldS>
          <FieldS label="scheduled">
            <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} onBlur={() => void save()}
                   className="input" />
          </FieldS>
          <button type="button"
                  onClick={async () => { await deleteTask(task.id); onDeleted(task.id); }}
                  className="col-span-2 text-left text-[12px] mt-1"
                  style={{ color: "var(--color-red)" }}>
            delete task
          </button>
        </div>
      )}
    </li>
  );
}

function FieldS({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="block mb-1 text-[11px]" style={{ color: "var(--color-ink-faint)" }}>{label}</span>
      {children}
    </label>
  );
}

function overdueLabel(due: string): { label: string; urgent: boolean } {
  const days = Math.ceil((new Date(due).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { label: `${-days}d overdue`, urgent: true };
  if (days === 0) return { label: "today", urgent: true };
  if (days === 1) return { label: "tomorrow", urgent: true };
  if (days <= 3) return { label: `${days}d`, urgent: true };
  if (days <= 14) return { label: `${days}d`, urgent: false };
  return { label: due.slice(5), urgent: false };
}
