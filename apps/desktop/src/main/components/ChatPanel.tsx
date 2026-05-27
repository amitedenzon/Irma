import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "../../lib/types";
import { sendChat } from "../../lib/api";

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState<string>("");
  const [busy, setBusy] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<{ backend: string; model: string } | null>(
    null,
  );
  const scrollRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, busy]);

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

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>): void {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void submit();
    }
  }

  return (
    <section className="border border-irma-border rounded-lg bg-irma-surface flex flex-col h-[28rem]">
      <header className="px-4 py-2 border-b border-irma-border flex items-center justify-between shrink-0">
        <h3 className="text-xs uppercase tracking-widest text-irma-mute flex items-center gap-2">
          <span className="inline-block w-2 h-2 rounded-full bg-irma-indigo" />
          Ask Irma
        </h3>
        {meta && (
          <span className="text-[10px] font-mono text-irma-mute">
            {meta.backend} · {meta.model}
          </span>
        )}
      </header>

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3 space-y-3 text-sm"
      >
        {messages.length === 0 && !busy && (
          <p className="text-irma-mute italic">
            Try: "what's on my calendar today?" or "draft a 3-line standup for me."
          </p>
        )}
        {messages.map((m, i) => (
          <MessageBubble key={i} message={m} />
        ))}
        {busy && (
          <div className="text-irma-mute text-xs italic">Irma is thinking…</div>
        )}
        {error && (
          <div className="text-irma-amber text-xs">Chat failed: {error}</div>
        )}
      </div>

      <div className="border-t border-irma-border p-2 flex gap-2 shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKey}
          rows={2}
          placeholder="Message Irma… (Enter to send, Shift+Enter for newline)"
          className="flex-1 resize-none bg-irma-bg text-irma-text border border-irma-border rounded px-2 py-1.5 text-sm focus:outline-none focus:border-irma-indigo placeholder:text-irma-mute"
          disabled={busy}
        />
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || !input.trim()}
          className="px-3 py-1.5 text-sm rounded border border-irma-border text-irma-text hover:border-irma-indigo disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Send
        </button>
      </div>
    </section>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={
          isUser
            ? "max-w-[80%] rounded-lg px-3 py-2 bg-irma-indigo/15 border border-irma-indigo/30 text-irma-text"
            : "max-w-[80%] rounded-lg px-3 py-2 border border-irma-border text-irma-text"
        }
      >
        <div className="text-[10px] uppercase tracking-widest text-irma-mute mb-1">
          {isUser ? "you" : "irma"}
        </div>
        <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
      </div>
    </div>
  );
}
