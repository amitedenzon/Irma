import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emitTo } from "@tauri-apps/api/event";
import { Window as TauriWindow } from "@tauri-apps/api/window";
import confetti from "canvas-confetti";
import { listProjects } from "../lib/api";
import { needsSetup } from "../lib/onboarding";
import { subscribeAgentState } from "../lib/sse";
import type { AgentState, Project } from "../lib/types";
import { ProjectsView } from "./projects/ProjectsView";
import { ChatView } from "./chat/ChatView";
import { SettingsView } from "./settings/SettingsView";
import { ScheduleView } from "./schedule/ScheduleView";
import { OnboardingWizard } from "./onboarding/OnboardingWizard";
import { SettingsIcon } from "../lib/icons";

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

type Tab = "projects" | "chat" | "schedule" | "settings";

export function App() {
  const [tab, setTab] = useState<Tab>("projects");
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const { ready, dots } = useApiReady();
  const [setupState, setSetupState] = useState<"checking" | "wizard" | "app">("checking");
  const [snacking, setSnacking] = useState(false);

  // Drag-treat state
  const [dragging, setDragging] = useState(false);
  const [cheesePos, setCheesePos] = useState({ x: 0, y: 0 });
  const [thankYou, setThankYou] = useState(false);
  const dragStartPos = useRef<{ x: number; y: number } | null>(null);
  const draggingRef = useRef(false);
  const overDogRef = useRef(false);
  const companionBoundsRef = useRef<{ x: number; y: number; w: number; h: number } | null>(null);
  const cleanupDragRef = useRef<(() => void) | null>(null);

  // Once the backend is ready, check whether first-run setup is needed.
  useEffect(() => {
    if (!ready) return;
    needsSetup()
      .then((needs) => setSetupState(needs ? "wizard" : "app"))
      .catch(() => setSetupState("app"));
  }, [ready]);

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

  // Clean up any live drag listeners if the component unmounts mid-drag
  useEffect(() => {
    return () => {
      cleanupDragRef.current?.();
      document.documentElement.classList.remove("cheese-dragging");
    };
  }, []);

  const closeWindow = () => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[dashboard] toggle_main failed:", e),
    );
  };

  const giveClickTreat = () => {
    // Original click behavior — no confetti, no toast
    void emitTo("companion", "companion:treat");
    setSnacking(true);
    setTimeout(() => setSnacking(false), 2000);
  };

  const giveDragTreat = () => {
    // Drag-and-drop treat — full celebration
    void emitTo("companion", "companion:treat");
    setSnacking(true);
    setTimeout(() => setSnacking(false), 2000);
    setThankYou(true);
    setTimeout(() => setThankYou(false), 3000);
    void confetti({
      particleCount: 120,
      spread: 80,
      origin: { y: 0.4 },
      colors: ["#f5c518", "#ff6b6b", "#4ecdc4", "#45b7d1", "#f9ca24"],
    });
  };

  const startCheeseDrag = (e: React.MouseEvent) => {
    e.preventDefault();
    dragStartPos.current = { x: e.clientX, y: e.clientY };
    draggingRef.current = false;
    companionBoundsRef.current = null;

    const onMove = (me: MouseEvent) => {
      const dx = me.clientX - (dragStartPos.current?.x ?? me.clientX);
      const dy = me.clientY - (dragStartPos.current?.y ?? me.clientY);

      if (Math.sqrt(dx * dx + dy * dy) > 4 && !draggingRef.current) {
        draggingRef.current = true;
        setDragging(true);
        document.documentElement.classList.add("cheese-dragging");
        void emitTo("companion", "cheese:drag-start");
        // Fetch companion bounds once at drag start — reused for every mousemove hit-test
        void (async () => {
          try {
            const companion = new TauriWindow("companion");
            const pos = await companion.outerPosition();
            const sz = await companion.outerSize();
            companionBoundsRef.current = { x: pos.x, y: pos.y, w: sz.width, h: sz.height };
          } catch { /* companion window not available */ }
        })();
      }

      if (draggingRef.current) {
        setCheesePos({ x: me.clientX, y: me.clientY });
        const b = companionBoundsRef.current;
        if (b) {
          const dpr = window.devicePixelRatio ?? 1;
          const cx = me.screenX * dpr;
          const cy = me.screenY * dpr;
          overDogRef.current = cx >= b.x && cx <= b.x + b.w && cy >= b.y && cy <= b.y + b.h;
        }
      }
    };

    const onUp = () => {
      cleanupDragRef.current = null;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
      document.documentElement.classList.remove("cheese-dragging");

      if (!draggingRef.current) {
        giveClickTreat();
        return;
      }

      draggingRef.current = false;
      setDragging(false);
      void emitTo("companion", "cheese:drag-end");

      if (overDogRef.current) {
        overDogRef.current = false;
        giveDragTreat();
      }
    };

    cleanupDragRef.current = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!ready || setupState === "checking") {
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

  if (setupState === "wizard") {
    return <OnboardingWizard onDone={() => setSetupState("app")} />;
  }

  return (
    <div
      className="min-h-screen w-full flex flex-col"
      style={{ background: "var(--color-bg)" }}
    >
      <Header
        tab={tab}
        onTabChange={setTab}
        agentState={agentState}
        onClose={closeWindow}
        stateLabel={snacking ? "Snacking" : agentState}
        onCheeseDragStart={startCheeseDrag}
      />

      {/* Floating cheese follows cursor while dragging (visible inside window) */}
      {dragging && (
        <div
          style={{
            position: "fixed",
            left: cheesePos.x - 16,
            top: cheesePos.y - 16,
            fontSize: 28,
            pointerEvents: "none",
            zIndex: 9999,
            userSelect: "none",
            lineHeight: 1,
          }}
        >
          🧀
        </div>
      )}

      {/* Thank you toast */}
      {thankYou && (
        <div
          style={{
            position: "fixed",
            top: 60,
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 10000,
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
            borderRadius: 12,
            padding: "10px 20px",
            boxShadow: "0 4px 24px rgba(0,0,0,0.15)",
            display: "flex",
            alignItems: "center",
            gap: 8,
            animation: "fadeInDown 0.3s ease",
          }}
        >
          <span style={{ fontSize: 20 }}>🐾</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-ink)" }}>
            Irma loves the treat!
          </span>
          <span style={{ fontSize: 16 }}>🧀</span>
        </div>
      )}

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
        {tab === "schedule" && (
          <div className="absolute inset-0 overflow-y-auto">
            <ScheduleView />
          </div>
        )}
        {/* Settings fills the pane; inner tab bar is sticky, content scrolls */}
        {tab === "settings" && (
          <div className="absolute inset-0 flex flex-col">
            <SettingsView />
          </div>
        )}
      </main>

    </div>
  );
}


function Header({
  tab, onTabChange, agentState, stateLabel, onClose, onCheeseDragStart,
}: {
  tab: Tab;
  onTabChange: (t: Tab) => void;
  agentState: AgentState;
  stateLabel: string;
  onClose: () => void;
  onCheeseDragStart: (e: React.MouseEvent) => void;
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
            {stateLabel}
          </span>
          <button
            type="button"
            aria-label="Drag cheese to give Irma a treat"
            title="Drag to Irma to give a treat 🧀"
            onMouseDown={onCheeseDragStart}
            className="text-[14px] leading-none rounded select-none"
            style={{
              lineHeight: 1,
              cursor: "grab",
              userSelect: "none",
              background: "none",
              border: "none",
              padding: 0,
              // Exclude from Tauri's window drag region so mousedown isn't stolen
              WebkitAppRegion: "no-drag",
            } as React.CSSProperties}
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
        <Tab id="schedule" current={tab} onClick={onTabChange}>Schedule</Tab>
        <div className="ml-auto flex items-center">
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
