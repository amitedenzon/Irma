import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import "@xterm/xterm/css/xterm.css";

const DATA_EVENT = "claude-pty:data";
const EXIT_EVENT = "claude-pty:exit";

export function ClaudeTerminal() {
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
      lineHeight: 1.15,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      theme: {
        background: "#0f1117",
        foreground: "#d8dee4",
        cursor: "#d8dee4",
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

  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      style={{ background: "#0f1117" }}
    />
  );
}
