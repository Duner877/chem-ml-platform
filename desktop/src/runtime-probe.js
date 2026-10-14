/**
 * Chem ML Platform v0.7.2 -- backend runtime probe (spec task P0-02).
 *
 * The v0.7.1 audit finding this file fixes: the desktop shell only checked four
 * base packages (`fastapi`, `uvicorn`, `pydantic`, `numpy`) before declaring the
 * environment ready.  A machine with those four present but `python-docx` or
 * `scipy` missing was reported as a healthy install, and the user only found out
 * mid-workflow.
 *
 * This module therefore validates the **entire declared dependency set** from
 * `requirements.txt` (and `requirements.lock` when present), including PEP 508
 * environment markers, and returns a classification the UI can act on:
 *
 *   ok                        every applicable requirement is satisfied
 *   python_missing            no usable interpreter was found
 *   python_incompatible       an interpreter was found but outside the supported range
 *   dependencies_missing      one or more distributions are not installed
 *   dependencies_incompatible installed, but a version constraint is violated
 *   probe_error               the probe itself could not run
 *
 * It is a plain CommonJS module with no Electron import so it can be executed
 * standalone (`node runtime-probe.js --json`) and unit-tested from Python:
 * see `tests/test_v07_2_desktop_runtime.py`.
 *
 * Design note: requirement parsing, marker evaluation and version comparison all
 * happen **in Python**, using the interpreter under test.  Re-implementing
 * PEP 440 / PEP 508 semantics in JavaScript would guarantee the probe and the
 * installer disagree about what "installed" means.
 */

"use strict";

const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");

/** Supported interpreter range (see docs/V07_2_DESKTOP_RUNTIME.md). */
const MIN_PYTHON = [3, 10];
const MAX_PYTHON = [3, 13];

/** Closed set of classifications returned to the caller. */
const CLASSIFICATION = Object.freeze({
  OK: "ok",
  PYTHON_MISSING: "python_missing",
  PYTHON_INCOMPATIBLE: "python_incompatible",
  DEPENDENCIES_MISSING: "dependencies_missing",
  DEPENDENCIES_INCOMPATIBLE: "dependencies_incompatible",
  PROBE_ERROR: "probe_error",
});

/**
 * Executed with the interpreter under test.  Reads a JSON array of requirement
 * strings on stdin and writes one JSON object on stdout.
 */
const PY_PROBE = String.raw`
import json, os, sys, platform

payload = json.loads(sys.stdin.read() or "{}")
groups = {
    "required": payload.get("required", []),
    "optional": payload.get("optional", []),
}

try:
    from packaging.requirements import Requirement
    from packaging.markers import Marker
    from packaging.utils import canonicalize_name
    HAVE_PACKAGING = True
except Exception:
    HAVE_PACKAGING = False

from importlib import metadata as md


def installed_version(name):
    try:
        return md.version(name)
    except Exception:
        return None


def evaluate_marker(marker_text):
    """Return True/False/None (None = could not be evaluated)."""
    if not marker_text:
        return True
    if not HAVE_PACKAGING:
        return None
    try:
        return bool(Marker(marker_text).evaluate())
    except Exception:
        return None


def check(raw):
    line = raw.split("#", 1)[0].strip()
    if not line:
        return None
    name, specifier, marker_text = line, "", ""
    if ";" in line:
        line, marker_text = line.split(";", 1)
        marker_text = marker_text.strip()
    line = line.strip()

    if HAVE_PACKAGING:
        try:
            req = Requirement(line)
            name = canonicalize_name(req.name)
            specifier = str(req.specifier)
        except Exception as exc:
            return {
                "line": raw.strip(), "name": line, "specifier": "",
                "marker": marker_text, "marker_applies": None,
                "installed": None, "satisfied": None,
                "reason": "cannot parse requirement: %s" % exc,
            }
    else:
        for token in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            if token in line:
                head, tail = line.split(token, 1)
                name = head.strip()
                specifier = token + tail.strip()
                break
        else:
            name = line

    applies = evaluate_marker(marker_text)
    if applies is False:
        return {
            "line": raw.strip(), "name": name, "specifier": specifier,
            "marker": marker_text, "marker_applies": False,
            "installed": None, "satisfied": True,
            "reason": "marker not applicable on this platform (%s)" % marker_text,
        }

    version = installed_version(name)
    satisfied = None
    reason = ""
    if version is None:
        satisfied = False
        reason = "not installed"
    elif not specifier:
        satisfied = True
    elif HAVE_PACKAGING:
        try:
            req = Requirement("%s%s" % (name, specifier))
            satisfied = req.specifier.contains(version, prereleases=True)
            reason = "" if satisfied else "%s does not satisfy %s" % (version, specifier)
        except Exception as exc:
            satisfied = None
            reason = "cannot compare: %s" % exc
    else:
        satisfied = None
        reason = "packaging module unavailable; version not verified"

    return {
        "line": raw.strip(), "name": name, "specifier": specifier,
        "marker": marker_text or "", "marker_applies": True if applies else None,
        "installed": version, "satisfied": satisfied, "reason": reason,
    }


out = {}
for group, lines in groups.items():
    out[group] = [r for r in (check(raw) for raw in lines) if r is not None]

print(json.dumps({
    "python": sys.version.split()[0],
    "python_info": list(sys.version_info[:3]),
    "executable": sys.executable,
    "prefix": sys.prefix,
    "platform": platform.platform(),
    "machine": platform.machine(),
    "has_packaging": HAVE_PACKAGING,
    "required": out["required"],
    "optional": out["optional"],
}))
`;

