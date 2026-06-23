import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./main/App";
import { applyTheme, loadSettings } from "./lib/settings";
import "./styles.css";

// Apply persisted theme before first paint.
const { themeId: _initThemeId } = loadSettings();
applyTheme(_initThemeId);

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in index.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
