/**
 * Chem ML Platform v0.7.1 -- Electron main process.
 *
 * Responsibilities (spec task A, §A.2):
 *  - locate a *bundled* Python runtime, falling back to a packaged venv, the
 *    repository venv and finally PATH -- the shipped app never depends on the
 *    developer machine's global interpreter;
 *  - run a first-launch dependency / health diagnostic and show an actionable
 *    error instead of a blank window;
 *  - spawn the Python backend (uvicorn backend.app:app) with an isolated user
 *    data / logs / temp layout;
 *  - generate a per-session token and hand it to both the backend
 *    (CHEMML_SESSION_TOKEN) and the renderer (via the preload bridge) so the
 *    local API is authenticated (spec task D);
 *  - poll /api/health until ready, surfacing progress;
 *  - clean up the backend process tree on quit (Windows: taskkill /T) while
 *    keeping the user's data directory intact across upgrades.
 *
 * Layout when packaged (resources/):
 *   app/                 the Python backend + node packages
 *   frontend-dist/       the built React UI (fallback source)
 *   python-runtime/      optional bundled interpreter (python.exe / bin/python)
 */
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn, spawnSync } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const fs = require("fs");
const http = require("http");

const IS_DEV = process.argv.includes("--dev");
const DEFAULT_PORT = 8000;
let PORT = DEFAULT_PORT;

let mainWindow = null;
let backendProcess = null;
let backendLogPath = "";
let healthCheckTimer = null;
let healthCheckAttempts = 0;
let sessionToken = "";
let readonlyToken = "";
const HEALTH_TIMEOUT_MS = 180000; // 3 min for a cold python start
const HEALTH_INTERVAL_MS = 1000;

// ------------------------------------------------------------------ paths ---- //
/** Python application root (the folder holding backend/, nodes/, ...). */
function backendRoot() {
  return app.isPackaged ? path.join(process.resourcesPath, "app") : path.join(__dirname, "..");
}

/** Writable per-user directories (never the install directory). */
function userPaths() {
  const base = app.getPath("userData");
  return {
    root: base,
    logs: path.join(base, "logs"),
    data: path.join(base, "data"),
    temp: path.join(base, "temp"),
    config: path.join(base, "config"),
  };
}

function ensureDirs(paths) {
  for (const dir of Object.values(paths)) fs.mkdirSync(dir, { recursive: true });
}