/** Version tuple comparison, e.g. [3,10] <= [3,13,1]. */
function cmpVersion(a, b) {
  for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
    const left = a[i] || 0;
    const right = b[i] || 0;
    if (left !== right) return left < right ? -1 : 1;
  }
  return 0;
}

/**
 * Is an interpreter version outside the supported range?
 *
 * The bounds are **major.minor** bounds, so 3.13.14 is inside 3.10–3.13.
 * Comparing full triplets against a two-element bound made every patch release
 * of the newest supported minor look unsupported.
 */
function outOfRange(versionInfo) {
  const parts = Array.isArray(versionInfo) ? versionInfo.slice(0, 2) : [];
  if (parts.length < 2) return true;
  return cmpVersion(parts, MIN_PYTHON) < 0 || cmpVersion(parts, MAX_PYTHON) > 0;
}

/**
 * Candidate interpreters, most specific first.
 *
 * A bundled runtime is preferred, then a venv shipped beside the app, then the
 * repository venv, and only then PATH.  PATH is last because a developer
 * machine's global interpreter must never be silently used instead of the
 * declared one (spec P0-02 acceptance: "首次启动不依赖开发者机器的绝对路径").
 */
function resolvePythonCandidates({ packaged, resourcesPath, backendRoot, env = process.env } = {}) {
  const exe = process.platform === "win32" ? "python.exe" : "python3";
  const out = [];
  if (env.CHEMML_PYTHON) out.push({ python: env.CHEMML_PYTHON, source: "CHEMML_PYTHON" });
  if (packaged && resourcesPath) {
    out.push({
      python: path.join(resourcesPath, "python-runtime", exe),
      source: "bundled-runtime",
    });
    out.push({
      python: path.join(resourcesPath, "python-runtime", "bin", "python"),
      source: "bundled-runtime",
    });
  }
  if (backendRoot) {
    out.push({
      python: path.join(backendRoot, ".venv", "Scripts", "python.exe"),
      source: "app-venv",
    });
    out.push({ python: path.join(backendRoot, ".venv", "bin", "python"), source: "app-venv" });
    out.push({ python: path.join(backendRoot, "python-runtime", exe), source: "app-runtime" });
  }
  out.push({ python: process.platform === "win32" ? "python" : "python3", source: "PATH" });
  out.push({ python: "python", source: "PATH" });
  return out.filter((c, i, arr) => arr.findIndex((x) => x.python === c.python) === i);
}

/** First candidate that exists (or that is a bare name we are willing to try). */
function resolvePython(options = {}) {
  for (const candidate of resolvePythonCandidates(options)) {
    const isPath = candidate.python.includes(path.sep) || candidate.python.includes("/");
    if (!isPath) return candidate; // bare name -> let PATH decide
    if (fs.existsSync(candidate.python)) return candidate;
  }
  return { python: "", source: "none" };
}

