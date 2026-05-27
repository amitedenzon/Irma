import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { fetchBrief, forceRefresh, listProjects } from "../lib/api";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, Brief, Project } from "../lib/types";
import { IconRefresh, IconSpark, IconX } from "../lib/icons";
import { ChatPanel } from "./components/ChatPanel";
import { ProjectsView } from "./projects/ProjectsView";

export function App() {
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [brief, setBrief] = useState<Brief | null>(null);
  const [briefBusy, setBriefBusy] = useState(false);
  const [briefError, setBriefError] = useState<string | null>(null);
  const [refreshBusy, setRefreshBusy] = useState(false);

  const loadProjects = useCallback(async () => {
    try {
      const all = await listProjects(["active", "paused", "archived"]);
      setProjects(all);
      setSelectedId((cur) => cur ?? (all.find((p) => p.status === "active")?.id ?? all[0]?.id ?? null));
    } catch (e) {
      console.error("[app] listProjects", e);
    }
  }, []);

  useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  useEffect(() => {
    const sub = subscribeAgentState((s) => setAgentState(s));
    return () => sub.close();
  }, []);

  const selected = projects.find((p) => p.id === selectedId) ?? null;
  const path = selected ? `~/projects/${slug(selected.name)}` : "~/projects";

  const synth = useCallback(async () => {
    setBriefBusy(true);
    setBriefError(null);
    try {
      setBrief(await fetchBrief("day"));
    } catch (e) {
      setBriefError(e instanceof Error ? e.message : String(e));
    } finally {
      setBriefBusy(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    setRefreshBusy(true);
    try { await forceRefresh(); }
    catch (e) { console.error(e); }
    finally { setRefreshBusy(false); }
  }, []);

  const closeWindow = () => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  return (
    <div className="min-h-screen w-full paper-bg flex flex-col" style={{ color: "var(--color-ink)" }}>
      <TerminalHeader
        path={path}
        agentState={agentState}
        onSynth={() => { setBriefOpen(true); if (!brief) void synth(); }}
        onRefresh={() => void refresh()}
        onClose={closeWindow}
        refreshBusy={refreshBusy}
        briefOpen={briefOpen}
      />

      {briefOpen && (
        <BriefDrawer
          brief={brief}
          busy={briefBusy}
          error={briefError}
          onClose={() => setBriefOpen(false)}
          onRefetch={() => void synth()}
        />
      )}

      <main className="flex-1 overflow-hidden">
        <ProjectsView
          projects={projects}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onProjectsChanged={setProjects}
          onReload={loadProjects}
        />
      </main>

      <ChatPanel
        contextProjectId={selectedId}
        contextProjectName={selected?.name ?? null}
        onTaskCreated={() => void loadProjects()}
      />
    </div>
  );
}

function slug(name: string): string {
  return name.toLowerCase().replace(/\s+/g, "-").replace(/[^a-z0-9-]/g, "");
}

function TerminalHeader({
  path, agentState, onSynth, onRefresh, onClose, refreshBusy, briefOpen,
}: {
  path: string;
  agentState: AgentState;
  onSynth: () => void;
  onRefresh: () => void;
  onClose: () => void;
  refreshBusy: boolean;
  briefOpen: boolean;
}) {
  const stateColor = {
    idle: "var(--color-moss)",
    observing: "var(--color-amber-stain)",
    thinking: "var(--color-red-glow)",
    alert: "var(--color-red-seal)",
  }[agentState];

  return (
    <header
      data-tauri-drag-region
      className="scanlines h-11 flex items-center justify-between px-3 select-none border-b"
      style={{
        background: "linear-gradient(180deg, var(--color-paper-deep) 0%, var(--color-paper) 100%)",
        borderColor: "var(--color-rule)",
      }}
    >
      <div className="flex items-center gap-3 min-w-0">
        <span
          className="pdot"
          style={{ background: stateColor, boxShadow: `0 0 0 2px var(--color-paper-deep), 0 0 0 3px ${stateColor}` }}
          aria-label={`agent ${agentState}`}
        />
        <span style={{ fontFamily: "var(--font-display)" }} className="text-[13px] tracking-tight">
          <span style={{ color: "var(--color-red-seal)" }}>irma</span>
          <span style={{ color: "var(--color-ink-mute)" }}>@local</span>
          <span style={{ color: "var(--color-ink-faint)" }}> {path} </span>
          <span style={{ color: "var(--color-red-seal)" }} className="caret">%</span>
        </span>
      </div>
      <div className="flex items-center gap-1">
        <HeaderButton onClick={onSynth} title="Synthesize today's brief" active={briefOpen}>
          <IconSpark size={14} /> <span>brief</span>
        </HeaderButton>
        <HeaderButton onClick={onRefresh} title="Force observer re-collection" busy={refreshBusy}>
          <IconRefresh size={14} /> <span>refresh</span>
        </HeaderButton>
        <HeaderButton onClick={onClose} title="Hide dashboard" subtle>
          <IconX size={14} />
        </HeaderButton>
      </div>
    </header>
  );
}

function HeaderButton({
  children, onClick, title, active, busy, subtle,
}: {
  children: React.ReactNode;
  onClick: () => void;
  title: string;
  active?: boolean;
  busy?: boolean;
  subtle?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      disabled={busy}
      className="text-[11px] uppercase tracking-wider px-2 py-1 flex items-center gap-1.5 transition-colors"
      style={{
        fontFamily: "var(--font-mono)",
        color: subtle ? "var(--color-ink-mute)" : active ? "var(--color-red-seal)" : "var(--color-ink)",
        background: active ? "var(--color-paper-fold)" : "transparent",
        border: subtle ? "none" : `1px solid ${active ? "var(--color-red-seal)" : "var(--color-rule)"}`,
        borderRadius: 0,
        opacity: busy ? 0.4 : 1,
      }}
    >
      {children}
    </button>
  );
}

function BriefDrawer({
  brief, busy, error, onClose, onRefetch,
}: {
  brief: Brief | null;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onRefetch: () => void;
}) {
  return (
    <div className="paper-inset border-b px-4 py-3" style={{ borderColor: "var(--color-rule)" }}>
      <div className="flex items-baseline justify-between mb-2">
        <div style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
             className="text-[11px] uppercase tracking-widest flex items-center gap-2">
          <IconSpark size={12} /> Brief · Today
        </div>
        <div className="flex items-center gap-3">
          <button onClick={onRefetch} disabled={busy}
                  className="text-[10px] uppercase tracking-wider hover:underline"
                  style={{ color: "var(--color-ink-mute)" }}>
            {busy ? "…" : "re-synth"}
          </button>
          <button onClick={onClose} aria-label="close brief"
                  style={{ color: "var(--color-ink-mute)" }}>
            <IconX size={12} />
          </button>
        </div>
      </div>
      {busy && !brief && (
        <div className="text-[12px]" style={{ color: "var(--color-ink-mute)" }}>
          Irma is reading the room…
        </div>
      )}
      {error && (
        <div className="text-[12px]" style={{ color: "var(--color-red-seal)" }}>
          brief unavailable: {error}
        </div>
      )}
      {brief && (
        <div className="space-y-2">
          {brief.recommendation && (
            <p style={{ fontFamily: "var(--font-serif)" }} className="text-[14px] leading-snug">
              {brief.recommendation}
            </p>
          )}
          {brief.conflicts.length > 0 && (
            <ul className="text-[12px] space-y-0.5">
              {brief.conflicts.map((c, i) => (
                <li key={i} className="flex gap-2" style={{ color: "var(--color-red-seal)" }}>
                  <span>!!</span><span>{c}</span>
                </li>
              ))}
            </ul>
          )}
          {brief.narrative && (
            <p style={{ fontFamily: "var(--font-serif)", color: "var(--color-ink-mute)" }}
               className="text-[13px] leading-snug italic whitespace-pre-wrap">
              {brief.narrative}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
