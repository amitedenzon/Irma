import { useEffect, useRef, useState } from "react";
import { sendChat, fetchLocalModels } from "../../lib/api";
import type { ChatMessage, Project } from "../../lib/types";
import type { LocalModel } from "../../lib/api";
import { ClaudeTerminal } from "../claude/ClaudeTerminal";

type Mode = "claude" | "local";

const PLAN_PREFIX =
  "Think step by step. First outline a structured plan with numbered steps, then execute it.\n\n";

export function ChatView({
  contextProjects: _ctx,
  onTaskMaybeCreated: _onTaskMaybeCreated,
  tabVisible = true,
}: {
  contextProjects: Project[];
  onTaskMaybeCreated: () => void | Promise<void>;
  tabVisible?: boolean;
}) {
  const [mode, setMode] = useState<Mode>("claude");
  const [claudeEpoch, setClaudeEpoch] = useState(0);

  // Local chat state
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ backend: string; model: string } | null>(null);

  // Model picker
  const [models, setModels] = useState<LocalModel[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");

  // Media attach
  const [pendingImage, setPendingImage] = useState<{ name: string; b64: string } | null>(null);

  // Plan mode
  const [planMode, setPlanMode] = useState(false);

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Fetch available local models on mount
  useEffect(() => {
    fetchLocalModels()
      .then((res) => {
        setModels(res.models);
        if (res.models.length > 0) {
          setSelectedModel(res.models[0].name);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (mode !== "local") return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, mode]);

  function clearConversation(): void {
    setMessages([]);
    setMeta(null);
    setError(null);
    setPendingImage(null);
  }

  function onFileSelected(e: React.ChangeEvent<HTMLInputElement>): void {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      const b64 = (reader.result as string).split(",")[1];
      if (b64) setPendingImage({ name: file.name, b64 });
    };
    reader.readAsDataURL(file);
    // Reset so the same file can be picked again
    e.target.value = "";
  }

  async function submit(): Promise<void> {
    const text = input.trim();
    if (!text || busy) return;

    const finalContent = planMode ? PLAN_PREFIX + text : text;
    const userMsg: ChatMessage = {
      role: "user",
      content: finalContent,
      ...(pendingImage ? { image_b64: pendingImage.b64 } : {}),
    };

    const next: ChatMessage[] = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setPendingImage(null);
    setBusy(true);
    setError(null);

    try {
      const res = await sendChat(next, { model: selectedModel || undefined });
      setMessages([...next, { role: "assistant", content: res.reply }]);
      setMeta({ backend: res.backend, model: res.model });
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

  return (
    <div className="h-full w-full flex flex-col">
      {/* Top bar */}
      <div
        className="shrink-0 flex items-center justify-between gap-2 px-4 py-2 border-b"
        style={{ background: "var(--color-surface)", borderColor: "var(--color-border)" }}
      >
        <ModeToggle mode={mode} onChange={setMode} />
        <ActionButton
          mode={mode}
          canClearLocal={messages.length > 0}
          onClaudeRestart={() => setClaudeEpoch((n) => n + 1)}
          onLocalClear={clearConversation}
        />
      </div>

      <div className="flex-1 min-h-0 relative">
        {/* Claude pane */}
        <div className="absolute inset-0" style={{ display: mode === "claude" ? "block" : "none" }}>
          <ClaudeTerminal visible={tabVisible && mode === "claude"} epoch={claudeEpoch} />
        </div>

        {/* Local pane */}
        <div
          className="absolute inset-0 flex flex-col p-4"
          style={{ display: mode === "local" ? "flex" : "none" }}
        >
          {/* Model picker */}
          <div className="shrink-0 flex items-center gap-2 mb-3">
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
                    {m.proficiency.length ? ` · ${m.proficiency.join(", ")}` : ""}
                  </option>
                ))}
              </select>
            ) : (
              <span className="text-[12px]" style={{ color: "var(--color-ink-faint)" }}>
                No models found — add them in Settings → Local
              </span>
            )}
          </div>

          {/* Chat area */}
          <div
            className="flex-1 min-h-0 flex flex-col rounded-xl overflow-hidden"
            style={{ background: "var(--color-surface)", border: "1px solid var(--color-border)" }}
          >
            <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 p-4">
              {messages.length === 0 && !busy && (
                <p className="text-[13px]" style={{ color: "var(--color-ink-mute)" }}>
                  Ask Irma anything — about your day, your projects, or what to work on next.
                </p>
              )}
              {messages.map((m, i) => <Bubble key={i} message={m} />)}
              {busy && (
                <div className="text-[12px] italic" style={{ color: "var(--color-ink-mute)" }}>
                  Irma is thinking…
                </div>
              )}
              {error && (
                <div className="text-[13px]" style={{ color: "var(--color-red)" }}>{error}</div>
              )}
            </div>

            {/* Pending image preview */}
            {pendingImage && (
              <div
                className="px-3 py-2 flex items-center gap-2"
                style={{ borderTop: "1px solid var(--color-border)" }}
              >
                <span className="text-[11px] px-2 py-0.5 rounded-full flex items-center gap-1.5"
                      style={{ background: "var(--color-surface-2)", color: "var(--color-ink-mute)" }}>
                  <span>🖼</span>
                  <span className="max-w-[160px] truncate">{pendingImage.name}</span>
                </span>
                <button type="button" onClick={() => setPendingImage(null)}
                        className="text-[11px]" style={{ color: "var(--color-ink-faint)" }}>
                  ✕
                </button>
              </div>
            )}

            {/* Toolbar + input */}
            <div style={{ borderTop: "1px solid var(--color-border)" }}>
              {/* Toolbar row */}
              <div className="flex items-center gap-1.5 px-3 pt-2.5 pb-1">
                {/* Attach image */}
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={busy}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all disabled:opacity-40 select-none"
                  style={{
                    background: pendingImage
                      ? "color-mix(in srgb, var(--color-red) 14%, transparent)"
                      : "var(--color-surface-2)",
                    color: pendingImage ? "var(--color-red)" : "var(--color-ink-mute)",
                    border: `1px solid ${pendingImage ? "color-mix(in srgb, var(--color-red) 35%, transparent)" : "var(--color-border)"}`,
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M2 12.5L6.5 7.5L9.5 11L11.5 8.5L14 12.5H2Z" />
                    <circle cx="5" cy="5" r="1.5" />
                    <rect x="1" y="1" width="14" height="14" rx="2.5" />
                  </svg>
                  {pendingImage ? "1 image" : "Image"}
                </button>

                {/* Plan mode */}
                <button
                  type="button"
                  onClick={() => setPlanMode((p) => !p)}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium transition-all select-none"
                  style={{
                    background: planMode
                      ? "color-mix(in srgb, var(--color-red) 14%, transparent)"
                      : "var(--color-surface-2)",
                    color: planMode ? "var(--color-red)" : "var(--color-ink-mute)",
                    border: `1px solid ${planMode ? "color-mix(in srgb, var(--color-red) 35%, transparent)" : "var(--color-border)"}`,
                  }}
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 4h10M3 8h7M3 12h5" />
                    <path d="M12 9l1.5 1.5L16 8" strokeWidth="1.6" />
                  </svg>
                  Plan{planMode ? " ✓" : ""}
                </button>
              </div>

              {/* Hidden file input — triggered by the Image button */}
              <input
                ref={fileInputRef}
                type="file"
                accept="image/png,image/jpeg,image/gif,image/webp"
                style={{ display: "none" }}
                onChange={onFileSelected}
              />

              {/* Input row */}
              <div className="flex items-end gap-2 px-3 pb-3">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={onKey}
                  rows={2}
                  placeholder={
                    planMode
                      ? "Describe what to plan… (step-by-step)"
                      : "Message Irma… (Enter to send)"
                  }
                  className="input flex-1 resize-y"
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

            {/* Status bar */}
            {meta && (
              <div
                className="px-3 py-1 text-[11px] text-right"
                style={{ color: "var(--color-ink-faint)", borderTop: "1px solid var(--color-border)" }}
              >
                {meta.backend} · {meta.model}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------
function ModeToggle({ mode, onChange }: { mode: Mode; onChange: (m: Mode) => void }) {
  const modes: { id: Mode; label: string }[] = [
    { id: "claude", label: "Claude" },
    { id: "local", label: "Local" },
  ];
  return (
    <div className="flex rounded-full overflow-hidden" style={{ border: "1px solid var(--color-border)" }}>
      {modes.map((m) => {
        const active = m.id === mode;
        return (
          <button key={m.id} type="button" onClick={() => onChange(m.id)}
                  className="px-3 py-1 text-[12px]"
                  style={{
                    background: active ? "var(--color-red)" : "transparent",
                    color: active ? "#fff" : "var(--color-ink)",
                  }}>
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

function ActionButton({
  mode, canClearLocal, onClaudeRestart, onLocalClear,
}: { mode: Mode; canClearLocal: boolean; onClaudeRestart: () => void; onLocalClear: () => void }) {
  if (mode === "claude") {
    return (
      <button type="button" onClick={onClaudeRestart}
              className="text-[11px] underline" style={{ color: "var(--color-ink-mute)" }}>
        restart session
      </button>
    );
  }
  if (canClearLocal) {
    return (
      <button type="button" onClick={onLocalClear}
              className="text-[11px] underline" style={{ color: "var(--color-ink-mute)" }}>
        new conversation
      </button>
    );
  }
  return <span />;
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  // Strip the plan-mode prefix from display so the bubble shows only the user's actual text
  const displayContent = message.content.startsWith(PLAN_PREFIX)
    ? message.content.slice(PLAN_PREFIX.length)
    : message.content;

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className="max-w-[80%] px-3.5 py-2 text-[13.5px] leading-snug whitespace-pre-wrap rounded-2xl"
        style={{
          background: isUser ? "var(--color-red)" : "var(--color-bg)",
          color: isUser ? "#fff" : "var(--color-ink)",
          border: isUser ? "none" : "1px solid var(--color-border)",
          borderBottomRightRadius: isUser ? "4px" : undefined,
          borderBottomLeftRadius: !isUser ? "4px" : undefined,
        }}
      >
        {message.image_b64 && (
          <img
            src={`data:image/jpeg;base64,${message.image_b64}`}
            alt="attached"
            className="mb-2 rounded-lg max-w-full max-h-48 object-contain"
          />
        )}
        {displayContent}
      </div>
    </div>
  );
}
