import { useEffect, useState } from "react";
import { IRMA_API_BASE } from "../../lib/api";

const DAILY_BRIEF_ID = "trig_0128d6voBA1V4YoHYqhtK1fE";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface Routine {
  id: string;
  name: string;
  cron: string;
  cron_human: string;
  enabled: boolean;
  prompt: string;
}

// ---------------------------------------------------------------------------
// Schedule builder helpers
// ---------------------------------------------------------------------------
const WEEKDAYS = [
  { n: 1, label: "Mon" },
  { n: 2, label: "Tue" },
  { n: 3, label: "Wed" },
  { n: 4, label: "Thu" },
  { n: 5, label: "Fri" },
  { n: 6, label: "Sat" },
  { n: 0, label: "Sun" },
];

const ordinal = (n: number) => {
  const s = ["th", "st", "nd", "rd"];
  const v = n % 100;
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0]);
};

type Freq = "daily" | "weekly" | "monthly";
interface Schedule { freq: Freq; weekdays: number[]; monthDay: number }

function buildCron({ freq, weekdays, monthDay }: Schedule): string {
  if (freq === "daily") return "30 4 * * *";
  if (freq === "weekly") {
    const days = weekdays.length ? weekdays.slice().sort((a, b) => a - b).join(",") : "1";
    return `30 4 * * ${days}`;
  }
  return `30 4 ${monthDay} * *`;
}

function buildHuman({ freq, weekdays, monthDay }: Schedule): string {
  if (freq === "daily") return "Every day";
  if (freq === "weekly") {
    if (!weekdays.length) return "Every week";
    const order = [1, 2, 3, 4, 5, 6, 0];
    const names = weekdays
      .slice()
      .sort((a, b) => order.indexOf(a) - order.indexOf(b))
      .map((n) => WEEKDAYS.find((d) => d.n === n)!.label);
    return names.length === 1
      ? `Every ${names[0]}`
      : `Every ${names.slice(0, -1).join(", ")} and ${names.at(-1)}`;
  }
  return `Monthly on the ${ordinal(monthDay)}`;
}

