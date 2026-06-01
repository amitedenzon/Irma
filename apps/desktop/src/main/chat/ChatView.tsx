import { useEffect, useRef, useState } from "react";
import {
  sendChat,
  fetchLocalModels,
  fetchIntegrationsStatus,
  connectGoogleCalendar,
} from "../../lib/api";
import type { ChatMessage, Project } from "../../lib/types";
import type { LocalModel, IntegrationsStatus } from "../../lib/api";

type Mode = "claude" | "local";

export function ChatView({
  contextProjects: _ctx,
  onTaskMaybeCreated: _onTaskMaybeCreated,
}: {
  contextProjects: Project[];
  onTaskMaybeCreated: () => void | Promise<void>;
  tabVisible?: boolean;
}) {
  const [mode, setMode] = useState<Mode>("claude");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Local mode
  const [models, setModels] = useState<LocalModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");

  // Claude mode — integrations
  const [integrations, setIntegrations] = useState<IntegrationsStatus | null>(null);
  const [connecting, setConnecting] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const savedPath = localStorage.getItem("irma.settings.modelsPath") ?? undefined;
    fetchLocalModels(savedPath)
      .then((res) => {
        setModels(res.models);
        if (res.models.length > 0) setSelectedModel(res.models[0].name);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchIntegrationsStatus().then(setIntegrations).catch(() => {});
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  function switchMode(m: Mode) {
    setMode(m);
    setMessages([]);
    setError(null);
  }

  async function submit(): Promise<void> {
    const text = input.trim();
    if (!text || busy) return;

    const userMsg: ChatMessage = { role: "user", content: text };
    const next: ChatMessage[] = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError(null);

    try {
      const opts = mode === "local" && selectedModel ? { model: selectedModel } : {};
      const res = await sendChat(next, opts);
      setMessages([...next, { role: "assistant", content: res.reply }]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  async function handleConnect() {
    setConnecting(true);
    try {
      const updated = await connectGoogleCalendar();
      setIntegrations(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setConnecting(false);
    }
  }

  return (
    <div className="h-full w-full flex flex-col">
      {/* Top bar */}
      <div
        className="shrink-0 flex items-center justify-between gap-2 px-4 py-2 border-b"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <ModeToggle mode={mode} onChange={switchMode} />
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => { setMessages([]); setError(null); }}
            className="text-[11px] underline"
            style={{ color: "var(--color-ink-mute)" }}
          >
            new conversation
          </button>
        )}
      </div>

      {/* Model picker (local mode) */}
      {mode === "local" && (
        <div
          className="shrink-0 flex items-center gap-2 px-4 py-2 border-b"
          style={{ borderColor: "var(--color-border)" }}
        >
          <span className="text-[11px] uppercase tracking-wider shrink-0"
                style={{ color: "var(--color-ink-mute)" }}>
            Model
          </span>
          {models.length > 0 ? (
            <select
              className="input text-[12px] flex-1"
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
            >
              {models.map((m) => (
                <option key={m.name} value={m.name}>
                  {m.display_name}
                  {m.size_label ? ` · ${m.size_label}` : ""}
                </option>
              ))}
            </select>
          ) : (
            <span className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
              No local models — add them in Settings
            </span>
          )}
        </div>
      )}

      {/* Integrations bar (claude mode) */}
      {mode === "claude" && integrations && (
        <IntegrationsBar
          integrations={integrations}
          connecting={connecting}
          onConnect={handleConnect}
        />
      )}

      {/* Chat area */}
      <div
        className="flex-1 min-h-0 flex flex-col m-3 rounded-xl overflow-hidden"
        style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)" }}
      >
        <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 p-4">
          {messages.length === 0 && !busy && (
            <p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
              {mode === "claude"
                ? "Ask Irma anything — your day, projects, calendar, what to work on next."
                : "Ask your local model anything."}
            </p>
          )}
          {messages.map((m, i) => <Bubble key={i} message={m} />)}
          {busy && (
            <div className="text-[12px] italic" style={{ color: "var(--color-ink-mute)" }}>
              Thinking…
            </div>
          )}
          {error && (
            <div className="text-[13px]" style={{ color: "var(--color-red)" }}>{error}</div>
          )}
        </div>

        {/* Input */}
        <div
          className="shrink-0 flex items-end gap-2 px-3 py-3"
          style={{ borderTop: "1px solid var(--color-border)" }}
        >
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={onKey}
            rows={2}
            placeholder="Message Irma… (Enter to send)"
            className="input flex-1 resize-none"
            disabled={busy}
          />
          <button
            type="button"
            onClick={() => void submit()}
            disabled={busy || !input.trim()}
            className="btn-red"
          >
            send
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  return (
    <div className="flex rounded-full overflow-hidden" style={{ border: "1px solid var(--color-border)" }}>
      {(["claude", "local"] as const).map((m) => {
        const active = m === mode;
        return (
          <button key={m} type="button" onClick={() => onChange(m)}
                  className="px-3 py-1 text-[12px] capitalize"
                  style={{
                    background: active ? "var(--color-red)" : "transparent",
                    color: active ? "#fff" : "var(--color-ink)",
                  }}>
            {m}
          </button>
        );
      })}
    </div>
  );
}

function IntegrationsBar({
  integrations, connecting, onConnect,
}: { integrations: IntegrationsStatus; connecting: boolean; onConnect: () => void }) {
  return (
    <div
      className="shrink-0 flex items-center gap-2 px-4 py-1.5 border-b"
      style={{ borderColor: "var(--color-border)" }}
    >
      <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--color-ink-mute)" }}>
        Tools
      </span>
      <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>·</span>
      {integrations.calendar_linked ? (
        <span
          className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full"
          style={{ background: "color-mix(in srgb, var(--color-moss) 12%, transparent)", color: "var(--color-moss)" }}
        >
          <span>●</span> Calendar
        </span>
      ) : integrations.calendar_creds_set ? (
        <button
          type="button"
          onClick={onConnect}
          disabled={connecting}
          className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full transition-opacity disabled:opacity-50"
          style={{
            background: "color-mix(in srgb, var(--color-amber) 12%, transparent)",
            color: "var(--color-amber)",
            border: "1px solid color-mix(in srgb, var(--color-amber) 30%, transparent)",
          }}
        >
          {connecting ? "Connecting…" : "Connect Calendar"}
        </button>
      ) : (
        <span className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
          Calendar — add OAuth credentials in Settings
        </span>
      )}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className="max-w-[82%] px-3.5 py-2 text-[13px] leading-relaxed whitespace-pre-wrap rounded-2xl"
        style={{
          background: isUser ? "var(--color-red)" : "var(--color-bg)",
          color: isUser ? "#fff" : "var(--color-ink)",
          border: isUser ? "none" : "1px solid var(--color-border)",
          borderBottomRightRadius: isUser ? "4px" : undefined,
          borderBottomLeftRadius: !isUser ? "4px" : undefined,
        }}
      >
        {message.content}
      </div>
    </div>
  );
}
