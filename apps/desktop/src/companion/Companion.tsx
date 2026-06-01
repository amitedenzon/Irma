import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen, type UnlistenFn } from "@tauri-apps/api/event";
import type { AgentState, SpriteFrameSpec, SpriteManifest } from "../lib/types";
import { subscribeAgentState } from "../lib/sse";
import {
  getCompanion,
  loadSettings,
  saveCompanionPlacement,
  subscribeSettings,
  applyPawCursor,
  applyPawCursorTheme,
  DEFAULT_DOCK_POSITION,
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
    treat_partial: { frames: [56, 57, 58, 59, 60, 61], fps: 8, loop: true },
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
  | "treat"
  | "treat_partial";

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
  const [monitorName, setMonitorName] = useState<string | null>(
    () => loadSettings().monitorName,
  );
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [dog, setDog] = useState<DogRender>({
    variant: "cuddle",
    facingRight: false,
  });

  const boundsRef = useRef<CompanionBounds | null>(null);
  const xRef = useRef<number>(0);
  const draggingRef = useRef<boolean>(false);
  const [cheeseDropTarget, setCheeseDropTarget] = useState(false);
  const startXRef = useRef<number | null>(null);
  const pressRef = useRef<{
    screenX: number;
    screenY: number;
    moved: boolean;
  } | null>(null);
  const [placementVersion, setPlacementVersion] = useState<number>(0);

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
      setMonitorName(s.monitorName);
      applyPawCursor(s.pawCursor);
      applyPawCursorTheme(s.themeId);
    });
    return unsub;
  }, []);

  // Agent-state SSE — kept for future use; doesn't drive the dog brain.
  useEffect(() => {
    const sub = subscribeAgentState(setAgentState);
    return () => sub.close();
  }, []);

  // Reset placement to the primary-monitor default (tray / right-click).
  useEffect(() => {
    let cancelled = false;
    let unlisten: UnlistenFn | undefined;
    listen<void>("companion:reset-position", () => {
      if (cancelled) return;
      saveCompanionPlacement(null, DEFAULT_DOCK_POSITION);
      void invoke("position_companion").catch((e: unknown) =>
        console.error("[companion] position_companion failed", e),
      );
    })
      .then((u) => {
        if (cancelled) u();
        else unlisten = u;
      })
      .catch((e) => console.error("[companion] listen companion:reset-position failed", e));
    return () => {
      cancelled = true;
      if (unlisten) unlisten();
    };
  }, []);

  // Re-anchor to her saved placement after a DPI/scale change — unless a drag is
  // in progress (the drag owns her position while crossing monitors). Bumping
  // placementVersion re-bootstraps the brain, which re-derives bounds for the
  // saved monitor/zone via refreshBounds.
  useEffect(() => {
    let cancelled = false;
    let unlisten: UnlistenFn | undefined;
    listen<void>("companion:rescale", () => {
      if (cancelled || draggingRef.current) return;
      setPlacementVersion((v) => v + 1);
    })
      .then((u) => {
        if (cancelled) u();
        else unlisten = u;
      })
      .catch((e) => console.error("[companion] listen companion:rescale failed", e));
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
    let unlistenTreat: UnlistenFn | undefined;

    const clearTimers = (): void => {
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
      if (timer) clearTimeout(timer);
      timer = undefined;
    };

    const moveTo = (x: number): void => {
      if (draggingRef.current) return;
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
          monitorName,
          dockPosition,
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
        if (cancelled || mode !== "autonomous" || draggingRef.current) return;
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
      if (draggingRef.current) return;
      mode = "bark";
      clearTimers();
      const facingRight = Math.random() < 0.5;
      setDog({ variant: "sit_bark", facingRight });
      console.info("[companion] enter bark mode");
    };

    const exitBarkMode = (): void => {
      // Also cancel treat mid-sequence — window closed while cheese animation played.
      if (mode !== "bark" && mode !== "treat") return;
      mode = "autonomous";
      clearTimers();
      // lay (1 loop) → cuddle → resume walking
      setDog((d) => ({ variant: "lay", facingRight: d.facingRight }));
      timer = setTimeout(() => startCuddle(), LAY_MS);
      console.info("[companion] exit bark mode → lay → cuddle → walk");
    };

    // ---- Treat mode (cheese button) ------------------------------------
    // Sequence: 2 full treat cycles → 6-frame treat cycle → 1 stand cycle → sit_bark
    const TREAT_FULL_MS  = (8 / 8) * 2 * 1000; // 2000ms — 2 × 8 frames @ 8 fps
    const TREAT_SHORT_MS = (6 / 8) * 1000;       //  750ms — 6 frames @ 8 fps
    // STAND_MS (1200ms) is already defined above: 6 frames @ 5 fps

    const enterTreatMode = (): void => {
      if (cancelled) return;
      mode = "treat";
      clearTimers();

      // Phase 1 — 2 full treat loops
      setDog((d) => ({ variant: "treat", facingRight: d.facingRight }));

      timer = setTimeout(() => {
        if (cancelled || mode !== "treat") return;
        // Phase 2 — first 6 frames of treat (no tail frames)
        setDog((d) => ({ variant: "treat_partial", facingRight: d.facingRight }));

        timer = setTimeout(() => {
          if (cancelled || mode !== "treat") return;
          // Phase 3 — one full standing cycle
          setDog((d) => ({ variant: "stand", facingRight: d.facingRight }));

          timer = setTimeout(() => {
            if (cancelled) return;
            // Phase 4 — sit and bark
            mode = "bark";
            setDog((d) => ({ variant: "sit_bark", facingRight: d.facingRight }));
          }, STAND_MS);
        }, TREAT_SHORT_MS);
      }, TREAT_FULL_MS);
    };

    // ---- Bootstrap ----------------------------------------------------
    (async () => {
      draggingRef.current = false;
      const bounds = await refreshBounds();
      if (!bounds || cancelled) return;
      const fallbackCenter = bounds.minX + (bounds.maxX - bounds.minX) / 2;
      // startXRef is the drop landing-x handed off by onPointerUp; consume it
      // once (clear below) so a later non-drop re-boot falls back to center.
      const startX = clamp(
        startXRef.current ?? fallbackCenter,
        bounds.minX,
        bounds.maxX,
      );
      startXRef.current = null;
      xRef.current = startX;
      moveTo(startX);
      console.info("[companion] bounds", bounds, TEST_WALK_ONLY ? "(TEST)" : "");
      if (TEST_WALK_ONLY) {
        void startWalk();
      } else {
        startCuddle();
      }
    })();

    listen<void>("companion:treat", () => {
      if (cancelled) return;
      enterTreatMode();
    })
      .then((u) => { unlistenTreat = u; })
      .catch((e) => console.error("[companion] listen companion:treat failed", e));

    // Cheese drag-and-drop: glow when user is dragging cheese toward us
    listen<void>("cheese:drag-start", () => {
      if (cancelled) return;
      setCheeseDropTarget(true);
    }).catch(() => {});
    listen<void>("cheese:drag-end", () => {
      if (cancelled) return;
      setCheeseDropTarget(false);
    }).catch(() => {});

    // Poll whether the main window is actually presented to the user every
    // 250 ms. We key off "active" (visible AND focused), not just "visible":
    // a window that's merely on-screen but behind another app (the user
    // clicked away) must still calm the dog. `is_main_active` returns false
    // the moment the window loses key focus — except while our own folder
    // picker is up — so she leaves bark mode no matter how the window is
    // dismissed (X, companion, tray, app-switch, hide, …).
    const visibilityPoll = setInterval(() => {
      void invoke<boolean>("is_main_active").then((active) => {
        if (cancelled) return;
        if (active && mode === "autonomous") enterBarkMode();
        else if (!active && (mode === "bark" || mode === "treat")) exitBarkMode();
      });
    }, 250);

    return () => {
      cancelled = true;
      clearTimers();
      clearInterval(visibilityPoll);
      if (unlistenTreat) unlistenTreat();
    };
  }, [dockPosition, monitorName, placementVersion]);

  const extras = effectiveManifest.extras ?? {};
  const spec: SpriteFrameSpec =
    extras[dog.variant] ?? effectiveManifest.states[agentState];

  const DRAG_THRESHOLD = 4;

  const onPointerDown = (e: React.PointerEvent): void => {
    if (e.button !== 0) return; // primary button only
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    pressRef.current = { screenX: e.screenX, screenY: e.screenY, moved: false };
  };

  const onPointerMove = (e: React.PointerEvent): void => {
    const p = pressRef.current;
    if (!p) return;
    if (!p.moved) {
      const dist = Math.hypot(e.screenX - p.screenX, e.screenY - p.screenY);
      if (dist < DRAG_THRESHOLD) return;
      p.moved = true;
      draggingRef.current = true; // suspend the dog brain's movement
      void invoke("companion_drag_begin").catch((err: unknown) =>
        console.error("[companion] companion_drag_begin failed", err),
      );
    }
    void invoke("companion_drag_to").catch((err: unknown) =>
      console.error("[companion] companion_drag_to failed", err),
    );
  };

  const onPointerUp = (e: React.PointerEvent): void => {
    const p = pressRef.current;
    pressRef.current = null;
    try {
      (e.target as HTMLElement).releasePointerCapture(e.pointerId);
    } catch {
      /* capture may already be released */
    }
    if (!p) return;
    if (!p.moved) {
      // A click (no meaningful movement) → toggle the main window.
      void invoke("toggle_main").catch((err: unknown) =>
        console.error("[companion] toggle_main failed:", err),
      );
      return;
    }
    // A drag → resolve the snap, apply it, persist, and resume roaming.
    void (async () => {
      try {
        const drop = (await invoke("resolve_companion_drop")) as {
          monitorName: string;
          dockPosition: DockPosition;
          x: number;
          bounds: CompanionBounds;
        };
        // Normalize "" → null so it matches what readMonitorName() will later
        // report; otherwise the async settings-changed event would re-set a
        // different value and trigger a redundant second re-bootstrap.
        const nextMonitor =
          drop.monitorName.length > 0 ? drop.monitorName : null;
        boundsRef.current = drop.bounds;
        startXRef.current = drop.x;
        await invoke("set_companion_pos", { x: drop.x, y: drop.bounds.y });
        draggingRef.current = false;
        saveCompanionPlacement(nextMonitor, drop.dockPosition);
        // Apply locally AND bump the version in one batch so the brain re-boots
        // exactly once (reading startXRef before it's cleared). The cross-window
        // settings event that saveCompanionPlacement fires then re-sets these
        // same values → no-op, no second re-bootstrap.
        setMonitorName(nextMonitor);
        setDockPosition(drop.dockPosition);
        setPlacementVersion((v) => v + 1);
      } catch (err) {
        console.error("[companion] resolve_companion_drop failed", err);
        draggingRef.current = false;
      }
    })();
  };

  const onContextMenu = (e: React.MouseEvent): void => {
    e.preventDefault();
    void invoke("show_companion_context_menu").catch((err: unknown) =>
      console.error("[companion] show_companion_context_menu failed", err),
    );
  };

  return (
    <div style={WRAPPER_STYLE}>
      <div style={{
        position: "relative",
        pointerEvents: "none",
        filter: cheeseDropTarget
          ? "drop-shadow(0 0 12px gold) drop-shadow(0 0 6px orange)"
          : "none",
        transition: "filter 0.2s ease",
      }}>
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
            touchAction: "none",
          }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onContextMenu={onContextMenu}
          role="button"
          aria-label="Irma companion"
        />
      </div>
    </div>
  );
}
