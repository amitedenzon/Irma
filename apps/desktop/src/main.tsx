import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./main/App";
import { applyTheme, applyPawCursor, applyPawCursorTheme, loadSettings } from "./lib/settings";
import "./styles.css";

// Apply persisted theme and cursor before first paint.
const _settings = loadSettings();
applyTheme(_settings.themeId);
applyPawCursor(_settings.pawCursor);
applyPawCursorTheme(_settings.themeId);

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in index.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
