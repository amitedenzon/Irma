import type { FocusItem } from "../../lib/types";

export function FocusList({
  items,
  onCompleteTask,
}: {
  items: FocusItem[];
  onCompleteTask: (taskId: string) => void | Promise<void>;
}) {
  if (items.length === 0) return null;
  return (
    <section>
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">Focus</h3>
      <ul className="space-y-1.5">
        {items.map((it, i) => (
          <li key={`${it.kind}-${it.task_id ?? i}`} className="flex items-start gap-3">
            {it.kind === "task" && it.task_id ? (
              <input
                type="checkbox"
                onChange={() => void onCompleteTask(it.task_id!)}
                className="mt-1 accent-irma-indigo"
                aria-label={`Complete ${it.title}`}
              />
            ) : (
              <span className="mt-1">📅</span>
            )}
            <div className="flex-1 min-w-0">
              <div className="text-sm">{it.title}</div>
              <div className="text-xs text-irma-mute">
                {it.project_name ?? "—"}
                {it.due_date ? ` · due ${it.due_date}` : ""}
                {it.scheduled_for ? ` · sched ${it.scheduled_for}` : ""}
                {it.when ? ` · ${it.when}` : ""}
                {it.note ? ` · ${it.note}` : ""}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
