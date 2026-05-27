import { useEffect, useState } from "react";
import type { CSSProperties } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AgentState, SpriteManifest } from "../lib/types";
import { subscribeAgentState } from "../lib/sse";
import { Sprite } from "./Sprite";

// Bundled fallback. Mirrors ARCHITECTURE §3 — used until /sprites/manifest.json
// loads successfully, so the companion window is never empty/invisible.
const FALLBACK_MANIFEST: SpriteManifest = {
  image: "nofari_sheet.png",
  frameWidth: 96,
  frameHeight: 96,
  states: {
    idle: { frames: [0, 1, 2, 1], fps: 4, loop: true },
    observing: { frames: [3, 4, 5], fps: 8, loop: true },
    thinking: { frames: [6, 7], fps: 6, loop: true },
    alert: { frames: [8, 9, 8, 9], fps: 10, loop: true },
  },
};

const WRAPPER_STYLE: CSSProperties = {
  width: "100vw",
  height: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  cursor: "pointer",
};

export function Companion() {
  const [manifest, setManifest] = useState<SpriteManifest>(FALLBACK_MANIFEST);
  const [sheetAvailable, setSheetAvailable] = useState<boolean>(false);
  const [state, setState] = useState<AgentState>("idle");

  useEffect(() => {
    console.info("[companion] mounted, using fallback manifest until fetch resolves");
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/sprites/manifest.json");
        if (!res.ok) {
          console.warn(
            "[companion] manifest fetch returned",
            res.status,
            "— keeping fallback",
          );
          return;
        }
        const m = (await res.json()) as SpriteManifest;
        if (cancelled) return;
        setManifest(m);
        // Probe must return a real image — Vite's dev server falls back to
        // index.html for unknown paths, so `probe.ok` alone is a lie.
        const probe = await fetch(`/sprites/${m.image}`, { method: "HEAD" });
        const contentType = probe.headers.get("content-type") ?? "";
        const hasRealSheet = probe.ok && contentType.startsWith("image/");
        if (!cancelled) setSheetAvailable(hasRealSheet);
        console.info(
          "[companion] manifest loaded — sheetAvailable=",
          hasRealSheet,
          "(probe.ok=",
          probe.ok,
          ", content-type=",
          contentType || "<none>",
          ")",
        );
      } catch (e) {
        console.warn("[companion] manifest fetch threw", e, "— keeping fallback");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    invoke("position_companion")
      .then(() => console.info("[companion] position_companion OK"))
      .catch((e: unknown) =>
        console.error("[companion] position_companion failed:", e),
      );
  }, []);

  useEffect(() => {
    const sub = subscribeAgentState(setState);
    return () => sub.close();
  }, []);

  const onClick = (): void => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[companion] toggle_main failed:", e),
    );
  };

  return (
    <div
      style={WRAPPER_STYLE}
      onClick={onClick}
      role="button"
      aria-label="Nofari companion"
    >
      <Sprite state={state} manifest={manifest} sheetAvailable={sheetAvailable} />
    </div>
  );
}
