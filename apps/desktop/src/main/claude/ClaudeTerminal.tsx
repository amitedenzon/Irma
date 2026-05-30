import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const DATA_EVENT = "claude-pty:data";
const EXIT_EVENT = "claude-pty:exit";

/**
 * Framed Claude terminal pane.
 *
 * Owns the dark rounded card and hands the inner xterm work to TerminalSession,
 * which is keyed on `epoch` so the parent can force a fresh PTY by bumping it.
 * `visible` flows down so we can refit after the panel switches back from
 * display:none (xterm.js can't measure a hidden container).
 */
export function ClaudeTerminal({
  visible,
  epoch,
}: {
  visible: boolean;
  epoch: number;
}) {
  return (
    <div
      className="flex-1 min-h-0 overflow-hidden rounded-xl p-3"
      style={{
        background: "#0f1117",
        border: "1px solid var(--color-border)",
        boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04)",
      }}
    >
      <TerminalSession key={epoch} visible={visible} />
    </div>
  );
}

function TerminalSession({ visible }: { visible: boolean }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    // StrictMode in dev double-invokes effects; the two `listen()` promises
    // may not resolve before the cleanup runs. `cancelled` guards the
    // late-resolving handlers so we never leak listeners on the dead term.
    let cancelled = false;
    const unlistens: UnlistenFn[] = [];

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
    }).then((un) => {
      if (cancelled) {
        try { un(); } catch { /* noop */ }
      } else {
        unlistens.push(un);
      }
    });

    void listen<{ code: number | null }>(EXIT_EVENT, (event) => {
      term.writeln(
        `\r\n[irma] claude exited (code ${event.payload.code ?? "?"})\r\n`,
      );
    }).then((un) => {
      if (cancelled) {
        try { un(); } catch { /* noop */ }
      } else {
        unlistens.push(un);
      }
    });

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
      cancelled = true;
      window.removeEventListener("resize", onResize);
      onDataDisposable.dispose();
      unlistens.forEach((un) => {
        try { un(); } catch { /* noop */ }
      });
      void invoke("claude_pty_kill").catch(() => undefined);
      term.dispose();
      termRef.current = null;
      fitRef.current = null;
    };
  }, []);

  // Refit + sync size when transitioning to visible. Hidden containers
  // measure as 0x0, so xterm's initial fit during display:none is wrong.
  useEffect(() => {
    if (!visible) return;
    const raf = requestAnimationFrame(() => {
      try {
        fitRef.current?.fit();
        if (termRef.current) {
          void invoke("claude_pty_resize", {
            rows: termRef.current.rows,
            cols: termRef.current.cols,
          });
        }
      } catch (e) {
        console.error("[claude_pty] refit failed:", e);
      }
    });
    return () => cancelAnimationFrame(raf);
  }, [visible]);

  return <div ref={containerRef} className="h-full w-full" />;
}
