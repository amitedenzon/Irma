import { useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AgentState, SpriteManifest } from "../lib/types";
import { subscribeAgentState } from "../lib/sse";
import { Sprite } from "./Sprite";

export function Companion() {
  const [manifest, setManifest] = useState<SpriteManifest | null>(null);
  const [sheetAvailable, setSheetAvailable] = useState<boolean>(false);
  const [state, setState] = useState<AgentState>("idle");

  // Load the sprite manifest and probe whether the real sheet exists.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/sprites/manifest.json");
        if (!res.ok) return;
        const m = (await res.json()) as SpriteManifest;
        if (cancelled) return;
        setManifest(m);
        const probe = await fetch(`/sprites/${m.image}`, { method: "HEAD" });
        if (!cancelled) setSheetAvailable(probe.ok);
      } catch {
        // Manifest unavailable — render nothing rather than crashing the window.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Anchor the companion beside the Dock once the window has mounted React.
  useEffect(() => {
    invoke("position_companion").catch(() => undefined);
  }, []);

  // Subscribe to AgentState transitions. Phase 1: backend may be absent —
  // EventSource auto-retries, sprite stays at 'idle' in the meantime.
  useEffect(() => {
    const sub = subscribeAgentState(setState);
    return () => sub.close();
  }, []);

  if (!manifest) return null;

  const onClick = (): void => {
    void invoke("toggle_main").catch(() => undefined);
  };

  return (
    <div
      className="w-screen h-screen flex items-center justify-center cursor-pointer"
      onClick={onClick}
      role="button"
      aria-label="Nofari companion"
    >
      <Sprite state={state} manifest={manifest} sheetAvailable={sheetAvailable} />
    </div>
  );
}
