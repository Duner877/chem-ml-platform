/**
 * Chem ML Platform v0.7.2 -- Electron main process (spec task P0-02).
 *
 * v0.7.1 could start on a developer machine but the task book found it could
 * not demonstrably start on a clean one: it validated four packages, waited the
 * full three minutes even when the backend had already crashed, and surfaced
 * every problem as the same generic dialog.
 *
 * What this version does instead:
 *  - validates the **whole declared runtime dependency set** via
 *    `runtime-probe.js` before spawning anything;
 *  - classifies every failure into a stable code the UI can act on
 *    (`install_failure` / `runtime_missing` / `dependency_missing` /
 *    `port_conflict` / `backend_timeout` / `backend_crashed` /
 *    `backend_unstable`), instead of one catch-all message;
 *  - fails fast when the backend process **exits** during startup, rather than
 *    waiting out the health timeout;
 *  - honours a configurable start timeout (`CHEMML_START_TIMEOUT_MS`);
 *  - handles port conflicts by detecting whether the occupant is another Chem
 *    ML instance, then moving to a free port and reporting it;
 *  - restarts an unexpectedly dead backend with bounded backoff, and stops
 *    pretending after the budget is spent;
 *  - guarantees the child process tree is terminated on quit paths
 *    (`before-quit`, `will-quit`, `process.exit`) so no orphan holds the port;
 *  - keeps user data, logs, temp and config strictly under `app.getPath("userData")`
 *    and never writes into the install directory.
 *
 * Packaging: see `docs/V07_2_DESKTOP_RUNTIME.md` for the runtime strategy,
 * supported platforms, data-retention policy and the clean-VM test record.
 */
const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const { spawn } = require("child_process");
const crypto = require("crypto");
const path = require("path");
const fs = require("fs");
const http = require("http");
const net = require("net");

const runtimeProbe = require("./runtime-probe");

const IS_DEV = process.argv.includes("--dev");
const DEFAULT_PORT = 8000;
const PORT_SCAN_RANGE = 20;
const HEALTH_INTERVAL_MS = 1000;
const START_TIMEOUT_MS = Number(process.env.CHEMML_START_TIMEOUT_MS || 180000);
const MAX_AUTO_RESTARTS = 3;
const RESTART_BACKOFF_MS = [2000, 5000, 10000];

/** Stable failure codes. The renderer switches on these, not on prose. */
const FAILURE = Object.freeze({
  INSTALL: "install_failure",
  RUNTIME_MISSING: "runtime_missing",
  DEPENDENCY_MISSING: "dependency_missing",
  PORT_CONFLICT: "port_conflict",
  BACKEND_TIMEOUT: "backend_timeout",
  BACKEND_CRASHED: "backend_crashed",
  BACKEND_UNSTABLE: "backend_unstable",
});

let PORT = DEFAULT_PORT;
let mainWindow = null;
let backendProcess = null;
let backendLogPath = "";
let healthCheckTimer = null;
let healthCheckAttempts = 0;
let sessionToken = "";
let readonlyToken = "";
let runtimeDiagnosis = null;
let portConflict = null;
let restartCount = 0;
/** Set while we intend the backend to die (quit / explicit restart). */
let shuttingDown = false;

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

function logLine(message) {
  const line = `[${new Date().toISOString()}] ${message}\n`;
  try {
    if (!backendLogPath) {
      const dir = userPaths().logs;
      fs.mkdirSync(dir, { recursive: true });
      backendLogPath = path.join(dir, "backend.log");
    }
    fs.appendFileSync(backendLogPath, line);
  } catch (_) {
    /* log failure must never crash the app */
  }
  if (IS_DEV) process.stdout.write(line);
}

/** Last N lines of the backend log, for failure dialogs. */
function tailLog(lines = 40) {
  try {
    const content = fs.readFileSync(backendLogPath, "utf-8");
    return content.split("\n").slice(-lines).join("\n");
  } catch (_) {
    return "(日志尚不可读)";
  }
}