/**
 * Read the declared dependency sets.
 *
 * Required (`requirements.runtime.txt`, else `requirements.txt`) blocks startup.
 * Optional (`requirements.optional.txt`) only degrades capability.  Returning
 * the source names lets the report state which file was actually validated.
 */
function readRequirements(root) {
  const load = (name) => {
    const file = path.join(root, name);
    try {
      if (!fs.existsSync(file)) return null;
      return {
        source: name,
        path: file,
        lines: fs
          .readFileSync(file, "utf-8")
          .split(/\r?\n/)
          .filter((line) => line.trim() && !line.trim().startsWith("#")),
      };
    } catch (_) {
      return null;
    }
  };

  let required = null;
  for (const name of ["requirements.runtime.txt", "requirements.lock", "requirements.txt"]) {
    required = load(name);
    if (required) break;
  }
  if (!required) required = { source: "", path: "", lines: [] };

  const optional = load("requirements.optional.txt") || { source: "", path: "", lines: [] };
  return { ...required, optionalSource: optional.source, optionalLines: optional.lines };
}

/** Run the Python-side probe. Resolves to the parsed object or `{ __error }`. */
function runPythonProbe(pythonCmd, { required, optional }, { cwd, timeoutMs = 60000 } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const done = (value) => {
      if (!settled) {
        settled = true;
        resolve(value);
      }
    };

    let child;
    try {
      // Async spawn on purpose: the probe can take tens of seconds on a cold
      // interpreter, and the Electron main process must stay responsive so the
      // window can show progress.  (spawnSync also fails with EBUSY on some
      // hardened Windows hosts.)
      child = spawn(pythonCmd, ["-c", PY_PROBE], {
        cwd,
        windowsHide: true,
        stdio: ["pipe", "pipe", "pipe"],
      });
    } catch (err) {
      done({ __error: String(err && err.message ? err.message : err) });
      return;
    }

    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      try {
        child.kill("SIGKILL");
      } catch (_) {
        /* already gone */
      }
      done({ __error: `probe timed out after ${timeoutMs}ms` });
    }, timeoutMs);

    child.stdout.on("data", (chunk) => {
      stdout += chunk;
      if (stdout.length > 8 * 1024 * 1024) stdout = stdout.slice(-8 * 1024 * 1024);
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
      if (stderr.length > 1024 * 1024) stderr = stderr.slice(-1024 * 1024);
    });
    child.on("error", (err) => {
      clearTimeout(timer);
      done({ __error: String(err && err.message ? err.message : err) });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        done({ __error: (stderr || stdout || `python exited ${code}`).trim() });
        return;
      }
      const text = (stdout || "").trim();
      const lastLine = text.split("\n").filter(Boolean).pop() || "";
      try {
        done(JSON.parse(lastLine));
      } catch (err) {
        done({ __error: `cannot parse probe output: ${err.message}` });
      }
    });
    child.stdin.on("error", () => {
      /* the child may exit before reading stdin; handled via close */
    });
    child.stdin.end(JSON.stringify({ required, optional }));
  });
}

/** Turn the raw probe payload into a classified, actionable result. */
function classify(info, requirementsMeta, pythonCmd, pythonSource) {
  const summaryOf = (rows) => {
    const results = rows || [];
    const applicable = results.filter((r) => r.marker_applies !== false);
    return {
      declared: results.length,
      applicable: applicable.length,
      satisfied: applicable.filter((r) => r.satisfied === true).length,
      missing: applicable
        .filter((r) => r.satisfied === false && r.installed === null)
        .map((r) => ({ name: r.name, specifier: r.specifier })),
      mismatched: applicable
        .filter((r) => r.satisfied === false && r.installed !== null)
        .map((r) => ({ name: r.name, specifier: r.specifier, installed: r.installed })),
      unverified: applicable
        .filter((r) => r.satisfied === null)
        .map((r) => ({ name: r.name, reason: r.reason })),
      details: results,
    };
  };

  const required = summaryOf(info && info.required);
  const optional = summaryOf(info && info.optional);
  const version = (info && info.python_info) || [];
  let classification = CLASSIFICATION.OK;

  if (!pythonCmd) classification = CLASSIFICATION.PYTHON_MISSING;
  else if (outOfRange(version)) classification = CLASSIFICATION.PYTHON_INCOMPATIBLE;
  else if (required.missing.length) classification = CLASSIFICATION.DEPENDENCIES_MISSING;
  else if (required.mismatched.length) classification = CLASSIFICATION.DEPENDENCIES_INCOMPATIBLE;

  return {
    classification,
    ok: classification === CLASSIFICATION.OK,
    python: {
      command: pythonCmd,
      source: pythonSource,
      version: (info && info.python) || "",
      versionInfo: version,
      executable: (info && info.executable) || "",
      prefix: (info && info.prefix) || "",
      supportedRange: `${MIN_PYTHON.join(".")}–${MAX_PYTHON.join(".")}`,
    },
    platform: { platform: (info && info.platform) || "", machine: (info && info.machine) || "" },
    requirements: {
      source: requirementsMeta.source,
      ...required,
      optionalSource: requirementsMeta.optionalSource,
      optional,
    },
    hasPackaging: Boolean(info && info.has_packaging),
    guidance: guidanceFor(classification, required.missing, required.mismatched, version).concat(
      optionalDebt(optional)
    ),
  };
}