// ---------------------------------------------------------------------------
// Routine form
// ---------------------------------------------------------------------------
function RoutineForm({
  initial,
  prefix,
  onSaved,
  onCancel,
}: {
  initial?: Routine;
  prefix: string;
  onSaved: (r: Routine) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial?.name ?? "");
  const [prompt, setPrompt] = useState(initial?.prompt ?? "");
  const [freq, setFreq] = useState<Freq>("daily");
  const [weekdays, setWeekdays] = useState<number[]>([1]);
  const [monthDay, setMonthDay] = useState(1);
  const [showPrefix, setShowPrefix] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const schedule: Schedule = { freq, weekdays, monthDay };

  const toggleDay = (n: number) =>
    setWeekdays((prev) =>
      prev.includes(n) ? prev.filter((d) => d !== n) : [...prev, n],
    );

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(
        initial
          ? `${IRMA_API_BASE}/api/v1/schedule/routines/${initial.id}`
          : `${IRMA_API_BASE}/api/v1/schedule/routines`,
        {
          method: initial ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name.trim(),
            cron: buildCron(schedule),
            cron_human: buildHuman(schedule),
            prompt: prompt.trim(),
            enabled: true,
          }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      onSaved((await res.json()) as Routine);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      onSubmit={submit}
      className="rounded-xl border p-4 space-y-4"
      style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      <div className="flex items-baseline justify-between">
        <h2 className="display text-[14px] font-semibold" style={{ color: "var(--color-ink)" }}>
          {initial ? "Edit routine" : "New routine"}
        </h2>
        <button type="button" onClick={onCancel} className="text-[12px]"
                style={{ color: "var(--color-ink-mute)" }}>cancel</button>
      </div>

      {/* Name */}
      <label className="block">
        <span className="text-[12px] font-medium block mb-1" style={{ color: "var(--color-ink)" }}>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)}
               placeholder="Monthly paycheck reminder" autoFocus className="input w-full" />
      </label>

      {/* Schedule */}
      <div>
        <span className="text-[12px] font-medium block mb-2" style={{ color: "var(--color-ink)" }}>Schedule</span>
        <div className="flex gap-2 mb-3">
          {(["daily", "weekly", "monthly"] as Freq[]).map((f) => (
            <button key={f} type="button" onClick={() => setFreq(f)}
                    className="px-3 py-1 rounded-md text-[12px] font-medium transition-colors capitalize"
                    style={{
                      background: freq === f ? "var(--color-red)" : "var(--color-surface-2)",
                      color: freq === f ? "#fff" : "var(--color-ink-mute)",
                    }}>
              {f}
            </button>
          ))}
        </div>

        {freq === "weekly" && (
          <div className="flex gap-1.5 flex-wrap">
            {WEEKDAYS.map(({ n, label }) => (
              <button key={n} type="button" onClick={() => toggleDay(n)}
                      className="px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors"
                      style={{
                        background: weekdays.includes(n) ? "var(--color-red)" : "var(--color-surface-2)",
                        color: weekdays.includes(n) ? "#fff" : "var(--color-ink-mute)",
                      }}>
                {label}
              </button>
            ))}
          </div>
        )}

        {freq === "monthly" && (
          <div className="flex items-center gap-2">
            <span className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>Day</span>
            <input type="number" min={1} max={28} value={monthDay}
                   onChange={(e) => setMonthDay(Math.min(28, Math.max(1, Number(e.target.value))))}
                   className="input w-20" />
            <span className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>of each month</span>
          </div>
        )}

        <p className="mt-2 text-[11px]" style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
          {buildHuman(schedule)} · draft created 30 min before send
        </p>
      </div>

      {/* Prompt */}
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-[12px] font-medium" style={{ color: "var(--color-ink)" }}>Prompt</span>
          <button type="button" onClick={() => setShowPrefix((v) => !v)}
                  className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
            {showPrefix ? "hide system context" : "show system context"}
          </button>
        </div>

        {showPrefix && (
          <pre
            className="mb-2 text-[10px] whitespace-pre-wrap break-words leading-relaxed rounded-lg px-3 py-2"
            style={{
              color: "var(--color-ink-faint)",
              fontFamily: "var(--font-mono)",
              background: "var(--color-bg)",
              border: "1px dashed var(--color-border)",
            }}
          >
            {prefix}
          </pre>
        )}

        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          placeholder="Describe what Irma should write and email to you…"
          className="input w-full resize-y text-[11px] leading-relaxed"
          style={{ fontFamily: "var(--font-mono)" }}
        />
      </div>

      {error && <p className="text-[12px]" style={{ color: "var(--color-red)" }}>{error}</p>}

      <div className="flex justify-end gap-2">
        <button type="button" onClick={onCancel} className="btn-ghost">cancel</button>
        <button type="submit" disabled={busy || !name.trim() || !prompt.trim()} className="btn-red">
          {busy ? "saving…" : initial ? "save" : "create"}
        </button>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------------------
