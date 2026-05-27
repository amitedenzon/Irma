import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { forceRefresh } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState } from "../lib/types";
import { BriefView } from "./brief/BriefView";
import { ChatPanel } from "./components/ChatPanel";
import { ProjectsView } from "./projects/ProjectsView";

type Tab = "brief" | "projects";

export function App() {
  const [tab, setTab] = useState<Tab>("brief");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  // Increment whenever the backend settles after a refresh — BriefView reloads.
  const [agentSignal, setAgentSignal] = useState(0);

  useEffect(() => {
    const sub = subscribeAgentState((s) => {
      setAgentState(s);
      if (s === "idle" || s === "alert") setAgentSignal((n) => n + 1);
    });
    return () => sub.close();
  }, []);

  const refresh = async () => {
    try { await forceRefresh(); } catch (e) { console.error(e); }
  };

  const closeWindow = () => {
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
        <div className="flex items-center gap-3 select-none">
          <StateDot state={agentState} />
          <span className="text-sm font-medium tracking-wide">Irma</span>
          <nav className="flex gap-1 ml-2">
            <TabButton current={tab} id="brief"    onClick={setTab} label="Brief" />
            <TabButton current={tab} id="projects" onClick={setTab} label="Projects" />
          </nav>
          <span className="text-xs text-irma-mute font-mono ml-2">{agentState}</span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => void refresh()} type="button"
                  className="text-xs text-irma-mute hover:text-irma-text px-2 py-0.5 rounded border border-irma-border">
            refresh
          </button>
          <button onClick={closeWindow} type="button" aria-label="Hide window"
                  className="text-base leading-none text-irma-mute hover:text-irma-text px-2 py-0.5 rounded">
            ×
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-4xl mx-auto space-y-6">
          {tab === "brief" ? <BriefView agentSignal={agentSignal} /> : <ProjectsView />}
          <ChatPanel />
        </div>
      </div>
    </div>
  );
}

function TabButton({
  current, id, onClick, label,
}: { current: Tab; id: Tab; onClick: (t: Tab) => void; label: string }) {
  const active = current === id;
  return (
    <button
      type="button"
      onClick={() => onClick(id)}
      className={
        "px-2 py-0.5 text-xs rounded " +
        (active ? "bg-irma-surface text-irma-text border border-irma-border" : "text-irma-mute hover:text-irma-text")
      }
    >
      {label}
    </button>
  );
}

function StateDot({ state }: { state: AgentState }) {
  const color =
    state === "alert" ? "bg-irma-amber"
    : state === "thinking" ? "bg-irma-violet"
    : state === "observing" ? "bg-irma-teal"
    : "bg-irma-indigo";
  return <span className={`inline-block w-2 h-2 rounded-full ${color}`} />;
}
