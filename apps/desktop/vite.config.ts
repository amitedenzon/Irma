import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { resolve } from "node:path";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react(), tailwindcss()],

  // 1. prevent Vite from obscuring Rust errors
  clearScreen: false,
  // 2. Tauri expects a fixed port — fail if unavailable
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },

  // 4. two windows → two HTML entries, both built into ../dist for production
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        companion: resolve(__dirname, "companion.html"),
      },
    },
  },
});