// Main view
// ---------------------------------------------------------------------------
export function ScheduleView() {
  const [routines, setRoutines] = useState<Routine[]>([]);
  const [prefix, setPrefix] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [editing, setEditing] = useState<Routine | null>(null);
  const [adding, setAdding] = useState(false);
  const [runState, setRunState] = useState<Record<string, "idle" | "running" | "sent" | "error">>({});

  useEffect(() => {
    Promise.all([
      fetch(`${IRMA_API_BASE}/api/v1/schedule/routines`).then((r) => r.json() as Promise<Routine[]>),
      fetch(`${IRMA_API_BASE}/api/v1/schedule/prefix`).then((r) => r.json() as Promise<{ prefix: string }>),
    ])
      .then(([routines, { prefix }]) => { setRoutines(routines); setPrefix(prefix); })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const runNow = async (id: string) => {
    setRunState((s) => ({ ...s, [id]: "running" }));
    try {
      const res = await fetch(`${IRMA_API_BASE}/api/v1/schedule/routines/${id}/run`, { method: "POST" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setRunState((s) => ({ ...s, [id]: "sent" }));
    } catch {
      setRunState((s) => ({ ...s, [id]: "error" }));
    } finally {
      setTimeout(() => setRunState((s) => ({ ...s, [id]: "idle" })), 4000);
    }
  };

  const onSaved = (r: Routine) => {
    setRoutines((prev) => {
      const idx = prev.findIndex((x) => x.id === r.id);
      return idx >= 0 ? prev.map((x) => (x.id === r.id ? r : x)) : [...prev, r];
    });
    setEditing(null);
    setAdding(false);
  };

  if (error) {
    return <p className="p-6 text-[13px]" style={{ color: "var(--color-red)" }}>Failed to load: {error}</p>;
  }

  return (
    <div className="p-5 flex flex-col gap-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-[11px] uppercase tracking-widest font-semibold"
           style={{ color: "var(--color-ink-faint)" }}>Scheduled</p>
        {!adding && !editing && (
          <button type="button" onClick={() => setAdding(true)}
                  className="text-[12px] px-2.5 py-1 rounded-md"
                  style={{ color: "var(--color-red)" }}>
            + Add
          </button>
        )}
      </div>

      <p className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
        * All scheduled mails are sent at 08:00 (Israel time)
      </p>

      {adding && (
        <RoutineForm prefix={prefix} onSaved={onSaved} onCancel={() => setAdding(false)} />
      )}

      {routines.length === 0 && !adding && (
        <p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>No routines yet.</p>
      )}

      {routines.map((r) =>
        editing?.id === r.id ? (
          <RoutineForm key={r.id} initial={r} prefix={prefix}
                       onSaved={onSaved} onCancel={() => setEditing(null)} />
        ) : (
          <div key={r.id} className="rounded-xl border"
               style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}>
            <div className="flex items-center gap-3 px-4 py-3">
              <span className="w-2 h-2 rounded-full shrink-0"
                    style={{ background: r.enabled ? "var(--color-moss)" : "var(--color-ink-faint)" }} />
              <div className="flex-1 min-w-0">
                <p className="text-[13px] font-medium truncate" style={{ color: "var(--color-ink)" }}>{r.name}</p>
                <p className="text-[11px]" style={{ color: "var(--color-ink-mute)", fontFamily: "var(--font-mono)" }}>
                  {r.cron_human}
                </p>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {r.id === DAILY_BRIEF_ID ? (
                  <span
                    title="Managed internally — prompt is not user-editable"
                    className="text-[13px] px-1"
                    style={{ color: "var(--color-ink-faint)" }}
                  >
                    🔒
                  </span>
                ) : (
                  <>
                    <button type="button"
                            onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                            className="text-[11px] px-2.5 py-1 rounded-md transition-colors"
                            style={{
                              color: expanded === r.id ? "var(--color-ink)" : "var(--color-ink-mute)",
                              background: expanded === r.id ? "var(--color-surface-2)" : "transparent",
                            }}>
                      {expanded === r.id ? "Hide" : "Prompt"}
                    </button>
                    <button type="button"
                            onClick={() => { setEditing(r); setExpanded(null); setAdding(false); }}
                            className="text-[11px] px-2.5 py-1 rounded-md"
                            style={{ color: "var(--color-ink-mute)" }}>
                      Edit
                    </button>
                  </>
                )}
                <button
                  type="button"
                  disabled={runState[r.id] === "running"}
                  onClick={() => void runNow(r.id)}
                  className="text-[11px] px-2.5 py-1 rounded-md font-semibold text-white transition-opacity disabled:opacity-50"
                  style={{
                    background:
                      runState[r.id] === "sent" ? "var(--color-moss)"
                      : runState[r.id] === "error" ? "color-mix(in srgb, var(--color-red) 70%, black)"
                      : "var(--color-red)",
                  }}
                >
                  {runState[r.id] === "running" ? "Sending…"
                    : runState[r.id] === "sent" ? "Sent ✓"
                    : runState[r.id] === "error" ? "Failed"
                    : "Run now"}
                </button>
              </div>
            </div>

            {expanded === r.id && r.id !== DAILY_BRIEF_ID && (
              <div style={{ borderTop: "1px solid var(--color-border)" }} className="px-4 pb-4 pt-3">
                <pre className="text-[11px] whitespace-pre-wrap break-words leading-relaxed"
                     style={{
                       color: "var(--color-ink-mute)",
                       fontFamily: "var(--font-mono)",
                       background: "var(--color-bg)",
                       borderRadius: 8,
                       padding: "10px 12px",
                     }}>
                  {r.prompt}
                </pre>
              </div>
            )}
          </div>
        ),
      )}
    </div>
  );
}
