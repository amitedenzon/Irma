import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { StandupView } from "./StandupView";
import { mockBrief } from "./mockBrief";
import { fetchStandup } from "../lib/api";
import type { StandupBrief } from "../lib/types";

const USE_MOCK: boolean =
  (import.meta.env.VITE_USE_MOCK as string | undefined) !== "0";

export function App() {
  const [brief, setBrief] = useState<StandupBrief | null>(USE_MOCK ? mockBrief : null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (USE_MOCK) return;
    let cancelled = false;
    fetchStandup()
      .then((b) => {
        if (!cancelled) setBrief(b);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
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
          <span className="inline-block w-2 h-2 rounded-full bg-nofari-indigo" />
          Nofari · Standup Brief
        </div>
        <button
          onClick={closeWindow}
          className="text-base leading-none text-nofari-mute hover:text-nofari-text px-2 py-0.5 rounded"
          aria-label="Hide window"
          type="button"
        >
          ×
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {error && (
          <div className="text-sm text-nofari-amber mb-4">
            Brief unavailable: {error}
          </div>
        )}
        {brief ? <StandupView brief={brief} /> : <Skeleton />}
      </div>
    </div>
  );
}

function Skeleton() {
  return (
    <div className="space-y-4 text-sm text-nofari-mute">
      <div>Waiting for Nofari to assemble your brief…</div>
    </div>
  );
}
