import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
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
    // Route through Rust so `main:visibility` fires (companion needs it to
    // exit bark mode). Direct getCurrentWindow().hide() would bypass that.
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  return (
    <div className="min-h-screen w-full bg-irma-bg text-irma-text flex flex-col">
      <div
        data-tauri-drag-region
        className="h-10 flex items-center justify-between px-4 border-b border-irma-border bg-irma-surface shrink-0"
      >
        <div className="text-sm font-medium tracking-wide flex items-center gap-2 select-none">
          <StateDot state={agentState} />
          Irma · Standup Brief
          <span className="text-xs text-irma-mute font-mono ml-1">{agentState}</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refresh()}
            className="text-xs text-irma-mute hover:text-irma-text px-2 py-0.5 rounded border border-irma-border"
            aria-label="Force refresh"
            type="button"
            disabled={USE_MOCK}
            title={USE_MOCK ? "Refresh disabled in mock mode" : "Force re-observation"}
          >
            refresh
          </button>
          <button
            onClick={closeWindow}
            className="text-base leading-none text-irma-mute hover:text-irma-text px-2 py-0.5 rounded"
            aria-label="Hide window"
            type="button"
          >
            ×
          </button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div className="text-sm text-irma-amber mb-4">
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
      ? "bg-irma-amber"
      : state === "thinking"
      ? "bg-irma-violet"
      : state === "observing"
      ? "bg-irma-teal"
      : "bg-irma-indigo";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}

function Skeleton({ loading }: { loading: boolean }) {
  return (
    <div className="space-y-4 text-sm text-irma-mute">
      <div>
        {loading
          ? "Waiting for Irma to assemble your brief…"
          : "No brief yet. Hit refresh to ask Irma to observe and synthesize."}
      </div>
    </div>
  );
}
