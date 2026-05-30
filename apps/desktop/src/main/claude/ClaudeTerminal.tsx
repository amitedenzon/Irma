import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const DATA_EVENT = "claude-pty:data";
const EXIT_EVENT = "claude-pty:exit";

export function ClaudeTerminal() {
  // Bumping the epoch unmounts the inner TerminalSession; cleanup kills the
  // current PTY and the next mount spawns a fresh one. Cheaper than wiring
  // an explicit restart command across the Tauri boundary.
  const [epoch, setEpoch] = useState(0);

  return (
    <div className="px-6 py-6 max-w-3xl mx-auto h-full flex flex-col">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span
            className="text-[13px] font-medium"
            style={{ color: "var(--color-ink)" }}
          >
            Claude
          </span>
          <span
            className="text-[11px]"
            style={{
              color: "var(--color-ink-faint)",
              fontFamily: "var(--font-mono)",
            }}
          >
            interactive · cwd: repo root
          </span>
        </div>
        <button
          type="button"
          onClick={() => setEpoch((n) => n + 1)}
          className="text-[11px] underline"
          style={{ color: "var(--color-ink-mute)" }}
        >
          restart session
        </button>
      </div>

      <div
        className="flex-1 overflow-hidden rounded-xl p-3"
        style={{
          background: "#0f1117",
          border: "1px solid var(--color-border)",
          boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
        }}
      >
        <TerminalSession key={epoch} />
      </div>

      <div
        className="mt-2 text-[11px] text-right"
        style={{ color: "var(--color-ink-faint)" }}
      >
        claude --dangerously-skip-permissions
      </div>
    </div>
  );
}

function TerminalSession() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const disposeRef = useRef<UnlistenFn[]>([]);

  useEffect(() => {
    if (!containerRef.current) return;

    const term = new Terminal({
      fontFamily:
        '"JetBrains Mono", "Menlo", "DejaVu Sans Mono", "Courier New", monospace',
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      theme: {
        background: "#0f1117",
        foreground: "#d8dee4",
        cursor: "#d8dee4",
        selectionBackground: "rgba(184, 52, 28, 0.35)",
      },
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(containerRef.current);
    fit.fit();
    termRef.current = term;
    fitRef.current = fit;

    const { rows, cols } = term;

    void invoke("claude_pty_spawn", { rows, cols }).catch((e: unknown) => {
      term.writeln(`\r\n[irma] failed to spawn claude: ${String(e)}\r\n`);
    });

    const onDataDisposable = term.onData((chunk: string) => {
      void invoke("claude_pty_write", { data: chunk }).catch((e: unknown) =>
        console.error("[claude_pty] write failed:", e),
      );
    });

    void listen<string>(DATA_EVENT, (event) => {
      term.write(event.payload);
    }).then((unlisten) => disposeRef.current.push(unlisten));

    void listen<{ code: number | null }>(EXIT_EVENT, (event) => {
      term.writeln(
        `\r\n[irma] claude exited (code ${event.payload.code ?? "?"})\r\n`,
      );
    }).then((unlisten) => disposeRef.current.push(unlisten));

    const onResize = () => {
      try {
        fit.fit();
        void invoke("claude_pty_resize", { rows: term.rows, cols: term.cols });
      } catch (e: unknown) {
        console.error("[claude_pty] resize failed:", e);
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      onDataDisposable.dispose();
      disposeRef.current.forEach((un) => {
        try {
          un();
        } catch {
          /* noop */
        }
      });
      disposeRef.current = [];
      void invoke("claude_pty_kill").catch(() => undefined);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, []);

  return <div ref={containerRef} className="h-full w-full" />;
}
