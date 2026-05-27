import { useState } from "react";
import { createTask } from "../../lib/api";
import type { Task } from "../../lib/types";

export function TaskAddRow({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (t: Task) => void;
}) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [sched, setSched] = useState("");
  const [busy, setBusy] = useState(false);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="text-xs text-irma-indigo hover:underline"
      >
        + add task
      </button>
    );
  }

  const reset = () => {
    setTitle(""); setDue(""); setSched(""); setOpen(false);
  };

  const submit = async () => {
    if (!title.trim()) return;
    setBusy(true);
    try {
      const t = await createTask({
        project_id: projectId,
        title: title.trim(),
        due_date: due || null,
        scheduled_for: sched || null,
      });
      onCreated(t);
      reset();
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={(e) => { e.preventDefault(); void submit(); }}
      className="flex flex-wrap gap-2 items-center text-sm py-1.5"
    >
      <input
        autoFocus
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Task title"
        className="flex-1 min-w-[12rem] bg-irma-bg border border-irma-border rounded px-2 py-1"
      />
      <label className="text-xs text-irma-mute">due
        <input type="date" value={due} onChange={(e) => setDue(e.target.value)}
               className="ml-1 bg-irma-bg border border-irma-border rounded px-1" />
      </label>
      <label className="text-xs text-irma-mute">sched
        <input type="date" value={sched} onChange={(e) => setSched(e.target.value)}
               className="ml-1 bg-irma-bg border border-irma-border rounded px-1" />
      </label>
      <button type="submit" disabled={busy || !title.trim()}
              className="px-2 py-1 rounded border border-irma-indigo text-irma-indigo">
        save
      </button>
      <button type="button" onClick={reset}
              className="px-2 py-1 rounded text-irma-mute">
        cancel
      </button>
    </form>
  );
}
