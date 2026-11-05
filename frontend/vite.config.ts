import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// The dev server forwards /api to the FastAPI backend, so the browser sees one origin (no CORS setup).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: process.env.SCOUTIQ_API ?? "http://localhost:8000", changeOrigin: true } },
  },
  test: { environment: "node" },
});
