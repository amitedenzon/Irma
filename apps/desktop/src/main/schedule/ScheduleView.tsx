import { useEffect, useState } from "react";
import { IRMA_API_BASE } from "../../lib/api";

interface Routine {
  id: string;
  name: string;
  cron: string;
  cron_human: string;
  enabled: boolean;
  prompt: string;
}

export function ScheduleView() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${IRMA_API_BASE}/api/v1/schedule/routines`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Routine[]>;
      })
      .then(setRoutines)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) {
    return (
      <p className="p-6 text-[13px]" style={{ color: "var(--color-red)" }}>
        Failed to load routines: {error}
      </p>
    );
  }

  return (
    <div className="p-5 flex flex-col gap-3">
      <p className="text-[11px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-ink-faint)" }}>
        Scheduled
      </p>

      {routines.length === 0 && (
        <p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
          No routines yet.
        </p>
      )}

      {routines.map((r) => (
        <div
          key={r.id}
          className="rounded-xl border"
          style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
        >
          {/* Header row */}
          <div className="flex items-center gap-3 px-4 py-3">
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: r.enabled ? "var(--color-moss)" : "var(--color-ink-faint)" }}
            />
            <div className="flex-1 min-w-0">
              <p className="text-[13px] font-medium truncate" style={{ color: "var(--color-ink)" }}>
                {r.name}
              </p>
              <p className="text-[11px]" style={{ color: "var(--color-ink-mute)", fontFamily: "var(--font-mono)" }}>
                {r.cron_human}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setExpanded(expanded === r.id ? null : r.id)}
              className="shrink-0 text-[11px] px-2.5 py-1 rounded-md transition-colors"
              style={{
                color: expanded === r.id ? "var(--color-ink)" : "var(--color-ink-mute)",
                background: expanded === r.id ? "var(--color-surface-2)" : "transparent",
              }}
            >
              {expanded === r.id ? "Hide prompt" : "View prompt"}
            </button>
          </div>

          {/* Expandable prompt */}
          {expanded === r.id && (
            <div
              className="px-4 pb-4 pt-0"
              style={{ borderTop: "1px solid var(--color-border)" }}
            >
              <pre
                className="mt-3 text-[11px] whitespace-pre-wrap break-words leading-relaxed"
                style={{
                  color: "var(--color-ink-mute)",
                  fontFamily: "var(--font-mono)",
                  background: "var(--color-bg)",
                  borderRadius: 8,
                  padding: "10px 12px",
                }}
              >
                {r.prompt}
              </pre>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
