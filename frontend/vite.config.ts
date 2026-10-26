/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, Vite proxies /api (REST + WebSocket) and /healthz to the
// backend, mirroring what nginx does in the container. Override the target
// with MARKETLAB_BACKEND_URL.
const backend = process.env.MARKETLAB_BACKEND_URL ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: backend, ws: true, changeOrigin: true },
      "/healthz": { target: backend, changeOrigin: true },
    },
  },
  build: { outDir: "dist", sourcemap: false },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
