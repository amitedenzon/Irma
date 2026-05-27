import { useState } from "react";
import { completeTask, deleteTask, updateTask } from "../../lib/api";
import type { Task, TaskStatus } from "../../lib/types";
import { IconChevronDown, IconChevronRight, IconTrash } from "../../lib/icons";

const STATUSES: TaskStatus[] = ["todo", "doing", "done", "blocked"];

const STATUS_GLYPH: Record<TaskStatus, string> = {
  todo: "[ ]",
  doing: "[~]",
  done: "[x]",
  blocked: "[!]",
};

const STATUS_COLOR: Record<TaskStatus, string> = {
  todo: "var(--color-ink-mute)",
  doing: "var(--color-amber-stain)",
  done: "var(--color-moss)",
  blocked: "var(--color-red-seal)",
};

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

  const dueChip = task.due_date
    ? overdueLabel(task.due_date)
    : null;

  return (
    <li
      className="border-l-2 transition-colors"
      style={{
        borderColor: isDone ? "transparent" : task.status === "blocked" ? "var(--color-red-seal)" : "var(--color-rule)",
      }}
    >
      <div className="flex items-center gap-2 py-1.5 px-2 group hover:bg-[var(--color-paper-deep)]">
        <button
          type="button"
          onClick={() => void toggle()}
          className="font-mono text-[14px] shrink-0"
          style={{ color: STATUS_COLOR[task.status], fontFamily: "var(--font-mono)" }}
          aria-label={`mark ${isDone ? "open" : "done"}`}
        >
          {STATUS_GLYPH[task.status]}
        </button>

        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex-1 text-left text-[13px] truncate flex items-center gap-1"
          style={{
            color: isDone ? "var(--color-ink-faint)" : "var(--color-ink)",
            textDecoration: isDone ? "line-through" : "none",
            fontFamily: "var(--font-mono)",
          }}
        >
          <span className="opacity-40 group-hover:opacity-100">
            {open ? <IconChevronDown size={11} /> : <IconChevronRight size={11} />}
          </span>
          <span className="truncate">{task.title}</span>
        </button>

        {dueChip && !isDone && (
          <span className="text-[10px] px-1.5 py-0.5 shrink-0"
                style={{
                  fontFamily: "var(--font-mono)",
                  background: dueChip.urgent ? "var(--color-red-seal)" : "var(--color-paper-fold)",
                  color: dueChip.urgent ? "var(--color-paper)" : "var(--color-ink-mute)",
                  border: dueChip.urgent ? "none" : "1px solid var(--color-ink-faint)",
                }}>
            {dueChip.label}
          </span>
        )}
        {task.scheduled_for && !isDone && (
          <span className="text-[10px] shrink-0" style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
            ◷ {task.scheduled_for.slice(5)}
          </span>
        )}
      </div>

      {open && (
        <div className="px-3 pl-8 pb-3 pt-1 grid grid-cols-2 gap-2 text-[11px]"
             style={{ background: "var(--color-paper-deep)" }}>
          <label className="col-span-2 block">
            <span className="text-[10px] uppercase tracking-widest block mb-1"
                  style={{ color: "var(--color-ink-faint)" }}>
              notes
            </span>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} onBlur={() => void save()}
                      rows={2} className="field w-full" />
          </label>
          <Field label="status">
            <select value={status}
                    onChange={(e) => { const s = e.target.value as TaskStatus; setStatus(s); void save(); }}
                    className="field w-full">
              {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </Field>
          <Field label="est. min">
            <input type="number" min={1} value={estimate}
                   onChange={(e) => setEstimate(e.target.value)} onBlur={() => void save()}
                   className="field w-full" />
          </Field>
          <Field label="due">
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} onBlur={() => void save()}
                   className="field w-full" />
          </Field>
          <Field label="scheduled">
            <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} onBlur={() => void save()}
                   className="field w-full" />
          </Field>
          <button type="button"
                  onClick={async () => { await deleteTask(task.id); onDeleted(task.id); }}
                  className="col-span-2 text-left text-[10px] uppercase tracking-wider mt-1 flex items-center gap-1.5"
                  style={{ color: "var(--color-red-seal)" }}>
            <IconTrash size={11} /> delete task
          </button>
        </div>
      )}
    </li>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[10px] uppercase tracking-widest block mb-1"
            style={{ color: "var(--color-ink-faint)" }}>
        {label}
      </span>
      {children}
    </label>
  );
}

function overdueLabel(due: string): { label: string; urgent: boolean } {
  const days = Math.ceil((new Date(due).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { label: `${-days}d overdue`, urgent: true };
  if (days === 0) return { label: "due today", urgent: true };
  if (days === 1) return { label: "due tomorrow", urgent: true };
  if (days <= 3) return { label: `${days}d`, urgent: true };
  if (days <= 14) return { label: `${days}d`, urgent: false };
  return { label: due.slice(5), urgent: false };
}