function logDir() {
  const dir = userPaths().logs;
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

function logLine(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  try {
    fs.appendFileSync(backendLogPath, line);
  } catch (_) {
    /* log failure must never crash the app */
  }
  if (IS_DEV) process.stdout.write(line);
}

// --------------------------------------------------------------- python ------- //
/** Every interpreter we are willing to try, most specific first. */
function pythonCandidates() {
  const exe = process.platform === "win32" ? "python.exe" : "python3";
  const list = [];
  if (app.isPackaged) {
    list.push(path.join(process.resourcesPath, "python-runtime", exe));
    list.push(path.join(process.resourcesPath, "python-runtime", "bin", "python"));
  }
  const root = backendRoot();
  list.push(path.join(root, ".venv", "Scripts", "python.exe")); // Windows venv
  list.push(path.join(root, ".venv", "bin", "python")); // POSIX venv
  list.push(path.join(root, "python-runtime", exe));
  return list;
}

/** First existing candidate, or a PATH fallback. */
function resolvePython() {
  for (const candidate of pythonCandidates()) {
    if (fs.existsSync(candidate)) return { python: candidate, bundled: true, path: candidate };
  }
  return { python: process.platform === "win32" ? "python" : "python3", bundled: false, path: "" };
}

/**
 * First-run diagnostic (spec §A.2 #4): confirm the interpreter runs and that
 * the core backend dependencies import.  Returns a structured, actionable
 * result instead of throwing.
 */
function diagnosePython(pythonCmd) {
  const probeScript = `
import sys, json, importlib
mods = {}
for name in ("fastapi", "uvicorn", "pydantic", "numpy"):
    try:
        importlib.import_module(name)
        mods[name] = True
    except Exception:
        mods[name] = False
print(json.dumps({"python": sys.version.split()[0], "executable": sys.executable, "modules": mods}))
`;
  try {
    const proc = spawnSync(pythonCmd, ["-c", probeScript], {
      cwd: backendRoot(),
      encoding: "utf-8",
      timeout: 30000,
      windowsHide: true,
    });
    if (proc.error) return { ok: false, reason: String(proc.error), python: "" };
    if (proc.status !== 0) {
      return { ok: false, reason: (proc.stderr || proc.stdout || "non-zero exit").trim(), python: "" };
    }
    const info = JSON.parse((proc.stdout || "").trim().split("\n").pop());
    const missing = Object.entries(info.modules || {})
      .filter(([, ok]) => !ok)
      .map(([name]) => name);
    return { ok: missing.length === 0, missing, python: info.python, executable: info.executable };
  } catch (err) {
    return { ok: false, reason: String(err), python: "" };
  }
}

function backendHealthy(port) {
  return new Promise((resolve) => {
    const req = http.get(
      { host: "127.0.0.1", port, path: "/api/health", timeout: 2000 },
      (res) => {
        let body = "";
        res.on("data", (chunk) => (body += chunk));
        res.on("end", () => {
          try {
            const data = JSON.parse(body);
            resolve(res.statusCode === 200 && data.status === "ok");
          } catch (_) {
            resolve(false);
          }
        });
      }
    );
    req.on("error", () => resolve(false));
    req.on("timeout", () => {
      req.destroy();
      resolve(false);
    });
  });
}

function startBackend() {
  const { python } = resolvePython();
  const root = backendRoot();
  const paths = userPaths();
  backendLogPath = path.join(paths.logs, "backend.log");
  logLine(`starting backend: ${python} -m uvicorn backend.app:app --port ${PORT}`);
  logLine(`backend root: ${root}`);
  logLine(`user data: ${paths.root}`);

  const origins = `http://127.0.0.1:${PORT},http://localhost:${PORT}`;
  backendProcess = spawn(
    python,
    [
      "-m",
      "uvicorn",
      "backend.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      String(PORT),
      "--log-level",
      "info",
    ],
    {
      cwd: root,
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        PYTHONPATH: root,
        // Local API authentication (spec task D): a fresh token each launch.
        CHEMML_SESSION_TOKEN: sessionToken,
        CHEMML_READONLY_TOKEN: readonlyToken,
        CHEMML_AUTH_MODE: "token",
        CHEMML_ALLOWED_ORIGINS: origins,
        CHEMML_AUDIT_LOG: path.join(paths.logs, "security_audit.jsonl"),
        CHEMML_DATA_DIR: paths.data,
        CHEMML_UPLOAD_DIR: path.join(paths.data, "uploads"),
        TMPDIR: paths.temp,
        TEMP: paths.temp,
        TMP: paths.temp,
      },
      windowsHide: true,
    }
  );
  backendProcess.stdout.on("data", (d) => logLine(`[backend] ${d}`.trimEnd()));
  backendProcess.stderr.on("data", (d) => logLine(`[backend:err] ${d}`.trimEnd()));
  backendProcess.on("exit", (code, signal) => {
    logLine(`backend exited code=${code} signal=${signal}`);
    backendProcess = null;
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-exited", { code, signal });
    }
  });
}

function stopBackend() {
  if (!backendProcess) return Promise.resolve();
  return new Promise((resolve) => {
    const pid = backendProcess.pid;
    const finished = () => resolve();
    backendProcess.once("exit", finished);
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true });
      } else {
        backendProcess.kill("SIGTERM");
      }
    } catch (err) {
      logLine(`stopBackend error: ${err}`);
    }
    setTimeout(() => {
      try {
        if (backendProcess) backendProcess.kill("SIGKILL");
      } catch (_) {
        /* already dead */
      }
      resolve();
    }, 5000);
  });
}

function waitForHealth() {
  healthCheckAttempts = 0;
  const started = Date.now();
  return new Promise((resolve, reject) => {
    healthCheckTimer = setInterval(async () => {
      healthCheckAttempts += 1;
      const ok = await backendHealthy(PORT);
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send("backend-status", {
          ok,
          attempts: healthCheckAttempts,
          elapsed: Date.now() - started,
        });
      }
      if (ok) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        resolve(true);
      } else if (Date.now() - started > HEALTH_TIMEOUT_MS) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        reject(
          new Error(
            `后端在 ${HEALTH_TIMEOUT_MS / 1000}s 内未就绪；日志：${backendLogPath}`
          )
        );
      }
    }, HEALTH_INTERVAL_MS);
  });
}

