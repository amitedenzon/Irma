import { useCallback, useEffect, useRef, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { StandupView } from "./StandupView";
import { mockBrief } from "./mockBrief";
import { fetchStandup, forceRefresh } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, StandupBrief } from "../lib/types";

const USE_MOCK: boolean =
  (import.meta.env.VITE_USE_MOCK as string | undefined) === "1";

export function App() {
  const [brief, setBrief] = useState<StandupBrief | null>(
    USE_MOCK ? mockBrief : null,
  );
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!USE_MOCK);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const inFlightRef = useRef<boolean>(false);

  const load = useCallback(async (): Promise<void> => {
    if (USE_MOCK) return;
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    setLoading(true);
    setError(null);
    try {
      const b = await fetchStandup();
      setBrief(b);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
      inFlightRef.current = false;
    }
  }, []);

  // Initial load.
  useEffect(() => {
    void load();
  }, [load]);

  // Re-fetch when the backend signals it has settled into idle or alert after
  // a refresh (i.e. a fresh brief is available in cache).
  useEffect(() => {
    const sub = subscribeAgentState((s) => {
      setAgentState(s);
      if (s === "idle" || s === "alert") {
        void load();
      }
    });
    return () => sub.close();
  }, [load]);

  const refresh = useCallback(async (): Promise<void> => {
    try {
      await forceRefresh();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const closeWindow = (): void => {
    void getCurrentWindow().hide().catch(() => undefined);
  };

  return (
    <div className="min-h-screen w-full bg-nofari-bg text-nofari-text flex flex-col">
      <div
        data-tauri-drag-region
        className="h-10 flex items-center justify-between px-4 border-b border-nofari-border bg-nofari-surface shrink-0"
      >
        <div className="text-sm font-medium tracking-wide flex items-center gap-2 select-none">
          <StateDot state={agentState} />
          Nofari · Standup Brief
          <span className="text-xs text-nofari-mute font-mono ml-1">{agentState}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refresh()}
            className="text-xs text-nofari-mute hover:text-nofari-text px-2 py-0.5 rounded border border-nofari-border"
            aria-label="Force refresh"
            type="button"
            disabled={USE_MOCK}
            title={USE_MOCK ? "Refresh disabled in mock mode" : "Force re-observation"}
          >
            refresh
          </button>
          <button
            onClick={closeWindow}
            className="text-base leading-none text-nofari-mute hover:text-nofari-text px-2 py-0.5 rounded"
            aria-label="Hide window"
            type="button"
          >
            ×
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div className="text-sm text-nofari-amber mb-4">
            Brief unavailable: {error}
          </div>
        )}
        {brief ? <StandupView brief={brief} /> : <Skeleton loading={loading} />}
      </div>
    </div>
  );
}

function StateDot({ state }: { state: AgentState }) {
  const color =
    state === "alert"
      ? "bg-nofari-amber"
      : state === "thinking"
      ? "bg-nofari-violet"
      : state === "observing"
      ? "bg-nofari-teal"
      : "bg-nofari-indigo";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function Skeleton({ loading }: { loading: boolean }) {
  return (
    <div className="space-y-4 text-sm text-nofari-mute">
      <div>
        {loading
          ? "Waiting for Nofari to assemble your brief…"
          : "No brief yet. Hit refresh to ask Nofari to observe and synthesize."}
      </div>
    </div>
  );
}
