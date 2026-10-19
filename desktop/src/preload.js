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
  runtimeDiagnosis: () => ipcRenderer.invoke("runtime-diagnosis"),
  readBackendLog: (lines) => ipcRenderer.invoke("read-backend-log", lines),
  restartBackend: () => ipcRenderer.invoke("restart-backend"),
  openLogFolder: () => ipcRenderer.invoke("open-log-folder"),
  openExternal: (url) => ipcRenderer.invoke("open-external", url),
  // Custom window chrome: min / max / close driven by the web top bar.
  windowControl: (action) => ipcRenderer.invoke("window-control", action),
  windowState: () => ipcRenderer.invoke("window-state"),
  // v0.7.2: native file picker for `file` typed node parameters.  The dialog
  // is raised in the main process; only the chosen absolute path comes back.
  pickFile: (options) => ipcRenderer.invoke("pick-file", options || {}),
  onBackendStatus: (cb) => ipcRenderer.on("backend-status", (_e, data) => cb(data)),
  onBackendReady: (cb) => ipcRenderer.on("backend-ready", (_e, data) => cb(data)),
  onBackendExited: (cb) => ipcRenderer.on("backend-exited", (_e, data) => cb(data)),
  // v0.7.2 (spec P0-02): classified startup failures and runtime state.
  onBackendFailure: (cb) => ipcRenderer.on("backend-failure", (_e, data) => cb(data)),
  onBackendRestarting: (cb) => ipcRenderer.on("backend-restarting", (_e, data) => cb(data)),
  onRuntimeDiagnosis: (cb) => ipcRenderer.on("runtime-diagnosis", (_e, data) => cb(data)),
  onPortInfo: (cb) => ipcRenderer.on("port-info", (_e, data) => cb(data)),
  // v0.7.3: "follow the system" needs the *shell's* idea of the OS
  // appearance.  The renderer's `prefers-color-scheme` usually agrees, but on
  // some Windows builds it only re-evaluates when something forces it, so the
  // main process mirrors `nativeTheme` here as an authoritative second signal.
  systemTheme: () => ipcRenderer.invoke("system-theme"),
  onSystemThemeChange: (cb) => ipcRenderer.on("system-theme-changed", (_e, data) => cb(data)),
});
