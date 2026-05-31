import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emitTo } from "@tauri-apps/api/event";
import { sendBriefEmail, listProjects } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, Project } from "../lib/types";
import { ProjectsView } from "./projects/ProjectsView";
import { ChatView } from "./chat/ChatView";
import { SettingsView } from "./settings/SettingsView";
import { BriefIcon, SettingsIcon } from "../lib/icons";

const LOADING_SCREEN_KEY = "irma.settings.loadingScreen";
const API_BASE = "http://127.0.0.1:8765";

function useApiReady() {
  const [ready, setReady] = useState(false);
  const [dots, setDots] = useState(".");
  const attemptsRef = useRef(0);

  useEffect(() => {
    // Skip loading screen if disabled in settings
    if (localStorage.getItem(LOADING_SCREEN_KEY) === "false") {
      setReady(true);
      return;
    }

    const dotsInterval = setInterval(() => {
      setDots((d) => (d.length >= 3 ? "." : d + "."));
    }, 400);

    const poll = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/v1/state`, { signal: AbortSignal.timeout(1500) });
        if (res.ok) {
          clearInterval(dotsInterval);
          setReady(true);
          return;
        }
      } catch { /* not ready yet */ }
      attemptsRef.current += 1;
      // Give up after 30s and show the app anyway
      if (attemptsRef.current > 60) {
        clearInterval(dotsInterval);
        setReady(true);
        return;
      }
      setTimeout(() => void poll(), 500);
    };

    void poll();
    return () => clearInterval(dotsInterval);
  }, []);

  return { ready, dots };
}

type Tab = "projects" | "chat" | "settings";

type BriefSendState = "idle" | "sending" | "sent" | "error";

export function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [briefSendState, setBriefSendState] = useState<BriefSendState>("idle");
  const [confirmOpen, setConfirmOpen] = useState(false);
  const { ready, dots } = useApiReady();
  const [snacking, setSnacking] = useState(false);

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

  const confirmSend = useCallback(() => {
    setConfirmOpen(false);
    void sendBrief();
  }, [sendBrief]);

  const closeWindow = () => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  if (!ready) {
    return (
      <div
        className="min-h-screen w-full flex flex-col items-center justify-center gap-4"
        style={{ background: "var(--color-bg)" }}
      >
        {/* Pulsing logo mark */}
        <div
          className="w-12 h-12 rounded-2xl flex items-center justify-center animate-pulse"
          style={{ background: "color-mix(in srgb, var(--color-red) 15%, transparent)" }}
        >
          <span style={{ fontSize: 24 }}>🐾</span>
        </div>
        <div className="text-center space-y-1">
          <p className="display text-[16px] font-semibold" style={{ color: "var(--color-ink)" }}>
            Irma
          </p>
          <p className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
            Starting up{dots}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen w-full flex flex-col" style={{ background: "var(--color-bg)" }}>
      <Header
        tab={tab}
        onTabChange={setTab}
        agentState={agentState}
        onSendBrief={() => setConfirmOpen(true)}
        briefSendState={briefSendState}
        onClose={closeWindow}
        stateLabel={snacking ? "Snacking" : agentState}
        onTreat={() => {
          void emitTo("companion", "companion:treat");
          setSnacking(true);
          setTimeout(() => setSnacking(false), 2000);
        }}
      />

      <main className="flex-1 min-h-0 overflow-hidden relative flex flex-col">
        {/* Projects — scrolls inside its own wrapper */}
        {tab === "projects" && (
          <div className="absolute inset-0 overflow-y-auto">
            <ProjectsView
              projects={projects}
              error={projectsError}
              onProjectsChanged={setProjects}
              onReload={loadProjects}
            />
          </div>
        )}
        {/* Chat stays mounted so the Claude PTY (and Local history) survives tab
            switches. Absolute fill avoids the percent-height-through-flex chain
            collapsing the chat area when the parent's height isn't explicit. */}
        <div
          style={{
            display: tab === "chat" ? "block" : "none",
            position: "absolute",
            inset: 0,
          }}
        >
          <ChatView
            contextProjects={projects}
            onTaskMaybeCreated={loadProjects}
            tabVisible={tab === "chat"}
          />
        </div>
        {/* Settings fills the pane; inner tab bar is sticky, content scrolls */}
        {tab === "settings" && (
          <div className="absolute inset-0 flex flex-col">
            <SettingsView />
          </div>
        )}
      </main>

      <ConfirmDialog
        open={confirmOpen}
        title="Send daily brief?"
        message="I'll email today's brief — progress since your last one, plus deadlines and events for the next few days — to your inbox now."
        confirmLabel="Send it"
        cancelLabel="Not now"
        onConfirm={confirmSend}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

function ConfirmDialog({
  open, title, message, confirmLabel, cancelLabel, onConfirm, onCancel,
}: {
  open: boolean;
  title: string;
  message: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!open) return null;
  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={onCancel}
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: "rgba(0,0,0,0.45)" }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="mx-4 w-full max-w-sm rounded-xl border p-5 shadow-xl"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <h2 className="display text-[16px] font-semibold mb-2" style={{ color: "var(--color-ink)" }}>
          {title}
        </h2>
        <p className="text-[13px] mb-5" style={{ color: "var(--color-ink-mute)" }}>
          {message}
        </p>
        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="px-3.5 py-1.5 text-[13px] font-medium rounded-md hover:bg-[var(--color-surface-2)]"
            style={{ color: "var(--color-ink-mute)" }}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            autoFocus
            className="px-3.5 py-1.5 text-[13px] font-semibold rounded-md text-white"
            style={{ background: "var(--color-red)" }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function Header({
  tab, onTabChange, agentState, stateLabel, onSendBrief, briefSendState, onClose, onTreat,
}: {
  tab: Tab;
  onTabChange: (t: Tab) => void;
  agentState: AgentState;
  stateLabel: string;
  onSendBrief: () => void;
  briefSendState: BriefSendState;
  onClose: () => void;
  onTreat: () => void;
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
            {stateLabel}
          </span>
          <button
            type="button"
            onClick={onTreat}
            aria-label="Give Irma a treat"
            title="Give Irma a treat"
            className="text-[14px] leading-none rounded hover:opacity-70 transition-opacity"
            style={{ lineHeight: 1 }}
          >
            🧀
          </button>
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
        <div className="ml-auto flex items-center">
          <button
            type="button"
            onClick={() => onSendBrief()}
            disabled={briefSendState === "sending"}
            aria-label={briefSendState === "idle" ? "Email today's brief" : briefLabel}
            title={briefSendState === "idle" ? "Email today's brief" : briefLabel}
            className="px-4 py-2 transition-colors flex items-center disabled:opacity-50"
            style={{
              color:
                briefSendState === "sent"
                  ? "var(--color-moss)"
                  : briefSendState === "error"
                    ? "var(--color-red)"
                    : "var(--color-ink-mute)",
              borderBottom: "2px solid transparent",
            }}
          >
            <BriefIcon size={16} className={briefSendState === "sending" ? "animate-pulse" : undefined} />
          </button>
          <Tab id="settings" current={tab} onClick={onTabChange}
               aria-label="Settings" title="Settings">
            <SettingsIcon size={16} />
          </Tab>
        </div>
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
