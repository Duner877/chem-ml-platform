/**
 * Preload: a minimal, explicitly enumerated IPC surface.
 * contextIsolation stays on; the renderer never gets Node.js powers.
 *
 * v0.7.1 (spec task D): the per-session API token is handed to the renderer
 * through ``contextBridge`` *before* any page script runs, so the very first
 * authenticated request already carries it.  The token is read from the extra
 * command-line argument injected by the main process.
 */
const { contextBridge, ipcRenderer } = require("electron");

function readToken() {
  const prefix = "--chemml-token=";
  const arg = process.argv.find((value) => value.startsWith(prefix));
  return arg ? arg.slice(prefix.length) : "";
}

// Exposed as a plain value in the main world; the REST client reads it.
contextBridge.exposeInMainWorld("__CHEMML_TOKEN__", readToken());

contextBridge.exposeInMainWorld("chemmlDesktop", {
  isDesktop: true,
  backendInfo: () => ipcRenderer.invoke("backend-info"),
  readBackendLog: (lines) => ipcRenderer.invoke("read-backend-log", lines),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLogFolder: () => ipcRenderer.invoke("open-log-folder"),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  onBackendStatus: (cb) => ipcRenderer.on("backend-status", (_e, data) => cb(data)),
  onBackendReady: (cb) => ipcRenderer.on("backend-ready", (_e, data) => cb(data)),
  onBackendExited: (cb) => ipcRenderer.on("backend-exited", (_e, data) => cb(data)),
});
