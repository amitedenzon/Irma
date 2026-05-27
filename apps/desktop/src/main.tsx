import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./main/App";
import "./styles.css";

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in index.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
