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
      className="h-full w-full overflow-hidden px-3 py-2"
      style={{ background: "var(--color-surface)" }}
    >
      <TerminalSession key={epoch} visible={visible} />
    </div>
  );
}

function readCssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

/**
 * Pull Irma's CSS palette into an xterm theme so the terminal reads as
 * "warm paper" rather than a black box dropped into the cream UI. ANSI
 * slots without a direct token mapping fall back to derived warm tones.
 */
function buildTheme() {
  const ink = readCssVar("--color-ink", "#2a1f17");
  const surface = readCssVar("--color-surface", "#fdfaf4");
  const inkMute = readCssVar("--color-ink-mute", "#7a6a52");
  const red = readCssVar("--color-red", "#b8341c");
  const redHover = readCssVar("--color-red-hover", "#d4543a");
  const redDeep = readCssVar("--color-red-deep", "#8a3a14");
  const moss = readCssVar("--color-moss", "#5a6b3a");
  const amber = readCssVar("--color-amber", "#c98a1a");

  return {
    background: surface,
    foreground: ink,
    cursor: red,
    cursorAccent: surface,
    selectionBackground: "rgba(184, 52, 28, 0.25)",
    selectionForeground: ink,

    black: ink,
    red,
    green: moss,
    yellow: amber,
    blue: "#3a5b6b",
    magenta: redDeep,
    cyan: "#4a7a6a",
    white: inkMute,

    brightBlack: inkMute,
    brightRed: redHover,
    brightGreen: "#7a8b5a",
    brightYellow: "#e0a83a",
    brightBlue: "#5a7b8b",
    brightMagenta: redHover,
    brightCyan: "#6a9b8a",
    brightWhite: ink,
  };
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
        '"Fira Code", "JetBrains Mono", "Menlo", "DejaVu Sans Mono", monospace',
      fontSize: 13,
      lineHeight: 1.2,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 5000,
      theme: buildTheme(),
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