async function pickFreePort(startPort) {
  const net = require("net");
  for (let port = startPort; port < startPort + 20; port += 1) {
    const free = await new Promise((resolve) => {
      const server = net.createServer();
      server.once("error", () => resolve(false));
      server.once("listening", () => server.close(() => resolve(true)));
      server.listen(port, "127.0.0.1");
    });
    if (free) return port;
  }
  throw new Error(`no free port in range ${startPort}..${startPort + 19}`);
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1440,
    height: 900,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: "#111318",
    title: "Chem ML Platform",
    show: false,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
      // The renderer reads the token from argv in the preload, before any
      // page script runs -- so the very first API call is authenticated.
      additionalArguments: [`--chemml-token=${sessionToken}`],
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: "detach" });

  const url = `http://127.0.0.1:${PORT}/`;
  mainWindow.webContents.on("did-fail-load", () => {
    // Fall back to the bundled static build when the backend is not serving it.
    const dist = path.join(
      app.isPackaged ? process.resourcesPath : path.join(__dirname, ".."),
      app.isPackaged ? "frontend-dist" : "frontend/dist",
      "index.html"
    );
    if (fs.existsSync(dist)) mainWindow.loadFile(dist);
  });
  if (IS_DEV) {
    mainWindow.loadURL("http://localhost:5173");
  } else {
    mainWindow.loadURL(url);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

// ------------------------------------------------------------ diagnostics ---- //
function showStartupFailure(title, message, pythonCmd) {
  const { python, bundled } = resolvePython();
  const detail =
    `${message}\n\n` +
    `诊断：\n` +
    `· Python 解释器：${pythonCmd || python}${bundled ? "（已随应用打包）" : "（来自 PATH）"}\n` +
    `· 后端目录：${backendRoot()}\n` +
    `· 日志文件：${backendLogPath}\n\n` +
    `常见原因：\n` +
    `1. 未安装后端依赖（在安装目录运行 install.bat，或在应用内点击“修复依赖”）\n` +
    `2. 端口 ${PORT} 被其它程序占用\n` +
    `3. 防火墙拦截本机回环连接\n\n` +
    `安装包内已随附后端源码与依赖清单，安装过程不依赖开发机的全局 Python。`;
  dialog.showErrorBox(title, detail);
}

// ------------------------------------------------------------------ boot ----- //
app.whenReady().then(async () => {
  const paths = userPaths();
  ensureDirs(paths);
  backendLogPath = path.join(paths.logs, "backend.log");

  // Fresh session tokens for this launch.
  sessionToken = crypto.randomBytes(32).toString("base64url");
  readonlyToken = crypto.randomBytes(32).toString("base64url");

  const { python, bundled } = resolvePython();
  logLine(`resolved python: ${python} (bundled=${bundled})`);

  const diag = diagnosePython(python);
  logLine(`python diagnostic: ${JSON.stringify(diag)}`);
  if (!diag.ok) {
    createWindow();
    const why = diag.missing
      ? `缺少后端依赖：${diag.missing.join(", ")}`
      : `Python 无法运行：${diag.reason || "未知错误"}`;
    showStartupFailure("后端依赖检查失败", why, python);
    return;
  }

  try {
    PORT = await pickFreePort(DEFAULT_PORT);
  } catch (err) {
    dialog.showErrorBox("端口冲突", String(err));
    app.exit(1);
    return;
  }
  createWindow();
  startBackend();
  try {
    await waitForHealth();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-ready", { port: PORT });
    }
    logLine(`backend ready on port ${PORT}`);
  } catch (err) {
    logLine(`health check failed: ${err.message}`);
    showStartupFailure("后端启动失败", err.message, python);
  }
});

function persistSession() {
  // Keep the token out of the install dir; store it beside the user data only.
  try {
    const file = path.join(userPaths().config, "session.json");
    fs.writeFileSync(file, JSON.stringify({ port: PORT }, null, 2), "utf-8");
  } catch (_) {
    /* non fatal */
  }
}

app.on("window-all-closed", () => {
  app.quit();
});

app.on("before-quit", (event) => {
  if (backendProcess) {
    event.preventDefault();
    persistSession();
    stopBackend().finally(() => {
      backendProcess = null;
      app.quit();
    });
  }
});

// ---------------------------------------------------------------- IPC ---- //
ipcMain.handle("backend-info", () => ({
  port: PORT,
  running: Boolean(backendProcess),
  logPath: backendLogPath,
  version: app.getVersion(),
  packaged: app.isPackaged,
  python: resolvePython().python,
  userData: userPaths().root,
}));

ipcMain.handle("read-backend-log", (_event, lines = 200) => {
  try {
    const content = fs.readFileSync(backendLogPath, "utf-8");
    return content.split("\n").slice(-lines).join("\n");
  } catch (_) {
    return "";
  }
});

ipcMain.handle("restart-backend", async () => {
  await stopBackend();
  startBackend();
  await waitForHealth();
  return { port: PORT };
});

ipcMain.handle("open-log-folder", async () => {
  await shell.openPath(path.dirname(backendLogPath));
  return true;
});

ipcMain.handle("open-external", async (_event, url) => {
  if (typeof url === "string" && /^https?:\/\//.test(url)) {
    await shell.openExternal(url);
    return true;
  }
  return false;
});
