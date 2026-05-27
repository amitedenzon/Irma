import type { Brief } from "../../lib/types";

export function BriefView({
  brief,
  busy,
  error,
  onRefetch,
}: {
  brief: Brief | null;
  busy: boolean;
  error: string | null;
  onRefetch: () => void | Promise<void>;
}) {
  return (
    <div className="px-6 py-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
          {brief ? `Synthesized ${formatTs(brief.generated_at)}` : "Today's brief"}
        </p>
        <button onClick={() => void onRefetch()} disabled={busy} className="btn-ghost">
          {busy ? "synthesizing…" : "re-synth"}
        </button>
      </div>

      {busy && !brief && (
        <p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
          Irma is reading the room…
        </p>
      )}

      {error && (
        <div className="card p-3 text-[13px]"
             style={{ borderColor: "var(--color-red)", color: "var(--color-red)" }}>
          {error}
        </div>
      )}

      {brief && (
        <div className="space-y-5">
          {brief.recommendation && (
            <div className="card p-4">
              <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--color-ink-mute)" }}>
                Recommendation
              </h3>
              <p className="text-[14px] leading-relaxed">{brief.recommendation}</p>
            </div>
          )}

          {brief.conflicts.length > 0 && (
            <div className="card p-4" style={{ borderColor: "var(--color-red)" }}>
              <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--color-red)" }}>
                Conflicts
              </h3>
              <ul className="space-y-1">
                {brief.conflicts.map((c, i) => (
                  <li key={i} className="text-[13.5px] flex gap-2">
                    <span style={{ color: "var(--color-red)" }}>·</span>
                    <span>{c}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.focus.length > 0 && (
            <div className="card p-4">
              <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--color-ink-mute)" }}>
                Focus
              </h3>
              <ul className="space-y-1.5">
                {brief.focus.map((f, i) => (
                  <li key={i} className="text-[13px] flex items-baseline gap-2">
                    <span style={{ color: "var(--color-ink-faint)" }}>
                      {f.kind === "task" ? "·" : "📅"}
                    </span>
                    <span className="flex-1">{f.title}</span>
                    <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                      {f.project_name ?? ""}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.project_status.length > 0 && (
            <div className="card p-4">
              <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--color-ink-mute)" }}>
                Project status
              </h3>
              <ul className="space-y-2">
                {brief.project_status.map((p) => (
                  <li key={p.project_id} className="text-[13px]">
                    <div className="flex items-baseline justify-between">
                      <span className="font-medium">{p.project_name}</span>
                      <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                        {p.open_tasks} open · {p.done_tasks} done
                        {p.days_to_target !== null ? ` · ${p.days_to_target}d to target` : ""}
                      </span>
                    </div>
                    {p.note && <div className="text-[12px] mt-0.5" style={{ color: "var(--color-ink-mute)" }}>{p.note}</div>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {brief.narrative && (
            <div className="card p-4">
              <h3 className="display text-[11px] font-semibold uppercase tracking-wider mb-2"
                  style={{ color: "var(--color-ink-mute)" }}>
                Narrative
              </h3>
              <p className="text-[13.5px] leading-relaxed italic whitespace-pre-wrap"
                 style={{ color: "var(--color-ink-mute)" }}>
                {brief.narrative}
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      hour: "2-digit", minute: "2-digit", month: "short", day: "numeric",
    });
  } catch {
    return iso;
  }
}