// ------------------------------------------------------------ http helpers ---- //
function getJson(port, urlPath, timeoutMs = 2000) {
  return new Promise((resolve) => {
    const req = http.get({ host: "127.0.0.1", port, path: urlPath, timeout: timeoutMs }, (res) => {
      let body = "";
      res.on("data", (chunk) => (body += chunk));
      res.on("end", () => {
        try {
          resolve({ status: res.statusCode, data: JSON.parse(body) });
        } catch (_) {
          resolve({ status: res.statusCode, data: null });
        }
      });
    });
    req.on("error", () => resolve({ status: 0, data: null }));
    req.on("timeout", () => {
      req.destroy();
      resolve({ status: 0, data: null });
    });
  });
}

async function backendHealthy(port) {
  const { status, data } = await getJson(port, "/api/health");
  return status === 200 && data && data.status === "ok";
}

/** Is this port answerable, and if so, is it another Chem ML instance? */
async function inspectPort(port) {
  const occupied = await new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => server.close(() => resolve(false)));
    server.listen(port, "127.0.0.1");
  });
  if (!occupied) return { occupied: false, ours: false, product: "" };
  const { data } = await getJson(port, "/api/health");
  const product = (data && data.product) || "";
  const ours = Boolean(data && data.status === "ok" && /chem/i.test(product || "chemml"));
  return { occupied: true, ours, product: product || "(非 Chem ML Platform 服务)" };
}

async function pickFreePort(startPort) {
  for (let port = startPort; port < startPort + PORT_SCAN_RANGE; port += 1) {
    const free = await new Promise((resolve) => {
      const server = net.createServer();
      server.once("error", () => resolve(false));
      server.once("listening", () => server.close(() => resolve(true)));
      server.listen(port, "127.0.0.1");
    });
    if (free) return port;
  }
  return 0;
}

// ------------------------------------------------------------- diagnostics ---- //
function send(channel, payload) {
  if (mainWindow && !mainWindow.isDestroyed()) mainWindow.webContents.send(channel, payload);
}

/**
 * Report a startup failure with a stable code, the evidence that produced it,
 * and actionable guidance.  Never a bare "something went wrong".
 */
function reportFailure(code, summary, guidance, extra = {}) {
  const payload = {
    code,
    summary,
    guidance,
    version: app.getVersion(),
    python: (runtimeDiagnosis && runtimeDiagnosis.pythonCommand) || "",
    pythonVersion: (runtimeDiagnosis && runtimeDiagnosis.python && runtimeDiagnosis.python.version) || "",
    backendRoot: backendRoot(),
    userData: userPaths().root,
    logPath: backendLogPath,
    logTail: tailLog(40),
    ...extra,
  };
  logLine(`STARTUP FAILURE ${code}: ${summary}`);
  send("backend-failure", payload);
  const detail =
    `${summary}\n\n` +
    `故障代码：${code}\n` +
    `· 版本：v${payload.version}\n` +
    `· Python：${payload.python || "（未解析）"} ${payload.pythonVersion}\n` +
    `· 后端目录：${payload.backendRoot}\n` +
    `· 用户数据：${payload.userData}\n` +
    `· 日志：${payload.logPath}\n\n` +
    `处理建议：\n` +
    (guidance.length ? guidance.map((g, i) => `${i + 1}. ${g}`).join("\n") : "（无）") +
    `\n\n最近日志：\n${payload.logTail.split("\n").slice(-12).join("\n")}`;
  dialog.showErrorBox("Chem ML Platform 启动失败", detail);
  return payload;
}

