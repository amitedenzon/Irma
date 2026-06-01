// Client-side user settings, persisted in localStorage and broadcast across the
// `main` and `companion` windows over the Tauri event bus. (The DOM `storage`
// event does NOT fire across separate WKWebView windows, so changes are pushed
// explicitly via `emit`/`listen`.)

import { emit, listen, type UnlistenFn } from "@tauri-apps/api/event";

export type DockPosition = "on-dock" | "left-of-dock" | "right-of-dock";

export type ThemeId = "warm" | "dark" | "ocean" | "forest" | "midnight" | "rose";

export interface ThemeDef {
  id: ThemeId;
  label: string;
  bg: string;
  surface: string;
  surface2: string;
  border: string;
  borderStrong: string;
  ink: string;
  inkMute: string;
  inkFaint: string;
  accent: string;
  accentHover: string;
  accentDeep: string;
  amber: string;
  moss: string;
}

export const THEMES: readonly ThemeDef[] = [
  {
    id: "warm",
    label: "Warm Paper",
    bg: "#f5ece0", surface: "#fdfaf4", surface2: "#efe5d4",
    border: "#e0d0b3", borderStrong: "#c2b08c",
    ink: "#2a1f17", inkMute: "#7a6a52", inkFaint: "#a8967a",
    accent: "#b8341c", accentHover: "#d4543a", accentDeep: "#8a3a14",
    amber: "#c98a1a", moss: "#5a6b3a",
  },
  {
    id: "dark",
    label: "Dark",
    bg: "#1a1a1a", surface: "#242424", surface2: "#2e2e2e",
    border: "#3a3a3a", borderStrong: "#555555",
    ink: "#e8e8e8", inkMute: "#999999", inkFaint: "#666666",
    accent: "#e05c3a", accentHover: "#f07050", accentDeep: "#c04020",
    amber: "#e0a030", moss: "#6a8a4a",
  },
  {
    id: "midnight",
    label: "Midnight Blue",
    bg: "#0f1520", surface: "#161e2e", surface2: "#1e2840",
    border: "#2a3550", borderStrong: "#3d4f70",
    ink: "#dce8ff", inkMute: "#7a92bb", inkFaint: "#4a5f85",
    accent: "#4d9de0", accentHover: "#6ab2f0", accentDeep: "#2a7ac0",
    amber: "#e0b840", moss: "#4aaa70",
  },
  {
    id: "ocean",
    label: "Ocean",
    bg: "#e8f4f8", surface: "#f2fafc", surface2: "#d8eef5",
    border: "#b8dce8", borderStrong: "#80bcd0",
    ink: "#0d2d3a", inkMute: "#3a6a80", inkFaint: "#7aabbb",
    accent: "#0a7a9a", accentHover: "#0a9abf", accentDeep: "#085a75",
    amber: "#d4a020", moss: "#2a8a60",
  },
  {
    id: "forest",
    label: "Forest",
    bg: "#edf2e8", surface: "#f5f9f2", surface2: "#deebd6",
    border: "#c2d8b0", borderStrong: "#90b878",
    ink: "#1a2d14", inkMute: "#4a6a3a", inkFaint: "#80a068",
    accent: "#3a7a2a", accentHover: "#4a9a38", accentDeep: "#285a1e",
    amber: "#c8960a", moss: "#5a8040",
  },
  {
    id: "rose",
    label: "Rose",
    bg: "#fdf0f2", surface: "#fff5f7", surface2: "#fae0e4",
    border: "#f0c0ca", borderStrong: "#e090a0",
    ink: "#2d1018", inkMute: "#8a4055", inkFaint: "#c08090",
    accent: "#c0305a", accentHover: "#e04070", accentDeep: "#902045",
    amber: "#d4800a", moss: "#507a40",
  },
] as const;

export const DEFAULT_THEME_ID: ThemeId = "warm";

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
  { id: "irma",    name: "Irma (Original)", image: "Irma.png" },
  { id: "lucky",   name: "Lucky",           image: "Lucky.png" },
  { id: "rio",     name: "Rio",             image: "Rio.png" },
] as const;

export const DEFAULT_COMPANION_ID: string = COMPANIONS[0].id;
export const DEFAULT_DOCK_POSITION: DockPosition = "left-of-dock";

export interface IrmaSettings {
  companionId: string;
  dockPosition: DockPosition;
  monitorName: string | null;
  themeId: ThemeId;
  pawCursor: boolean;
}

