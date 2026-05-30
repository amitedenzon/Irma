// Client-side user settings, persisted in localStorage and broadcast across the
// `main` and `companion` windows over the Tauri event bus. (The DOM `storage`
// event does NOT fire across separate WKWebView windows, so changes are pushed
// explicitly via `emit`/`listen`.)

import { emit, listen, type UnlistenFn } from "@tauri-apps/api/event";

export type DockPosition = "on-dock" | "beside-dock";

export interface Companion {
  id: string;
  /** Display name — placeholder/random for now; the maintainer will rename. */
  name: string;
  /** Sprite-sheet filename under `/sprites/dogs/`. */
  image: string;
}

// Roster mapped onto the spritesheets that ship in `public/sprites/dogs/`.
// The default sheet (used by the manifest) is the original Irma.
export const COMPANIONS: readonly Companion[] = [
  { id: "irma", name: "Irma (Original)", image: "Irma.png" },
  { id: "lucky", name: "Lucky", image: "Lucky.png" },
  { id: "rio", name: "Rio", image: "Rio.png" },
] as const;

export const DEFAULT_COMPANION_ID: string = COMPANIONS[0].id;
export const DEFAULT_DOCK_POSITION: DockPosition = "beside-dock";

export interface IrmaSettings {
  companionId: string;
  dockPosition: DockPosition;
}

const COMPANION_KEY = "irma.settings.companionId";
const DOCK_KEY = "irma.settings.dockPosition";

/** Tauri event broadcast to every window whenever a setting changes. */
const CHANGE_EVENT = "irma:settings-changed";

export function getCompanion(id: string): Companion {
  return COMPANIONS.find((c) => c.id === id) ?? COMPANIONS[0];
}

function readCompanionId(): string {
  const raw = localStorage.getItem(COMPANION_KEY);
  return raw && COMPANIONS.some((c) => c.id === raw) ? raw : DEFAULT_COMPANION_ID;
}

function readDockPosition(): DockPosition {
  const raw = localStorage.getItem(DOCK_KEY);
  return raw === "on-dock" || raw === "beside-dock" ? raw : DEFAULT_DOCK_POSITION;
}

export function loadSettings(): IrmaSettings {
  return { companionId: readCompanionId(), dockPosition: readDockPosition() };
}

export function saveCompanionId(id: string): void {
  localStorage.setItem(COMPANION_KEY, id);
  void emit(CHANGE_EVENT, loadSettings());
}

export function saveDockPosition(position: DockPosition): void {
  localStorage.setItem(DOCK_KEY, position);
  void emit(CHANGE_EVENT, loadSettings());
}

/**
 * Subscribe to settings changes broadcast (from any window) over the Tauri
 * event bus. Returns an unsubscribe function.
 */
export function subscribeSettings(cb: (settings: IrmaSettings) => void): () => void {
  let unlisten: UnlistenFn | undefined;
  let cancelled = false;
  void listen<IrmaSettings>(CHANGE_EVENT, (event) => cb(event.payload)).then((u) => {
    if (cancelled) u();
    else unlisten = u;
  });
  return () => {
    cancelled = true;
    if (unlisten) unlisten();
  };
}
