import React from "react";
import { createRoot } from "react-dom/client";
import { Companion } from "./companion/Companion";
import { applyPawCursor, applyPawCursorTheme, loadSettings } from "./lib/settings";
import "./styles.css";

document.body.classList.add("companion");
const _companionSettings = loadSettings();
applyPawCursor(_companionSettings.pawCursor);
applyPawCursorTheme(_companionSettings.themeId);

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in companion.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <Companion />
  </React.StrictMode>,
);
