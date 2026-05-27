import { useCallback, useEffect, useState } from "react";
import { completeTask, fetchBrief } from "../../lib/api";
import type { Brief, Horizon } from "../../lib/types";
import { ConflictList } from "./ConflictList";
import { FocusList } from "./FocusList";
import { HorizonTabs } from "./HorizonTabs";
import { Narrative } from "./Narrative";

export function BriefView({ agentSignal }: { agentSignal: number }) {
  const [horizon, setHorizon] = useState<Horizon>("day");
  const [brief, setBrief] = useState<Brief | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (h: Horizon) => {
    setLoading(true);
    setError(null);
    try {
      setBrief(await fetchBrief(h));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  // Reload whenever horizon changes OR the parent signals a backend settle.
  useEffect(() => {
    void load(horizon);
  }, [horizon, agentSignal, load]);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <HorizonTabs current={horizon} onChange={setHorizon} />
        {loading && <span className="text-xs text-irma-mute">loading…</span>}
      </div>

      {error && (
        <div className="text-sm text-irma-amber">Brief unavailable: {error}</div>
      )}

      {brief && (
        <>
          {brief.recommendation && (
            <section className="border border-irma-border rounded-lg p-4 bg-irma-surface">
              <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
                Recommendation
              </h3>
              <p className="text-sm leading-relaxed">{brief.recommendation}</p>
            </section>
          )}
          <FocusList
            items={brief.focus}
            onCompleteTask={async (tid) => {
              await completeTask(tid);
              await load(horizon);
            }}
          />
          <ConflictList items={brief.conflicts} />
          {brief.project_status.length > 0 && (
            <section>
              <h3 className="text-xs uppercase tracking-widest text-irma-mute mb-2">
                Project status
              </h3>
              <ul className="space-y-2 text-sm">
                {brief.project_status.map((ps) => (
                  <li key={ps.project_id} className="border border-irma-border rounded p-3">
                    <div className="font-medium">{ps.project_name}</div>
                    <div className="text-xs text-irma-mute">
                      open {ps.open_tasks} · done {ps.done_tasks}
                      {ps.days_to_target !== null ? ` · ${ps.days_to_target}d to target` : ""}
                    </div>
                    {ps.note && <div className="text-xs mt-1">{ps.note}</div>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          <Narrative text={brief.narrative} />
        </>
      )}
    </div>
  );
}