const COMPANION_KEY = "irma.settings.companionId";
const DOCK_KEY = "irma.settings.dockPosition";
const MONITOR_KEY = "irma.settings.monitorName";
const THEME_KEY = "irma.settings.themeId";
const PAW_CURSOR_KEY = "irma.settings.pawCursor";

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
  if (raw === "beside-dock") return "left-of-dock"; // migrate legacy value
  return raw === "on-dock" || raw === "left-of-dock" || raw === "right-of-dock"
    ? raw
    : DEFAULT_DOCK_POSITION;
}

function readMonitorName(): string | null {
  const raw = localStorage.getItem(MONITOR_KEY);
  return raw && raw.length > 0 ? raw : null;
}

function readThemeId(): ThemeId {
  const raw = localStorage.getItem(THEME_KEY);
  return THEMES.some((t) => t.id === raw) ? (raw as ThemeId) : DEFAULT_THEME_ID;
}

function readPawCursor(): boolean {
  return localStorage.getItem(PAW_CURSOR_KEY) === "true";
}

export function loadSettings(): IrmaSettings {
  return {
    companionId: readCompanionId(),
    dockPosition: readDockPosition(),
    monitorName: readMonitorName(),
    themeId: readThemeId(),
    pawCursor: readPawCursor(),
  };
}

export function savePawCursor(enabled: boolean): void {
  localStorage.setItem(PAW_CURSOR_KEY, enabled ? "true" : "false");
  applyPawCursor(enabled);
  void emit(CHANGE_EVENT, loadSettings());
}

// Light themes use dark paws (contrast), dark themes use white paws
const DARK_THEMES: readonly string[] = ["warm", "ocean", "forest", "rose"];

function isDarkTheme(id: string): boolean {
  return DARK_THEMES.includes(id);
}

export function applyPawCursor(enabled: boolean): void {
  document.documentElement.classList.toggle("paw-cursor", enabled);
  // Remove stale paw-clicking class if it got stuck from a previous session
  document.documentElement.classList.remove("paw-clicking");
}

export function applyPawCursorTheme(themeId: string): void {
  document.documentElement.classList.toggle("paw-dark", isDarkTheme(themeId));
}

/** Apply a theme's CSS variables to the document root immediately. */
export function applyTheme(id: ThemeId): void {
  const t = THEMES.find((th) => th.id === id) ?? THEMES[0];
  const root = document.documentElement;
  root.style.setProperty("--color-bg", t.bg);
  root.style.setProperty("--color-surface", t.surface);
  root.style.setProperty("--color-surface-2", t.surface2);
  root.style.setProperty("--color-border", t.border);
  root.style.setProperty("--color-border-strong", t.borderStrong);
  root.style.setProperty("--color-ink", t.ink);
  root.style.setProperty("--color-ink-mute", t.inkMute);
  root.style.setProperty("--color-ink-faint", t.inkFaint);
  root.style.setProperty("--color-red", t.accent);
  root.style.setProperty("--color-red-hover", t.accentHover);
  root.style.setProperty("--color-red-deep", t.accentDeep);
  root.style.setProperty("--color-amber", t.amber);
  root.style.setProperty("--color-moss", t.moss);
  // Dark themes need a dark body bg too
  document.body.style.background = t.bg;
}

export function saveTheme(id: ThemeId): void {
  localStorage.setItem(THEME_KEY, id);
  applyTheme(id);
  applyPawCursorTheme(id);
  void emit(CHANGE_EVENT, loadSettings());
}

export function saveCompanionId(id: string): void {
  localStorage.setItem(COMPANION_KEY, id);
  void emit(CHANGE_EVENT, loadSettings());
}

// Zone-only change (the Settings UI): monitorName is intentionally left
// unchanged — the zone changes on whichever monitor she currently lives on.
export function saveDockPosition(position: DockPosition): void {
  localStorage.setItem(DOCK_KEY, position);
  void emit(CHANGE_EVENT, loadSettings());
}

/**
 * Persist a full placement (monitor + zone) — used by drag-drop and reset.
 * A null/empty monitorName means "primary monitor".
 */
export function saveCompanionPlacement(
  monitorName: string | null,
  dockPosition: DockPosition,
): void {
  if (monitorName && monitorName.length > 0) {
    localStorage.setItem(MONITOR_KEY, monitorName);
  } else {
    localStorage.removeItem(MONITOR_KEY);
  }
  localStorage.setItem(DOCK_KEY, dockPosition);
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