// ---------------------------------------------------------------- backend ----- //
function startBackend() {
  const root = backendRoot();
  const paths = userPaths();
  backendLogPath = path.join(paths.logs, "backend.log");
  const python = (runtimeDiagnosis && runtimeDiagnosis.pythonCommand) || "python";

  logLine(`starting backend: ${python} -m uvicorn backend.app:app --port ${PORT}`);
  logLine(`backend root: ${root}`);
  logLine(`user data: ${paths.root}`);
  if (portConflict) logLine(`port conflict noted: ${JSON.stringify(portConflict)}`);

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
        // Local API authentication (spec P0-01): a fresh token each launch.
        CHEMML_SESSION_TOKEN: sessionToken,
        CHEMML_READONLY_TOKEN: readonlyToken,
        CHEMML_AUTH_MODE: "token",
        CHEMML_ENV: IS_DEV ? "dev" : "release",
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
  backendProcess.on("error", (err) => {
    logLine(`backend spawn error: ${err}`);
  });
  backendProcess.on("exit", (code, signal) => {
    logLine(`backend exited code=${code} signal=${signal}`);
    const wasIntentional = shuttingDown;
    backendProcess = null;
    send("backend-exited", { code, signal, intentional: wasIntentional });
    if (!wasIntentional) scheduleRestart(code, signal);
  });
  return backendProcess;
}

/** Bounded automatic restart with backoff -- and an honest stop after that. */
function scheduleRestart(code, signal) {
  if (restartCount >= MAX_AUTO_RESTARTS) {
    reportFailure(
      FAILURE.BACKEND_UNSTABLE,
      `后端在本次会话中已异常退出 ${restartCount + 1} 次，已停止自动重启。`,
      [
        "查看日志中的最后错误堆栈定位原因。",
        `确认端口 ${PORT} 未被其它程序占用。`,
        "在应用安装目录执行 install.bat 重新校验依赖。",
        "修正后从“后端”菜单手动重启。",
      ],
      { lastExit: { code, signal } }
    );
    return;
  }
  const delay = RESTART_BACKOFF_MS[Math.min(restartCount, RESTART_BACKOFF_MS.length - 1)];
  restartCount += 1;
  logLine(`scheduling backend restart ${restartCount}/${MAX_AUTO_RESTARTS} in ${delay} ms`);
  send("backend-restarting", { attempt: restartCount, max: MAX_AUTO_RESTARTS, delayMs: delay });
  setTimeout(() => {
    if (shuttingDown) return;
    startBackend();
    waitForHealth().catch((err) => {
      logLine(`restart health check failed: ${err.message}`);
    });
  }, delay);
}

function stopBackend() {
  if (!backendProcess) return Promise.resolve();
  return new Promise((resolve) => {
    const pid = backendProcess.pid;
    const child = backendProcess;
    let settled = false;
    const finish = () => {
      if (!settled) {
        settled = true;
        resolve();
      }
    };
    child.once("exit", finish);
    try {
      if (process.platform === "win32") {
        // /T kills the whole tree (uvicorn may spawn workers); /F is required
        // because the process ignores the console close signal when detached.
        spawn("taskkill", ["/PID", String(pid), "/T", "/F"], { windowsHide: true });
      } else {
        child.kill("SIGTERM");
      }
    } catch (err) {
      logLine(`stopBackend error: ${err}`);
    }
    setTimeout(() => {
      try {
        if (child && !child.killed) child.kill("SIGKILL");
      } catch (_) {
        /* already dead */
      }
      finish();
    }, 5000);
  });
}

/**
 * Wait for /api/health, but give up immediately if the child has already died.
 *
 * Waiting the full timeout on a process that crashed 200 ms in is exactly the
 * v0.7.1 behaviour this function replaces.
 */
function waitForHealth() {
  healthCheckAttempts = 0;
  const started = Date.now();
  return new Promise((resolve, reject) => {
    healthCheckTimer = setInterval(async () => {
      healthCheckAttempts += 1;
      if (!backendProcess) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        reject(new Error("BACKEND_EXITED"));
        return;
      }
      const ok = await backendHealthy(PORT);
      send("backend-status", {
        ok,
        attempts: healthCheckAttempts,
        elapsed: Date.now() - started,
        timeoutMs: START_TIMEOUT_MS,
      });
      if (ok) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        resolve(true);
      } else if (Date.now() - started > START_TIMEOUT_MS) {
        clearInterval(healthCheckTimer);
        healthCheckTimer = null;
        reject(new Error("HEALTH_TIMEOUT"));
      }
    }, HEALTH_INTERVAL_MS);
  });
}

