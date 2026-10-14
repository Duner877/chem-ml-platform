/**
 * Stamp the build provenance before electron-builder packs the payload.
 *
 * `extraResources` copies this file into `resources/app/`, which is not a Git
 * checkout -- so without a stamp the packaged app answers `git_commit() ==
 * "unknown"`, the exact defect ISSUE-21 records for extracted archives.  The
 * Electron build is the *other* place a distributed copy is born, so it gets
 * the same stamp, from the same code (`chemml_version.build_stamp`), through
 * the same fields.
 *
 * The stamp is produced by Python rather than re-implemented here: two
 * implementations of "what commit is this?" eventually disagree, and then one
 * of them is lying about provenance.
 *
 * Run manually (the output path defaults to the repository root):
 *
 *     node desktop/scripts/stamp-build-info.js
 *     CHEMML_BUILD_INFO_PATH=/tmp/BUILD_INFO.json node desktop/scripts/stamp-build-info.js
 *
 * A missing interpreter is a warning, not a build failure: the app needs Python
 * at *runtime* (the probe checks it), but its absence at build time only
 * degrades the provenance record.  `scripts/refresh_desktop_payload.py
 * --verify` reports the missing stamp as STALE, so the release process still
 * catches it.
 */

"use strict";

const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..", "..");
const OUTPUT =
  process.env.CHEMML_BUILD_INFO_PATH
    ? path.resolve(process.env.CHEMML_BUILD_INFO_PATH)
    : path.join(ROOT, "BUILD_INFO.json");

// The probe that produced this stamp; recorded inside the stamp itself.
const PRODUCED_BY = "desktop/scripts/stamp-build-info.js";

const PYTHON_CANDIDATES = [
  process.env.CHEMML_PYTHON,
  "python",
  "python3",
  "py",
].filter(Boolean);

const IMPORT_PROBE =
  "import sys; sys.path.insert(0, " +
  JSON.stringify(ROOT) +
  "); import chemml_version; print(chemml_version.__version__)";

const STAMP_PROBE =
  "import json, sys; sys.path.insert(0, " +
  JSON.stringify(ROOT) +
  "); import chemml_version; " +
  "print(json.dumps(chemml_version.build_stamp(" +
  JSON.stringify(PRODUCED_BY) +
  ")))";

function pythonWithChemml() {
  for (const candidate of PYTHON_CANDIDATES) {
    try {
      execFileSync(candidate, ["-c", IMPORT_PROBE], {
        cwd: ROOT,
        stdio: ["ignore", "pipe", "pipe"],
      });
      return candidate;
    } catch (_) {
      // Not an interpreter, or not one that can import the version module.
    }
  }
  return null;
}

function main() {
  const python = pythonWithChemml();
  if (!python) {
    console.warn(
      "[stamp-build-info] no Python interpreter found; BUILD_INFO.json not " +
        'written. The packaged payload will report commit "unknown" until ' +
        "scripts/refresh_desktop_payload.py stamps it."
    );
    return 0;
  }

  let stamp;
  try {
    stamp = JSON.parse(
      execFileSync(python, ["-c", STAMP_PROBE], { cwd: ROOT, encoding: "utf-8" })
    );
  } catch (error) {
    const detail = error && error.message ? error.message : String(error);
    console.warn(
      "[stamp-build-info] build_stamp() failed (" +
        detail +
        "); BUILD_INFO.json not written."
    );
    return 0;
  }

  const text = JSON.stringify(stamp, null, 2) + "\n";
  if (fs.existsSync(OUTPUT) && fs.readFileSync(OUTPUT, "utf-8") === text) {
    console.log("[stamp-build-info] unchanged: " + OUTPUT);
    return 0;
  }
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true });
  fs.writeFileSync(OUTPUT, text);
  console.log(
    "[stamp-build-info] wrote " + OUTPUT + " (commit " + stamp.commit_short + ")"
  );
  return 0;
}

if (require.main === module) {
  process.exit(main());
}

// electron-builder resolves `beforeBuild` as a module path and prefers a named
// export matching the hook name; falling back to the module itself also works,
// but naming it keeps the contract explicit.  Returning a falsy value tells
// electron-builder that node_modules are handled outside of it, which is what
// we want: the desktop dependencies are pre-installed, and a rebuild would be
// slow and offline-fragile for no benefit.
module.exports = { main, beforeBuild: main };
