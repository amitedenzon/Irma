import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { fetchBrief, forceRefresh, listProjects } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, Brief, Project } from "../lib/types";
import { ProjectsView } from "./projects/ProjectsView";
import { ChatView } from "./chat/ChatView";
import { ClaudeTerminal } from "./claude/ClaudeTerminal";
import { BriefView } from "./brief/BriefView";
import { SettingsView } from "./settings/SettingsView";
import { RefreshIcon, SettingsIcon } from "../lib/icons";

type Tab = "projects" | "chat" | "claude" | "brief" | "settings";

export function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);

  const loadProjects = useCallback(async () => {
    setProjectsError(null);
    try {
      const all = await listProjects(["active", "paused", "archived"]);
      setProjects(all);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e);
      setProjectsError(msg);
      console.error("[app] listProjects", e);
    }
  }, []);

  useEffect(() => { void loadProjects(); }, [loadProjects]);

  useEffect(() => {
    const sub = subscribeAgentState((s) => setAgentState(s));
    return () => sub.close();
  }, []);

  const synth = useCallback(async () => {
    setBriefBusy(true);
    setBriefError(null);
    try { setBrief(await fetchBrief("day")); }
    catch (e: unknown) { setBriefError(e instanceof Error ? e.message : String(e)); }
    finally { setBriefBusy(false); }
  }, []);

  // Pre-fetch the brief on mount so it's ready instantly when the user
  // clicks the Brief tab. Refire if the prior attempt errored and the user
  // later switches to the tab — gives them a retry path.
  useEffect(() => { void synth(); }, [synth]);
  useEffect(() => {
    if (tab === "brief" && !brief && !briefBusy && briefError) void synth();
  }, [tab, brief, briefBusy, briefError, synth]);

  const refresh = useCallback(async () => {
    setRefreshBusy(true);
    try { await forceRefresh(); await loadProjects(); }
    catch (e) { console.error(e); }
    finally { setRefreshBusy(false); }
  }, [loadProjects]);

  const closeWindow = () => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  return (
    <div className="min-h-screen w-full flex flex-col" style={{ background: "var(--color-bg)" }}>
      <Header
        tab={tab}
        onTabChange={setTab}
        agentState={agentState}
        onRefresh={refresh}
        refreshBusy={refreshBusy}
        onClose={closeWindow}
      />

      <main className="flex-1 overflow-y-auto">
        {tab === "projects" && (
          <ProjectsView
            projects={projects}
            error={projectsError}
            onProjectsChanged={setProjects}
            onReload={loadProjects}
          />
        )}
        {tab === "chat" && <ChatView contextProjects={projects} onTaskMaybeCreated={loadProjects} />}
        {tab === "claude" && <ClaudeTerminal />}
        {tab === "brief" && (
          <BriefView brief={brief} busy={briefBusy} error={briefError} onRefetch={synth} />
        )}
        {tab === "settings" && <SettingsView />}
      </main>
    </div>
  );
}

function Header({
  tab, onTabChange, agentState, onRefresh, refreshBusy, onClose,
}: {
  tab: Tab;
  onTabChange: (t: Tab) => void;
  agentState: AgentState;
  onRefresh: () => void;
  refreshBusy: boolean;
  onClose: () => void;
}) {
  const stateColor = {
    idle: "var(--color-moss)",
    observing: "var(--color-amber)",
    thinking: "var(--color-red-hover)",
    alert: "var(--color-red)",
  }[agentState];

  return (
    <header
      data-tauri-drag-region
      className="shrink-0 px-5 pt-3 pb-0 select-none border-b"
      style={{
        background: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2.5">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: stateColor }}
            aria-label={`agent ${agentState}`}
          />
          <h1 className="display text-[18px] font-semibold" style={{ color: "var(--color-ink)" }}>
            Irma
          </h1>
          <span className="text-[11px]" style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}>
            {agentState}
          </span>
        </div>
        <button onClick={onClose} aria-label="Close"
                className="px-2 py-1 text-[14px] leading-none rounded-md hover:bg-[var(--color-surface-2)]"
                style={{ color: "var(--color-ink-mute)" }}>
          ×
        </button>
      </div>
      <nav className="flex items-center gap-1 -mb-px">
        <Tab id="projects" current={tab} onClick={onTabChange}>Projects</Tab>
        <Tab id="chat"     current={tab} onClick={onTabChange}>Chat</Tab>
        <Tab id="claude"   current={tab} onClick={onTabChange}>Claude</Tab>
        <Tab id="brief"    current={tab} onClick={onTabChange}>Brief</Tab>
        <button
          type="button"
          onClick={() => void onRefresh()}
          disabled={refreshBusy}
          aria-label={refreshBusy ? "Refreshing" : "Refresh"}
          title="Refresh"
          className="ml-auto px-4 py-2 text-[13px] font-medium transition-colors flex items-center disabled:opacity-50"
          style={{ color: "var(--color-ink-mute)", borderBottom: "2px solid transparent" }}
        >
          <RefreshIcon size={16} className={refreshBusy ? "animate-spin" : undefined} />
        </button>
        <Tab id="settings" current={tab} onClick={onTabChange}
             aria-label="Settings" title="Settings">
          <SettingsIcon size={16} />
        </Tab>
      </nav>
    </header>
  );
}

function Tab({
  id, current, onClick, children, className, ...rest
}: {
  id: Tab;
  current: Tab;
  onClick: (t: Tab) => void;
  children: React.ReactNode;
  className?: string;
} & Pick<React.ButtonHTMLAttributes<HTMLButtonElement>, "aria-label" | "title">) {
  const active = current === id;
  return (
    <button
      type="button"
      onClick={() => onClick(id)}
      className={`px-4 py-2 text-[13px] font-medium transition-colors flex items-center${className ? ` ${className}` : ""}`}
      style={{
        color: active ? "var(--color-red)" : "var(--color-ink-mute)",
        borderBottom: `2px solid ${active ? "var(--color-red)" : "transparent"}`,
      }}
      {...rest}
    >
      {children}
    </button>
  );
}
