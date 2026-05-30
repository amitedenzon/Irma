import { useEffect, useRef, useState } from "react";
import { sendChat } from "../../lib/api";
import type { ChatMessage, Project } from "../../lib/types";

export function ChatView({
  contextProjects: _ctx,
  onTaskMaybeCreated: _onTaskMaybeCreated,
}: {
  contextProjects: Project[];
  onTaskMaybeCreated: () => void | Promise<void>;
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ backend: string; model: string } | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

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
      {messages.length > 0 && (
        <div className="mb-3 flex items-center justify-end">
          <button
            type="button"
            onClick={clearConversation}
            className="text-[11px] underline"
            style={{ color: "var(--color-ink-mute)" }}
          >
            new conversation
          </button>
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-4 pr-1">
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

      <div className="mt-4 flex items-end gap-2">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          rows={2}
          placeholder="Message Irma… (Enter to send, Shift+Enter for newline)"
          className="input flex-1 resize-y"
          disabled={busy}
        />
        <button type="button" onClick={() => void submit()} disabled={busy || !input.trim()} className="btn-red">
          send
        </button>
      </div>
      {meta && (
        <div className="mt-2 text-[11px] text-right" style={{ color: "var(--color-ink-faint)" }}>
          {meta.backend} · {meta.model}
        </div>
      )}
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className="max-w-[80%] px-3.5 py-2 text-[13.5px] leading-snug whitespace-pre-wrap rounded-2xl"
        style={{
          background: isUser ? "var(--color-red)" : "var(--color-surface)",
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