/** Optional components that are absent -- capability degradation, not failure. */
function optionalDebt(optional) {
  const absent = (optional.missing || []).length + (optional.mismatched || []).length;
  if (!absent) return [];
  const names = [...optional.missing, ...optional.mismatched].map((r) => r.name).join(", ");
  return [
    `可选组件未安装或版本不符：${names}。相关能力将使用内置回退实现（结果仍可复现，但性能或精度可能下降）。`,
  ];
}

function guidanceFor(classification, missing, wrongVersion, version) {
  switch (classification) {
    case CLASSIFICATION.PYTHON_MISSING:
      return [
        "未找到可用的 Python 解释器（已检查随附运行时、应用内 .venv 与 PATH）。",
        `请安装 Python ${MIN_PYTHON.join(".")}–${MAX_PYTHON.join(".")}（64 位），或设置环境变量 CHEMML_PYTHON 指向解释器绝对路径。`,
        "安装后重新启动 Chem ML Platform。",
      ];
    case CLASSIFICATION.PYTHON_INCOMPATIBLE:
      return [
        `检测到 Python ${version.join(".")}，超出受支持范围 ${MIN_PYTHON.join(".")}–${MAX_PYTHON.join(".")}。`,
        "请安装受支持版本的 Python，并用 CHEMML_PYTHON 指定，或在应用安装目录执行 install.bat。",
      ];
    case CLASSIFICATION.DEPENDENCIES_MISSING:
      return [
        `缺少 ${missing.length} 个依赖：${missing.map((m) => m.name).join(", ")}。`,
        "在应用安装目录执行 install.bat（或 `python -m pip install -r requirements.txt`）后重试。",
        "依赖检查覆盖 requirements.txt 中的完整声明集合，而非少数基础包。",
      ];
    case CLASSIFICATION.DEPENDENCIES_INCOMPATIBLE:
      return [
        `有 ${wrongVersion.length} 个依赖版本不满足声明：` +
          wrongVersion.map((w) => `${w.name}=${w.installed} (需要 ${w.specifier})`).join("; ") +
          "。",
        "请升级/降级到声明版本，或使用应用随附的依赖清单重新安装。",
      ];
    default:
      return ["运行时与依赖检查通过。"];
  }
}

/**
 * Full probe: locate interpreter -> validate the declared dependency set.
 *
 * @param {object} opts
 * @param {string} opts.root        directory holding requirements.txt (backend root)
 * @param {boolean} [opts.packaged]
 * @param {string} [opts.resourcesPath]
 * @param {string} [opts.python]    force a specific interpreter command
 * @param {number} [opts.timeoutMs]
 */