// ----------------------------------------------------------------- window ----- //
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
      additionalArguments: [`--chemml-token=${sessionToken}`],
    },
  });

  mainWindow.once("ready-to-show", () => mainWindow.show());
  if (IS_DEV) mainWindow.webContents.openDevTools({ mode: "detach" });

  const url = `http://127.0.0.1:${PORT}/`;
  mainWindow.webContents.on("did-fail-load", () => {
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

/** Show a window even when startup fails, so the message is readable. */
function ensureWindow() {
  if (!mainWindow || mainWindow.isDestroyed()) createWindow();
}

// ------------------------------------------------------------------- boot ----- //
async function boot() {
  const paths = userPaths();
  ensureDirs(paths);
  backendLogPath = path.join(paths.logs, "backend.log");
  logLine(`=== Chem ML Platform v${app.getVersion()} starting (packaged=${app.isPackaged}) ===`);

  // 1. Probe the runtime against the full declared dependency set.
  sessionToken = crypto.randomBytes(32).toString("base64url");
  readonlyToken = crypto.randomBytes(32).toString("base64url");

  const root = backendRoot();
  runtimeDiagnosis = await runtimeProbe.probeRuntime({
    root,
    packaged: app.isPackaged,
    resourcesPath: process.resourcesPath,
  });
  logLine(`runtime probe: ${runtimeProbe.summarise(runtimeDiagnosis)}`);
  send("runtime-diagnosis", runtimeDiagnosis);

  if (runtimeDiagnosis.classification === runtimeProbe.CLASSIFICATION.PYTHON_MISSING) {
    ensureWindow();
    reportFailure(
      FAILURE.RUNTIME_MISSING,
      "未找到可用的 Python 运行时。",
      runtimeDiagnosis.guidance,
      { diagnosis: runtimeDiagnosis }
    );
    return;
  }
  if (
    runtimeDiagnosis.classification === runtimeProbe.CLASSIFICATION.PYTHON_INCOMPATIBLE ||
    runtimeDiagnosis.classification === runtimeProbe.CLASSIFICATION.DEPENDENCIES_MISSING ||
    runtimeDiagnosis.classification === runtimeProbe.CLASSIFICATION.DEPENDENCIES_INCOMPATIBLE
  ) {
    ensureWindow();
    reportFailure(
      FAILURE.DEPENDENCY_MISSING,
      `运行环境不满足要求（${runtimeDiagnosis.classification}）。`,
      runtimeDiagnosis.guidance,
      { diagnosis: runtimeDiagnosis }
    );
    return;
  }
  if (runtimeDiagnosis.classification === runtimeProbe.CLASSIFICATION.PROBE_ERROR) {
    ensureWindow();
    reportFailure(
      FAILURE.INSTALL,
      "运行环境探针执行失败，无法确认安装是否完整。",
      runtimeDiagnosis.guidance,
      { diagnosis: runtimeDiagnosis }
    );
    return;
  }

  // 2. Resolve the port, reporting (not hiding) a conflict.
  const inspected = await inspectPort(DEFAULT_PORT);
  if (inspected.occupied) {
    portConflict = {
      requestedPort: DEFAULT_PORT,
      occupant: inspected.product,
      sameProduct: inspected.ours,
    };
    logLine(`port ${DEFAULT_PORT} occupied by ${inspected.product} (ours=${inspected.ours})`);
  }
  const freePort = await pickFreePort(DEFAULT_PORT);
  if (!freePort) {
    ensureWindow();
    reportFailure(
      FAILURE.PORT_CONFLICT,
      `在 ${DEFAULT_PORT}–${DEFAULT_PORT + PORT_SCAN_RANGE - 1} 范围内没有可用端口。`,
      [
        `关闭占用端口的程序（当前占用者：${(portConflict && portConflict.occupant) || "未知"}）。`,
        "或设置环境变量 CHEMML_PORT 指定端口后重新启动。",
      ],
      { portConflict }
    );
    return;
  }
  PORT = Number(process.env.CHEMML_PORT || freePort);
  portConflict = portConflict ? { ...portConflict, usedPort: PORT } : null;
  send("port-info", { port: PORT, conflict: portConflict });

  // 3. Start the backend and wait for health.
  createWindow();
  startBackend();
  try {
    await waitForHealth();
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send("backend-ready", { port: PORT });
    }
    logLine(`backend ready on port ${PORT}`);
  } catch (err) {
    if (err.message === "BACKEND_EXITED") {
      reportFailure(
        FAILURE.BACKEND_CRASHED,
        "后端进程在就绪前退出。",
        [
          "查看日志末尾的 Python 异常堆栈。",
          "在应用安装目录执行 install.bat 重新校验依赖。",
          "确认防火墙未拦截 127.0.0.1 回环连接。",
        ]
      );
    } else {
      reportFailure(
        FAILURE.BACKEND_TIMEOUT,
        `后端在 ${START_TIMEOUT_MS / 1000}s 内未就绪。`,
        [
          "首次启动可能正在编译缓存，可在“后端”菜单重试。",
          `如长期无响应，请检查日志：${backendLogPath}`,
          `必要时设置 CHEMML_START_TIMEOUT_MS 提高超时上限（当前 ${START_TIMEOUT_MS} ms）。`,
        ]
      );
    }
  }
}

app.whenReady().then(boot).catch((err) => {
  logLine(`boot crashed: ${err && err.stack ? err.stack : err}`);
  try {
    ensureWindow();
    reportFailure(FAILURE.INSTALL, `启动流程异常终止：${err && err.message ? err.message : err}`, [
      "请捕获日志文件并反馈该故障代码。",
    ]);
  } catch (_) {
    dialog.showErrorBox("Chem ML Platform", String(err));
  }
});

function persistSession() {
  try {
    const file = path.join(userPaths().config, "session.json");
    fs.writeFileSync(file, JSON.stringify({ port: PORT, version: app.getVersion() }, null, 2), "utf-8");
  } catch (_) {
    /* non fatal */
  }
}

app.on("window-all-closed", () => {
  app.quit();
});

// Every quit path terminates the child tree, so no orphan keeps the port.
app.on("before-quit", (event) => {
  if (backendProcess && !shuttingDown) {
    event.preventDefault();
    shuttingDown = true;
    persistSession();
    stopBackend().finally(() => app.quit());
  }
});

app.on("will-quit", () => {
  shuttingDown = true;
  if (backendProcess) {
    try {
      if (process.platform === "win32") {
        spawn("taskkill", ["/PID", String(backendProcess.pid), "/T", "/F"], { windowsHide: true });
      } else {
        backendProcess.kill("SIGKILL");
      }
    } catch (_) {
      /* best effort */
    }
  }
});

process.on("exit", () => {
  if (backendProcess) {
    try {
      process.kill(backendProcess.pid, "SIGKILL");
    } catch (_) {
      /* best effort */
    }
  }
});

// ---------------------------------------------------------------- IPC ---- //
ipcMain.handle("backend-info", () => ({
  port: PORT,
  running: Boolean(backendProcess),
  logPath: backendLogPath,
  version: app.getVersion(),
  packaged: app.isPackaged,
  python: (runtimeDiagnosis && runtimeDiagnosis.pythonCommand) || "",
  userData: userPaths().root,
  structured: {
    paths: userPaths(),
    portConflict,
    restartCount,
    maxRestarts: MAX_AUTO_RESTARTS,
    startTimeoutMs: START_TIMEOUT_MS,
    failureCodes: FAILURE,
  },
}));

ipcMain.handle("runtime-diagnosis", () => runtimeDiagnosis || { classification: "unknown" });

ipcMain.handle("read-backend-log", (_event, lines = 200) => {
  try {
    const content = fs.readFileSync(backendLogPath, "utf-8");
    return content.split("\n").slice(-lines).join("\n");
  } catch (_) {
    return "";
  }
});

ipcMain.handle("restart-backend", async () => {
  restartCount = 0;
  shuttingDown = false;
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
