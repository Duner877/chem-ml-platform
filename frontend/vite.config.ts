import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const BACKEND = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

/**
 * Single source of truth for the version (spec task P0-04).
 *
 * The frontend must not carry its own version literal: it did in v0.7.1, and it
 * drifted.  We read `chemml_version.py` directly instead of `package.json` so
 * the browser bundle, the API banner and the release report can never disagree.
 */
function platformVersion(): string {
  try {
    const src = readFileSync(resolve(__dirname, "..", "chemml_version.py"), "utf-8");
    const m = /^__version__\s*=\s*"([^"]+)"/m.exec(src);
    if (m) return m[1];
  } catch {
    /* fall through */
  }
  try {
    return JSON.parse(readFileSync(resolve(__dirname, "package.json"), "utf-8")).version;
  } catch {
    return "0.0.0";
  }
}

export default defineConfig({
  plugins: [react()],
  define: {
    __CHEMML_VERSION__: JSON.stringify(platformVersion()),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target: BACKEND,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    target: "es2020",
  },
});
