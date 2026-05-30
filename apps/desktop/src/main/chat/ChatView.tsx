import { useEffect, useRef, useState } from "react";
import { sendChat } from "../../lib/api";
import type { ChatMessage, Project } from "../../lib/types";
import { ClaudeTerminal } from "../claude/ClaudeTerminal";

type Mode = "claude" | "local";

/**
 * Chat tab container: hosts both Claude (terminal) and Local (Ollama chat)
 * surfaces inside one framed pane and lets the user switch between them.
 * Both panes stay mounted at all times so terminal state and chat history
 * survive mode toggles and tab switches alike — the parent passes
 * `tabVisible` so the Claude pane can refit after coming back into view.
 */
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
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (mode !== "local") return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy, mode]);

  function clearConversation(): void {
    setMessages([]);
    setMeta(null);
    setError(null);
  }

  async function submit(): Promise<void> {
    const text = input.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const res = await sendChat(next);
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
    <div className="px-6 py-6 max-w-3xl mx-auto h-full flex flex-col">
      <div className="mb-3 flex items-center justify-between gap-2">
        <ModeToggle mode={mode} onChange={setMode} />
        <ActionButton
          mode={mode}
          canClearLocal={messages.length > 0}
          onClaudeRestart={() => setClaudeEpoch((n) => n + 1)}
          onLocalClear={clearConversation}
        />
      </div>

      {/* Claude pane — kept mounted regardless of mode so the PTY survives. */}
      <div
        className="flex-1 min-h-0 flex flex-col"
        style={{ display: mode === "claude" ? "flex" : "none" }}
      >
        <ClaudeTerminal
          visible={tabVisible && mode === "claude"}
          epoch={claudeEpoch}
        />
      </div>

      {/* Local pane — also kept mounted so the conversation persists. */}
      <div
        className="flex-1 min-h-0 flex flex-col"
        style={{ display: mode === "local" ? "flex" : "none" }}
      >
        <div
          className="flex-1 min-h-0 flex flex-col rounded-xl overflow-hidden"
          style={{
            background: "var(--color-surface)",
            border: "1px solid var(--color-border)",
          }}
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
              <div className="text-[13px]" style={{ color: "var(--color-red)" }}>
                {error}
              </div>
            )}
          </div>
          <div
            className="p-3 flex items-end gap-2"
            style={{ borderTop: "1px solid var(--color-border)" }}
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              rows={2}
              placeholder="Message Irma… (Enter to send, Shift+Enter for newline)"
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
      </div>

      <div
        className="mt-2 text-[11px] text-right"
        style={{ color: "var(--color-ink-faint)" }}
      >
        {mode === "claude"
          ? "claude --dangerously-skip-permissions"
          : meta
            ? `${meta.backend} · ${meta.model}`
            : "local · ollama"}
      </div>
    </div>
  );
}

function ModeToggle({
  mode,
  onChange,
}: {
  mode: Mode;
  onChange: (m: Mode) => void;
}) {
  const modes: { id: Mode; label: string }[] = [
    { id: "claude", label: "Claude" },
    { id: "local", label: "Local" },
  ];
  return (
    <div
      className="flex rounded-full overflow-hidden"
      style={{ border: "1px solid var(--color-border)" }}
    >
      {modes.map((m) => {
        const active = m.id === mode;
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            className="px-3 py-1 text-[12px]"
            style={{
              background: active ? "var(--color-red)" : "transparent",
              color: active ? "#fff" : "var(--color-ink)",
            }}
          >
            {m.label}
          </button>
        );
      })}
    </div>
  );
}

function ActionButton({
  mode,
  canClearLocal,
  onClaudeRestart,
  onLocalClear,
}: {
  mode: Mode;
  canClearLocal: boolean;
  onClaudeRestart: () => void;
  onLocalClear: () => void;
}) {
  if (mode === "claude") {
    return (
      <button
        type="button"
        onClick={onClaudeRestart}
        className="text-[11px] underline"
        style={{ color: "var(--color-ink-mute)" }}
      >
        restart session
      </button>
    );
  }
  if (canClearLocal) {
    return (
      <button
        type="button"
        onClick={onLocalClear}
        className="text-[11px] underline"
        style={{ color: "var(--color-ink-mute)" }}
      >
        new conversation
      </button>
    );
  }
  return <span />;
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
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
        {message.content}
      </div>
    </div>
  );
}
