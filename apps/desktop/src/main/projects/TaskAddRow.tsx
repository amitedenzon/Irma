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
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [busy, setBusy] = useState(false);
  const [showDates, setShowDates] = useState(false);

  const submit = async () => {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      onCreated(await createTask({
        project_id: projectId,
        title: t,
        due_date: due || null,
        scheduled_for: null,
      }));
      setTitle(""); setDue(""); setShowDates(false);
    } catch (e: unknown) {
      alert(`create failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <form onSubmit={(e) => { e.preventDefault(); void submit(); }}
            className="flex items-center gap-2 py-1">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Add task and press Enter…"
          className="input flex-1"
          style={{ background: "transparent", border: "1px dashed var(--color-border)" }}
          disabled={busy}
        />
        <button type="button" onClick={() => setShowDates((v) => !v)} className="btn-link"
                style={{ color: showDates ? "var(--color-red)" : "var(--color-ink-mute)" }}>
          {showDates ? "− due" : "+ due"}
        </button>
        <button type="submit" disabled={busy || !title.trim()} className="btn-red">
          add
        </button>
      </form>
      {showDates && (
        <div className="flex items-center gap-4 mt-1 ml-1 text-[12px]"
             style={{ color: "var(--color-ink-mute)" }}>
          <label className="flex items-center gap-1.5">
            due
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="input"
                   style={{ width: "auto" }} />
          </label>
        </div>
      )}
    </div>
  );
}
