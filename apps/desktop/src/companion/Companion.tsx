import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { AgentState, SpriteFrameSpec, SpriteManifest } from "../lib/types";
import { subscribeAgentState } from "../lib/sse";
import {
  getCompanion,
  loadSettings,
  saveDockPosition,
  subscribeSettings,
  type DockPosition,
} from "../lib/settings";
import { Sprite } from "./Sprite";

const FALLBACK_MANIFEST: SpriteManifest = {
  image: "Irma.png",
  frameWidth: 64,
  frameHeight: 48,
  columns: 8,
  rows: 9,
  scale: 2,
  states: {
    idle: { frames: [0, 1, 2, 3, 4, 5], fps: 5, loop: true },
    observing: { frames: [32, 33, 34, 35, 36, 37, 38, 39], fps: 8, loop: true },
    thinking: { frames: [8, 9, 10, 11, 12, 13], fps: 4, loop: true },
    alert: { frames: [40, 41, 42, 43, 44, 45, 46, 47], fps: 10, loop: true },
  },
  extras: {
    cuddle: { frames: [64, 65, 66, 67], fps: 3, loop: true },
    walk: { frames: [32, 33, 34, 35, 36, 37, 38, 39], fps: 8, loop: true },
    walk_bark: { frames: [48, 49, 50, 51, 52, 53, 54, 55], fps: 9, loop: true },
    stand: { frames: [0, 1, 2, 3, 4, 5], fps: 5, loop: true },
    sit: { frames: [8, 9, 10, 11, 12, 13], fps: 4, loop: true },
    lay: { frames: [16, 17, 18, 19, 20, 21], fps: 4, loop: true },
    sit_bark: { frames: [8, 9, 10, 11, 12, 13, 14, 15], fps: 6, loop: true },
    treat: { frames: [56, 57, 58, 59, 60, 61, 62, 63], fps: 8, loop: true },
  },
};

interface CompanionBounds {
  monitorWidth: number;
  monitorHeight: number;
  spriteWidth: number;
  spriteHeight: number;
  y: number;
  minX: number;
  maxX: number;
  dockClearance: number;
  dogYOffset: number;
}

const WRAPPER_STYLE: CSSProperties = {
  width: "100vw",
  height: "100vh",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  pointerEvents: "none",
};

const WALK_SPEED_PX_PER_SEC = 60;
const CUDDLE_MIN_MS = 10_000;
const CUDDLE_MAX_MS = 25_000;
const BARK_PROBABILITY = 0.15;
const FULL_TRAVERSE_PROBABILITY = 0.12;

// Durations of the "transition" frames between walk and cuddle.
// Each is one full loop of its animation.
const STAND_MS = 1200; // 6 frames @ 5 fps
const SIT_MS = 1500;   // 6 frames @ 4 fps
const LAY_MS = 1500;   // 6 frames @ 4 fps

const TEST_WALK_ONLY: boolean =
  (import.meta.env.VITE_DOG_TEST_WALK as string | undefined) === "1";

type DogVariant =
  | "walk"
  | "walk_bark"
  | "stand"
  | "sit"
  | "lay"
  | "cuddle"
  | "sit_bark"
  | "treat";

interface DogRender {
  variant: DogVariant;
  facingRight: boolean;
}

