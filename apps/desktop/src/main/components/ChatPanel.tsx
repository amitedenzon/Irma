import { useEffect, useRef, useState } from "react";
import { sendChat } from "../../lib/api";
import type { ChatMessage } from "../../lib/types";
import { IconTerminal } from "../../lib/icons";

/**
 * Persistent bottom strip. Collapsed by default — shows the prompt line
 * with a hint. Expands upward on focus or when there's a conversation.
 *
 * Currently the NL-to-task path is not yet wired on the backend; we hint
 * at it in the placeholder so the user knows it's coming.
 */
export function ChatPanel({
  contextProjectId: _ctxId,
  contextProjectName,
  onTaskCreated: _onTaskCreated,
}: {
  contextProjectId: string | null;
  contextProjectName: string | null;
  onTaskCreated: () => void;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ backend: string; model: string } | null>(null);
  const [expanded, setExpanded] = useState(false);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => { if (messages.length > 0) setExpanded(true); }, [messages.length]);

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

  function onKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  const placeholder = contextProjectName
    ? `ask irma… (about ${contextProjectName} or anything)`
    : "ask irma anything…";

  return (
    <section
      className="border-t shrink-0 flex flex-col"
      style={{
        borderColor: "var(--color-rule)",
        background: "var(--color-paper)",
        maxHeight: expanded ? "22rem" : "auto",
      }}
    >
      {expanded && (
        <header className="px-3 py-1.5 flex items-baseline justify-between border-b"
                style={{ borderColor: "var(--color-rule)", background: "var(--color-paper-deep)" }}>
          <div className="flex items-center gap-2" style={{ color: "var(--color-red-seal)" }}>
            <IconTerminal size={12} />
            <span style={{ fontFamily: "var(--font-display)" }}
                  className="text-[10px] uppercase tracking-[0.18em]">
              ── irma · chat ──
            </span>
            {meta && (
              <span style={{ color: "var(--color-ink-faint)", fontFamily: "var(--font-mono)" }}
                    className="text-[10px]">
                {meta.backend} · {meta.model}
              </span>
            )}
          </div>
          <button onClick={() => { setExpanded(false); setMessages([]); }}
                  className="text-[10px] uppercase tracking-wider"
                  style={{ color: "var(--color-ink-mute)" }}>
            clear
          </button>
        </header>
      )}

      {expanded && (
        <div ref={scrollRef}
             className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
             style={{ minHeight: "8rem", maxHeight: "16rem" }}>
          {messages.length === 0 && !busy && (
            <p style={{ fontFamily: "var(--font-serif)", color: "var(--color-ink-mute)" }}
               className="text-[13px] italic">
              Try: <em>"what's on my plate today?"</em>, <em>"draft a 3-line standup for me."</em>
            </p>
          )}
          {messages.map((m, i) => <Bubble key={i} message={m} />)}
          {busy && (
            <div className="flex items-center gap-2 text-[12px]"
                 style={{ color: "var(--color-ink-mute)" }}>
              <span className="caret" style={{ fontFamily: "var(--font-mono)" }}>irma:</span>
              <span className="italic">thinking…</span>
            </div>
          )}
          {error && (
            <div className="text-[12px]" style={{ color: "var(--color-red-seal)" }}>
              !! chat failed: {error}
            </div>
          )}
        </div>
      )}

      <div className="flex items-center gap-2 px-3 py-2"
           style={{ background: "var(--color-paper)" }}>
        <span style={{ fontFamily: "var(--font-display)", color: "var(--color-red-seal)" }}
              className="text-[14px] shrink-0">
          ▍
        </span>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          onFocus={() => setExpanded(true)}
          placeholder={placeholder}
          className="flex-1 bg-transparent outline-none text-[13px]"
          style={{
            fontFamily: "var(--font-mono)",
            color: "var(--color-ink)",
            border: "none",
          }}
          disabled={busy}
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !input.trim()}
          className="wax-seal text-[10px] uppercase tracking-wider px-3 py-1"
          style={{ fontFamily: "var(--font-mono)" }}
        >
          send
        </button>
      </div>
    </section>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className="flex gap-2 text-[13px] leading-snug">
      <span style={{
        fontFamily: "var(--font-mono)",
        color: isUser ? "var(--color-ink-mute)" : "var(--color-red-seal)",
        minWidth: "3.5rem",
      }} className="shrink-0">
        {isUser ? "you:" : "irma:"}
      </span>
      <span style={{
        fontFamily: isUser ? "var(--font-mono)" : "var(--font-serif)",
        color: "var(--color-ink)",
        fontSize: isUser ? 12 : 14,
      }} className="whitespace-pre-wrap flex-1">
        {message.content}
      </span>
    </div>
  );
}
