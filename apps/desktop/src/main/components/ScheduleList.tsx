import type { ScheduleItem } from "../../lib/types";

interface ScheduleListProps {
  items: ScheduleItem[];
}

function formatTs(ts: string): string {
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function ScheduleList({ items }: ScheduleListProps) {
  return (
    <section className="border border-irma-border rounded-lg p-4 bg-irma-surface">
      <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-3">
        Next 7 days
      </h3>
      {items.length === 0 ? (
        <p className="text-sm text-irma-mute">Calendar is quiet.</p>
      ) : (
        <ul className="divide-y divide-irma-border">
          {items.map((it, i) => (
            <li key={i} className="py-2 flex items-baseline justify-between gap-4">
              <div>
                <div className="text-sm text-irma-text">{it.title}</div>
                {it.epic && (
                  <div className="text-xs text-irma-mute mt-0.5">{it.epic}</div>
                )}
              </div>
              <div className="text-xs text-irma-mute font-mono whitespace-nowrap">
                {formatTs(it.ts)}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