function pickWalkTarget(currentX: number, bounds: CompanionBounds): number {
  if (Math.random() < FULL_TRAVERSE_PROBABILITY) {
    const mid = (bounds.minX + bounds.maxX) / 2;
    return currentX < mid ? bounds.maxX : bounds.minX;
  }
  const span = bounds.maxX - bounds.minX;
  const hop = span * (0.1 + Math.random() * 0.45);
  const goRight = Math.random() < 0.5;
  const raw = goRight ? currentX + hop : currentX - hop;
  return clamp(raw, bounds.minX, bounds.maxX);
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function monitorsDiffer(a: CompanionBounds | null, b: CompanionBounds): boolean {
  if (!a) return true;
  // Treat as a different monitor if the strip moved by more than the window.
  return (
    Math.abs(a.minX - b.minX) > 10 ||
    Math.abs(a.y - b.y) > 10 ||
    Math.abs(a.monitorWidth - b.monitorWidth) > 10
  );
}

export function Companion() {
  const [manifest, setManifest] = useState<SpriteManifest>(FALLBACK_MANIFEST);
  const [sheetAvailable, setSheetAvailable] = useState<boolean>(false);
  const [companionId, setCompanionId] = useState<string>(
    () => loadSettings().companionId,
  );
  const [dockPosition, setDockPosition] = useState<DockPosition>(
    () => loadSettings().dockPosition,
  );
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [dog, setDog] = useState<DogRender>({
    variant: "cuddle",
    facingRight: false,
  });

  const boundsRef = useRef<CompanionBounds | null>(null);
  const xRef = useRef<number>(0);

  // The selected companion overrides the manifest's sheet image. Frame layout
  // (grid, fps, state→frame maps) is shared across the dog sheets.
  const selectedImage = getCompanion(companionId).image;
  const effectiveManifest: SpriteManifest = { ...manifest, image: selectedImage };

  // Load manifest JSON (frame layout) once.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/sprites/dogs/manifest.json");
        if (!res.ok) {
          console.warn("[companion] manifest fetch", res.status);
          return;
        }
        const m = (await res.json()) as SpriteManifest;
        if (!cancelled) setManifest(m);
        console.info("[companion] manifest loaded");
      } catch (e) {
        console.warn("[companion] manifest fetch failed", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Probe the selected companion's spritesheet whenever it changes.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const probe = await fetch(`/sprites/dogs/${selectedImage}`, { method: "HEAD" });
        const ct = probe.headers.get("content-type") ?? "";
        if (!cancelled) setSheetAvailable(probe.ok && ct.startsWith("image/"));
      } catch (e) {
        if (!cancelled) setSheetAvailable(false);
        console.warn("[companion] sheet probe failed", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedImage]);

  // React to settings changes made in the settings window (and on launch).
  useEffect(() => {
    const unsub = subscribeSettings((s) => {
      setCompanionId(s.companionId);
      setDockPosition(s.dockPosition);
    });
    return unsub;
  }, []);

  // Agent-state SSE — kept for future use; doesn't drive the dog brain.
  useEffect(() => {
    const sub = subscribeAgentState(setAgentState);
    return () => sub.close();
  }, []);

  // Listen for placement changes emitted by the companion context menu.
  useEffect(() => {
    let cancelled = false;
    let unlisten: UnlistenFn | undefined;
    listen<string>("companion:placement", (event) => {
      if (cancelled) return;
      saveDockPosition(event.payload as DockPosition);
    })
      .then((u) => { if (cancelled) u(); else unlisten = u; })
      .catch((e) => console.error("[companion] listen companion:placement failed", e));
    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, []);

  // Dog brain.
  useEffect(() => {
    let cancelled = false;
    let raf = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let mode: "autonomous" | "bark" | "treat" = "autonomous";
    let modeBeforeTreat: "autonomous" | "bark" = "autonomous";
    let unlistenVis: UnlistenFn | undefined;
    let unlistenTreat: UnlistenFn | undefined;

    const clearTimers = (): void => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (timer) clearTimeout(timer);
      timer = undefined;
    };

    const moveTo = (x: number): void => {
      xRef.current = x;
      const b = boundsRef.current;
      if (!b) return;
      void invoke("set_companion_pos", { x, y: b.y }).catch((e: unknown) =>
        console.error("[companion] set_companion_pos failed", e),
      );
    };

    const refreshBounds = async (): Promise<CompanionBounds | null> => {
      try {
        const b = (await invoke("get_companion_bounds", {
          besideDock: dockPosition === "beside-dock",
        })) as CompanionBounds;
        const migrating = monitorsDiffer(boundsRef.current, b);
        boundsRef.current = b;
        if (migrating) {
          const center = b.minX + (b.maxX - b.minX) / 2;
          xRef.current = center;
          void invoke("set_companion_pos", { x: center, y: b.y });
          console.info("[companion] migrated to monitor", {
            minX: b.minX,
            maxX: b.maxX,
            y: b.y,
          });
        }
        return b;
      } catch (e) {
        console.error("[companion] get_companion_bounds failed", e);
        return null;
      }
    };

    const startCuddle = (): void => {
      if (cancelled || mode !== "autonomous") return;
      setDog((d) => ({ variant: "cuddle", facingRight: d.facingRight }));
      const dur = CUDDLE_MIN_MS + Math.random() * (CUDDLE_MAX_MS - CUDDLE_MIN_MS);
      timer = setTimeout(() => void startWalk(), dur);
    };

    const startLayThenCuddle = (): void => {
      if (cancelled || mode !== "autonomous") return;
      setDog((d) => ({ variant: "lay", facingRight: d.facingRight }));
      timer = setTimeout(() => startCuddle(), LAY_MS);
    };

    const startSitThenLay = (): void => {
      if (cancelled || mode !== "autonomous") return;
      setDog((d) => ({ variant: "sit", facingRight: d.facingRight }));
      timer = setTimeout(() => startLayThenCuddle(), SIT_MS);
    };

    const startStandThenSit = (): void => {
      if (cancelled || mode !== "autonomous") return;
      setDog((d) => ({ variant: "stand", facingRight: d.facingRight }));
      timer = setTimeout(() => startSitThenLay(), STAND_MS);
    };

    const startWalk = async (): Promise<void> => {
      if (cancelled || mode !== "autonomous") return;
      const bounds = await refreshBounds();
      if (!bounds) {
        timer = setTimeout(() => void startWalk(), 1000);
        return;
      }
      const startX = xRef.current;

      let targetX: number;
      let bark: boolean;
      if (TEST_WALK_ONLY) {
        const mid = (bounds.minX + bounds.maxX) / 2;
        targetX = startX < mid ? bounds.maxX : bounds.minX;
        bark = false;
      } else {
        targetX = pickWalkTarget(startX, bounds);
        bark = Math.random() < BARK_PROBABILITY;
      }

      const distance = Math.abs(targetX - startX);
      if (distance < 24) {
        if (TEST_WALK_ONLY) {
          targetX = startX === bounds.minX ? bounds.maxX : bounds.minX;
        } else {
          timer = setTimeout(() => startStandThenSit(), 200);
          return;
        }
      }

      const facingRight = targetX > startX;
      setDog({ variant: bark ? "walk_bark" : "walk", facingRight });

      const durMs = (Math.abs(targetX - startX) / WALK_SPEED_PX_PER_SEC) * 1000;
      const startT = performance.now();
      const step = (): void => {
        if (cancelled || mode !== "autonomous") return;
        const t = Math.min(1, (performance.now() - startT) / durMs);
        const x = startX + (targetX - startX) * t;
        moveTo(x);
        if (t < 1) {
          raf = requestAnimationFrame(step);
        } else if (TEST_WALK_ONLY) {
          void startWalk();
        } else {
          startStandThenSit();
        }
      };
      raf = requestAnimationFrame(step);
    };

    // ---- Bark mode (main window open) ---------------------------------
    const enterBarkMode = (): void => {
      mode = "bark";
      clearTimers();
      const facingRight = Math.random() < 0.5;
      setDog({ variant: "sit_bark", facingRight });
      console.info("[companion] enter bark mode");
    };

    const exitBarkMode = (): void => {
      if (mode !== "bark") return;
      mode = "autonomous";
      clearTimers();
      // lay (1 loop) → cuddle → resume walking
      setDog((d) => ({ variant: "lay", facingRight: d.facingRight }));
      timer = setTimeout(() => startCuddle(), LAY_MS);
      console.info("[companion] exit bark mode → lay → cuddle → walk");
    };

    // ---- Treat mode (steak button) ------------------------------------
    const TREAT_FRAMES = 8;
    const TREAT_FPS = 8;
    const TREAT_LOOPS = 2;
    const TREAT_DURATION_MS = (TREAT_FRAMES / TREAT_FPS) * TREAT_LOOPS * 1000;

    const enterTreatMode = (): void => {
      if (cancelled) return;
      if (mode !== "treat") modeBeforeTreat = mode as "autonomous" | "bark";
      mode = "treat";
      clearTimers();
      setDog((d) => ({ variant: "treat", facingRight: d.facingRight }));
      timer = setTimeout(() => {
        if (cancelled) return;
        if (modeBeforeTreat === "bark") {
          mode = "bark";
          enterBarkMode();
        } else {
          mode = "autonomous";
          setDog((d) => ({ variant: "lay", facingRight: d.facingRight }));
          timer = setTimeout(() => startCuddle(), LAY_MS);
        }
      }, TREAT_DURATION_MS);
    };

    // ---- Bootstrap ----------------------------------------------------
    (async () => {
      const bounds = await refreshBounds();
      if (!bounds || cancelled) return;
      const center = bounds.minX + (bounds.maxX - bounds.minX) / 2;
      xRef.current = center;
      moveTo(center);
      console.info("[companion] bounds", bounds, TEST_WALK_ONLY ? "(TEST)" : "");
      if (TEST_WALK_ONLY) {
        void startWalk();
      } else {
        startCuddle();
      }
    })();

    listen<boolean>("main:visibility", (event) => {
      if (cancelled) return;
      if (event.payload) enterBarkMode();
      else exitBarkMode();
    })
      .then((u) => {
        unlistenVis = u;
      })
      .catch((e) => console.error("[companion] listen main:visibility failed", e));

    listen<void>("companion:treat", () => {
      if (cancelled) return;
      enterTreatMode();
    })
      .then((u) => {
        unlistenTreat = u;
      })
      .catch((e) => console.error("[companion] listen companion:treat failed", e));

    return () => {
      cancelled = true;
      clearTimers();
      if (unlistenVis) unlistenVis();
      if (unlistenTreat) unlistenTreat();
    };
  }, [dockPosition]);

  const extras = effectiveManifest.extras ?? {};
  const spec: SpriteFrameSpec =
    extras[dog.variant] ?? effectiveManifest.states[agentState];

  const onClick = (): void => {
    void invoke("toggle_main").catch((e: unknown) =>
      console.error("[companion] toggle_main failed:", e),
    );
  };

  const onContextMenu = (e: React.MouseEvent): void => {
    e.preventDefault();
    void invoke("show_companion_context_menu", {
      besideDock: dockPosition === "beside-dock",
    }).catch((e: unknown) =>
      console.error("[companion] show_companion_context_menu failed", e),
    );
  };

  return (
    <div style={WRAPPER_STYLE}>
      <div style={{ position: "relative", pointerEvents: "none" }}>
        <Sprite
          spec={spec}
          manifest={effectiveManifest}
          sheetAvailable={sheetAvailable}
          fallbackState={agentState}
          mirror={dog.facingRight}
        />
        <div
          style={{
            position: "absolute",
            bottom: 0,
            left: 0,
            right: 0,
            height: "50%",
            cursor: "pointer",
            pointerEvents: "auto",
          }}
          onClick={onClick}
          onContextMenu={onContextMenu}
          role="button"
          aria-label="Irma companion"
        />
      </div>
    </div>
  );
}
