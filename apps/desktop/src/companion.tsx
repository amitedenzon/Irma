import React from "react";
import { createRoot } from "react-dom/client";
import { Companion } from "./companion/Companion";
import { applyPawCursor, applyPawCursorTheme, loadSettings } from "./lib/settings";
import "./styles.css";

document.body.classList.add("companion");
const { pawCursor: _initPawCursor, themeId: _initThemeId } = loadSettings();
applyPawCursor(_initPawCursor);
applyPawCursorTheme(_initThemeId);

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in companion.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <Companion />
  </React.StrictMode>,
);
