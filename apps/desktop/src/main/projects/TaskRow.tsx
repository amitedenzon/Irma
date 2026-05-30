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
  const [due, setDue] = useState(task.due_date ?? "");

  const isDone = task.status === "done";

  const toggle = async () => {
    const next = isDone
      ? await updateTask(task.id, { status: "todo" })
      : await completeTask(task.id);
    onChanged(next);
  };

  const saveStatus = async (newStatus: TaskStatus) => {
    onChanged(await updateTask(task.id, { status: newStatus }));
  };

  const saveDue = async () => {
    onChanged(await updateTask(task.id, { due_date: due || null }));
  };

  const dueChip = task.due_date ? overdueLabel(task.due_date) : null;

  return (
    <li className="border-b last:border-b-0" style={{ borderColor: "var(--color-border)" }}>
      <div className="flex items-center gap-2.5 py-1.5">
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
          <span title="blocked" style={{ color: "var(--color-red)", fontSize: 14, lineHeight: 1 }}>⊘</span>
        )}
        {task.status === "doing" && (
          <span title="doing" style={{ color: "var(--color-amber)", fontSize: 11, lineHeight: 1 }}>▶</span>
        )}
        {dueChip && !isDone && (
          <span className={`badge ${dueChip.urgent ? "badge-urgent" : ""}`}>{dueChip.label}</span>
        )}
      </div>

      {open && (
        <div className="flex gap-2 pb-2.5 pl-7 pr-1 text-[12px]">
          <FieldS label="status">
            <select
              value={task.status}
              onChange={(e) => void saveStatus(e.target.value as TaskStatus)}
              className="input"
            >
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </FieldS>
          <FieldS label="due">
            <input type="date" value={due}
                   onChange={(e) => setDue(e.target.value)}
                   onBlur={() => void saveDue()}
                   className="input" />
          </FieldS>
          <div className="flex items-end pb-0.5">
            <button type="button"
                    onClick={async () => { await deleteTask(task.id); onDeleted(task.id); }}
                    className="text-[12px]"
                    style={{ color: "var(--color-red)" }}>
              delete
            </button>
          </div>
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
