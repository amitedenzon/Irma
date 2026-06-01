import React from "react";
import { createRoot } from "react-dom/client";
import { Companion } from "./companion/Companion";
import "./styles.css";

document.body.classList.add("companion");

const rootEl = document.getElementById("root");
if (!rootEl) throw new Error("root element missing in companion.html");

createRoot(rootEl).render(
  <React.StrictMode>
    <Companion />
  </React.StrictMode>,
);
