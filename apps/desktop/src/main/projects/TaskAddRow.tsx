import { useState } from "react";
import { createTask } from "../../lib/api";
import type { Task } from "../../lib/types";
import { IconPlus } from "../../lib/icons";

/**
 * Always-visible inline task adder. Type → Enter creates a task on the
 * current project. Optional due/scheduled date pickers are tucked behind
 * a chevron so the common case (no deadline) stays one keystroke away.
 */
export function TaskAddRow({
  projectId,
  onCreated,
}: {
  projectId: string;
  onCreated: (t: Task) => void;
}) {
  const [title, setTitle] = useState("");
  const [due, setDue] = useState("");
  const [sched, setSched] = useState("");
  const [busy, setBusy] = useState(false);
  const [showDates, setShowDates] = useState(false);

  const submit = async () => {
    const t = title.trim();
    if (!t || busy) return;
    setBusy(true);
    try {
      const task = await createTask({
        project_id: projectId,
        title: t,
        due_date: due || null,
        scheduled_for: sched || null,
      });
      onCreated(task);
      setTitle("");
      setDue("");
      setSched("");
      setShowDates(false);
    } catch (e: unknown) {
      alert(`create failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2">
      <form
        onSubmit={(e) => { e.preventDefault(); void submit(); }}
        className="flex items-center gap-2 py-1.5 px-2 border-l-2"
        style={{ borderColor: "var(--color-red-seal)", background: "var(--color-paper-deep)" }}
      >
        <span style={{ color: "var(--color-red-seal)", fontFamily: "var(--font-mono)" }} className="text-[14px]">
          [+]
        </span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="add task… (Enter to save)"
          className="field flex-1 text-[13px]"
          style={{ background: "var(--color-paper)" }}
          disabled={busy}
        />
        <button
          type="button"
          onClick={() => setShowDates((v) => !v)}
          title="Add deadline / scheduled date"
          className="text-[10px] uppercase tracking-wider px-1.5 py-1"
          style={{
            color: showDates ? "var(--color-red-seal)" : "var(--color-ink-mute)",
            border: `1px solid ${showDates ? "var(--color-red-seal)" : "var(--color-rule)"}`,
            fontFamily: "var(--font-mono)",
          }}
        >
          dates
        </button>
        <button
          type="submit"
          disabled={busy || !title.trim()}
          className="wax-seal text-[10px] uppercase tracking-wider px-3 py-1 flex items-center gap-1"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          <IconPlus size={10} /> {busy ? "…" : "add"}
        </button>
      </form>
      {showDates && (
        <div className="flex items-center gap-3 py-1.5 px-2 pl-9 text-[11px]"
             style={{ background: "var(--color-paper-deep)", color: "var(--color-ink-faint)" }}>
          <label className="flex items-center gap-1">
            due
            <input type="date" value={due} onChange={(e) => setDue(e.target.value)} className="field" />
          </label>
          <label className="flex items-center gap-1">
            scheduled
            <input type="date" value={sched} onChange={(e) => setSched(e.target.value)} className="field" />
          </label>
        </div>
      )}
    </div>
  );
}