function probeRuntime(opts = {}) {
  const root = opts.root || process.cwd();
  const requirementsMeta = readRequirements(root);
  const resolved =
    opts.python != null
      ? { python: opts.python, source: "explicit" }
      : resolvePython({
          packaged: opts.packaged,
          resourcesPath: opts.resourcesPath,
          backendRoot: root,
          env: opts.env || process.env,
        });

  const base = {
    checkedAt: new Date().toISOString(),
    root,
    pythonCommand: resolved.python,
    pythonSource: resolved.source,
  };

  if (!resolved.python) {
    return Promise.resolve({
      ...base,
      ok: false,
      classification: CLASSIFICATION.PYTHON_MISSING,
      python: {
        command: "",
        source: "none",
        supportedRange: `${MIN_PYTHON.join(".")}–${MAX_PYTHON.join(".")}`,
      },
      platform: {},
      requirements: {
        source: requirementsMeta.source,
        declared: requirementsMeta.lines.length,
        optionalSource: requirementsMeta.optionalSource,
      },
      hasPackaging: false,
      guidance: guidanceFor(CLASSIFICATION.PYTHON_MISSING, [], [], []),
    });
  }

  return runPythonProbe(
    resolved.python,
    { required: requirementsMeta.lines, optional: requirementsMeta.optionalLines },
    { cwd: root, timeoutMs: opts.timeoutMs || 60000 }
  ).then((info) => {
    if (info.__error) {
      const missingInterpreter = /ENOENT|not found|cannot find/i.test(info.__error);
      const classification = missingInterpreter
        ? CLASSIFICATION.PYTHON_MISSING
        : CLASSIFICATION.PROBE_ERROR;
      return {
        ...base,
        ok: false,
        classification,
        probeError: info.__error,
        python: {
          command: resolved.python,
          source: resolved.source,
          supportedRange: `${MIN_PYTHON.join(".")}–${MAX_PYTHON.join(".")}`,
        },
        platform: {},
        requirements: {
          source: requirementsMeta.source,
          declared: requirementsMeta.lines.length,
          optionalSource: requirementsMeta.optionalSource,
        },
        hasPackaging: false,
        guidance:
          classification === CLASSIFICATION.PYTHON_MISSING
            ? guidanceFor(CLASSIFICATION.PYTHON_MISSING, [], [], [])
            : [
                `运行环境探针执行失败：${info.__error}`,
                "请检查 Python 是否可执行，并查看日志文件。",
              ],
      };
    }
    const result = classify(info, requirementsMeta, resolved.python, resolved.source);
    return { ...base, ...result };
  });
}

/** One-line human summary, used by the CLI and by the Electron log. */
function summarise(result) {
  const r = result.requirements || {};
  const bits = [
    `classification=${result.classification}`,
    `python=${(result.python && result.python.version) || "?"} (${result.pythonCommand || "-"})`,
    `required=${r.source || "none"}`,
    `satisfied=${r.satisfied}/${r.applicable}`,
  ];
  if (r.missing && r.missing.length) bits.push(`missing=${r.missing.map((m) => m.name).join(",")}`);
  if (r.mismatched && r.mismatched.length) {
    bits.push(`mismatched=${r.mismatched.map((m) => `${m.name}=${m.installed}`).join(",")}`);
  }
  if (r.optional && r.optional.declared) {
    bits.push(`optional=${r.optional.satisfied}/${r.optional.applicable}`);
  }
  return bits.join(" ");
}

async function main(argv) {
  const args = { json: argv.includes("--json") };
  const rootFlag = argv.indexOf("--root");
  if (rootFlag !== -1) args.root = argv[rootFlag + 1];
  const pyFlag = argv.indexOf("--python");
  if (pyFlag !== -1) args.python = argv[pyFlag + 1];

  const result = await probeRuntime({
    root: args.root ? path.resolve(args.root) : path.resolve(__dirname, "..", ".."),
    python: args.python,
  });

  if (args.json) {
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  } else {
    process.stdout.write(summarise(result) + "\n");
    for (const line of result.guidance || []) process.stdout.write(`  - ${line}\n`);
  }
  // Exit code encodes the verdict so shell/CI callers can branch on it.
  return result.ok ? 0 : 1;
}

module.exports = {
  CLASSIFICATION,
  MIN_PYTHON,
  MAX_PYTHON,
  cmpVersion,
  parseRequirementsLines: (text) =>
    text
      .split(/\r?\n/)
      .filter((line) => line.trim() && !line.trim().startsWith("#")),
  readRequirements,
  resolvePython,
  resolvePythonCandidates,
  probeRuntime,
  summarise,
  guidanceFor,
};

if (require.main === module) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (err) => {
      process.stderr.write(`runtime probe crashed: ${err && err.stack ? err.stack : err}\n`);
      process.exit(2);
    }
  );
}
