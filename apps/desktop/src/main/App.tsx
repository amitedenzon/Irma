import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { sendBriefEmail, listProjects } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, Project } from "../lib/types";
import { ProjectsView } from "./projects/ProjectsView";
import { ChatView } from "./chat/ChatView";
import { SettingsView } from "./settings/SettingsView";
import { MailIcon, SettingsIcon } from "../lib/icons";

type Tab = "projects" | "chat" | "settings";

type BriefSendState = "idle" | "sending" | "sent" | "error";

export function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [briefSendState, setBriefSendState] = useState<BriefSendState>("idle");

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

  const sendBrief = useCallback(async () => {
    setBriefSendState("sending");
    try {
      await sendBriefEmail();
      setBriefSendState("sent");
      setTimeout(() => setBriefSendState("idle"), 4000);
    } catch (e) {
      console.error("[dashboard] sendBriefEmail failed:", e);
      setBriefSendState("error");
      setTimeout(() => setBriefSendState("idle"), 4000);
    }
  }, []);

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
        onSendBrief={sendBrief}
        briefSendState={briefSendState}
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
        {/* Chat stays mounted so the Claude PTY (and Local history) survives tab switches. */}
        <div style={{ display: tab === "chat" ? "block" : "none", height: "100%" }}>
          <ChatView
            contextProjects={projects}
            onTaskMaybeCreated={loadProjects}
            tabVisible={tab === "chat"}
          />
        </div>
        {tab === "settings" && <SettingsView />}
      </main>
    </div>
  );
}

function Header({
  tab, onTabChange, agentState, onSendBrief, briefSendState, onClose,
}: {
  tab: Tab;
  onTabChange: (t: Tab) => void;
  agentState: AgentState;
  onSendBrief: () => void;
  briefSendState: BriefSendState;
  onClose: () => void;
}) {
  const stateColor = {
    idle: "var(--color-moss)",
    observing: "var(--color-amber)",
    thinking: "var(--color-red-hover)",
    alert: "var(--color-red)",
  }[agentState];

  const briefLabel = {
    idle: "Brief",
    sending: "Sending…",
    sent: "Sent ✓",
    error: "Failed",
  }[briefSendState];

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
        <button
          type="button"
          onClick={() => onSendBrief()}
          disabled={briefSendState === "sending"}
          aria-label="Email today's brief"
          title="Email today's brief"
          className="ml-auto px-4 py-2 text-[13px] font-medium transition-colors flex items-center gap-1.5 disabled:opacity-50"
          style={{ color: "var(--color-ink-mute)", borderBottom: "2px solid transparent" }}
        >
          <MailIcon size={16} className={briefSendState === "sending" ? "animate-pulse" : undefined} />
          {briefLabel}
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
