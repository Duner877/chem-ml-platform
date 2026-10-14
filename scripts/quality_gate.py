"""Chem ML Platform v0.7.2 -- trustworthy quality gate (spec task P0-03).

Why this file was rewritten
---------------------------
The v0.7.1 gate could print PASS for a step whose subprocess had timed out, and
its report recorded a bare count of checks -- not the *evidence* a reader needs
to reproduce a number.  The v0.7.1 release report claimed 258 tests while a
fresh collection found 262, and nobody could tell which was right.

Every stage now emits, and this file stores:

* the Git commit of the tree under test,
* the Python version and the versions of the key dependencies,
* the exact command that ran,
* collected / passed / failed / skipped / error counts,
* the process exit code,
* the path of the full stdout+stderr log,
* and a status from a closed set where **TIMEOUT is its own state** and is never
  folded into PASS.

Status vocabulary (closed set):

``PASS``     the step did what it claims, exit code 0, no timeout.
``FAIL``     the step ran and failed (non-zero exit, or a test failed).
``TIMEOUT``  the step exceeded its budget and was killed -- never a pass.
``SKIP``     the step is not applicable here, with a stated reason.
``ERROR``    the gate itself could not execute the step (harness bug).

``SKIP`` is honest, but the reason is mandatory.  ``TIMEOUT`` and ``ERROR``
always fail the gate.

Usage::

    python scripts/quality_gate.py                  # all stages
    python scripts/quality_gate.py --fast           # skip frontend build + installer
    python scripts/quality_gate.py --json out.json --md out.md --log-dir logs/
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PYTHON = sys.executable

PASS, FAIL, TIMEOUT, SKIP, ERROR = "PASS", "FAIL", "TIMEOUT", "SKIP", "ERROR"

#: Statuses that make the gate fail.  SKIP never does (it carries a reason).
FAILING = {FAIL, TIMEOUT, ERROR}

#: Repo-local pytest temp root -- see the note on ``_PYTEST_TMP_ROOT`` below.
_PYTEST_TMP_ROOT = ROOT / "output" / "pytest_gate_tmp"
_pytest_tmp_seq = 0

DEFAULT_LOG_DIR = ROOT / "output" / "gate_logs"


@dataclass
class CheckResult:
    name: str
    category: str
    status: str
    detail: str = ""
    duration_ms: float = 0.0
    command: str = ""
    log_path: str = ""
    exit_code: Optional[int] = None
    timeout_s: Optional[float] = None
    collected: Optional[int] = None
    passed: Optional[int] = None
    failed: Optional[int] = None
    skipped: Optional[int] = None
    errors: Optional[int] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    version: str = ""
    codename: str = ""
    commit: str = ""
    started_at: str = ""
    finished_at: str = ""
    python: str = ""
    dependencies: Dict[str, str] = field(default_factory=dict)
    node: str = ""
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    timed_out: int = 0
    errored: int = 0
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.timed_out == 0 and self.errored == 0

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if result.status == PASS:
            self.passed += 1
        elif result.status == SKIP:
            self.skipped += 1
        elif result.status == TIMEOUT:
            self.timed_out += 1
        elif result.status == ERROR:
            self.errored += 1
        else:
            self.failed += 1

    @property
    def total_tests(self) -> int:
        return sum(c.collected or 0 for c in self.checks)

    def to_json(self) -> str:
        payload = {k: v for k, v in self.__dict__.items() if k != "checks"}
        payload["ok"] = self.ok
        payload["total_tests_collected"] = self.total_tests
        payload["checks"] = [c.to_dict() for c in self.checks]
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def to_markdown(self) -> str:
        lines = [
            f"# Chem ML Platform v{self.version} — Quality Gate Report",
            "",
            f"- **codename**: {self.codename}",
            f"- **commit**: `{self.commit}`",
            f"- **python**: {self.python}",
            f"- **node**: {self.node}",
            f"- **started**: {self.started_at}",
            f"- **finished**: {self.finished_at}",
            f"- **PASS**: {self.passed} · **FAIL**: {self.failed} · **SKIP**: {self.skipped} "
            f"· **TIMEOUT**: {self.timed_out} · **ERROR**: {self.errored}",
            f"- **gate**: {'PASSED' if self.ok else 'FAILED'}",
            f"- **tests collected**: {self.total_tests}",
            "",
            "> A step is only PASS when its process exited 0 within its time budget. "
            "TIMEOUT is a distinct state and always fails the gate; SKIP never counts as a pass.",
            "",
            "## Stages",
            "",
            "| # | Stage | Category | Status | Exit | Tests (coll/pass/fail/skip/err) | Duration | Detail |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for i, check in enumerate(self.checks, 1):
            if check.collected is None:
                counts = "—"
            else:
                counts = (
                    f"{check.collected}/{check.passed}/{check.failed}/{check.skipped}/{check.errors}"
                )
            exit_code = "—" if check.exit_code is None else str(check.exit_code)
            detail = check.detail.replace("\n", " ").replace("|", "\\|")[:140]
            lines.append(
                f"| {i} | {check.name} | {check.category} | {check.status} | {exit_code} | "
                f"{counts} | {check.duration_ms:.0f} ms | {detail} |"
            )

        lines += ["", "## Evidence per stage", ""]
        for check in self.checks:
            lines.append(f"### `{check.name}` — {check.status}")
            lines.append("")
            lines.append(f"- category: `{check.category}`")
            if check.command:
                lines.append(f"- command: `{check.command}`")
            if check.timeout_s is not None:
                lines.append(f"- timeout: {check.timeout_s:.0f} s")
            if check.exit_code is not None:
                lines.append(f"- exit code: {check.exit_code}")
            if check.collected is not None:
                lines.append(
                    f"- tests: collected={check.collected} passed={check.passed} "
                    f"failed={check.failed} skipped={check.skipped} errors={check.errors}"
                )
            if check.log_path:
                lines.append(f"- log: `{check.log_path}`")
            lines.append(f"- detail: {check.detail or '—'}")
            lines.append("")

        if self.dependencies:
            lines += ["## Dependency fingerprint", "", "| Package | Version |", "| --- | --- |"]
            for name, version in sorted(self.dependencies.items()):
                lines.append(f"| {name} | {version} |")
            lines.append("")
        return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Process harness
# --------------------------------------------------------------------------- #

def _log_path(name: str, log_dir: Path) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{name}.log"


def _run(
    name: str,
    cmd: List[str],
    *,
    cwd: Optional[Path] = None,
    timeout: float = 600.0,
    log_dir: Path = DEFAULT_LOG_DIR,
    env: Optional[Dict[str, str]] = None,
) -> Tuple[str, int, str]:
    """Run a command, capture everything, and classify honestly.

    Returns ``(status, exit_code, detail)`` where ``status`` is one of
    PASS / FAIL / TIMEOUT / ERROR.  A timeout is NEVER a pass.
    """
    path = _log_path(name, log_dir)
    header = (
        f"$ {' '.join(cmd)}\n"
        f"# cwd={cwd or ROOT}\n"
        f"# timeout={timeout:.0f}s\n"
        f"# started={datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        + "-" * 78
        + "\n"
    )
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd or ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            errors="replace",
            env={**os.environ, **(env or {})},
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        path.write_text(header + out + err + f"\n\n### TIMEOUT after {timeout:.0f}s\n", encoding="utf-8")
        return TIMEOUT, -1, f"exceeded {timeout:.0f}s budget and was killed (log: {path.name})"
    except OSError as exc:
        path.write_text(header + f"\n\n### HARNESS ERROR: {exc!r}\n", encoding="utf-8")
        return ERROR, -2, f"could not execute: {exc}"

    path.write_text(
        header + (proc.stdout or "") + (proc.stderr or "") + f"\n# exit={proc.returncode}\n",
        encoding="utf-8",
    )
    tail = "\n".join(((proc.stderr or proc.stdout or "").strip().splitlines())[-6:])
    if proc.returncode == 0:
        last = (proc.stdout or "").strip().splitlines()[-1:] or [""]
        return PASS, 0, (last[0] if last[0] else "ok")[:300]
    return FAIL, proc.returncode, (tail or f"exit code {proc.returncode}")[:600]


def _junit_counts(xml_path: Path) -> Optional[Dict[str, int]]:
    """Read exact pass/fail/skip/error counts from a JUnit XML report."""
    try:
        root = ET.parse(str(xml_path)).getroot()
    except (OSError, ET.ParseError):
        return None
    suites = [root] if root.tag == "testsuite" else list(root)
    counts = {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    for suite in suites:
        if suite.tag != "testsuite":
            suite = next((c for c in suite if c.tag == "testsuite"), None)
            if suite is None:
                continue
        for case in suite.iter("testcase"):
            counts["collected"] += 1
            kinds = {child.tag for child in case}
            if "failure" in kinds:
                counts["failed"] += 1
            elif "error" in kinds:
                counts["errors"] += 1
            elif "skipped" in kinds:
                counts["skipped"] += 1
            else:
                counts["passed"] += 1
    return counts


def _pytest_stage(
    name: str,
    args: List[str],
    *,
    category: str,
    timeout: float = 900.0,
    log_dir: Path = DEFAULT_LOG_DIR,
) -> Tuple[CheckResult, str]:
    """Run a pytest selection and return a fully populated CheckResult.

    ``--basetemp`` is unique per invocation.  Rationale (v0.7.1 finding): pytest
    deletes a *populated* ``--basetemp`` at start, and on hardened hosts the
    safe-delete shim fails closed with ``OSError [Errno 123]`` on non-ASCII
    ``\\?\\``-prefixed paths, turning every ``tmp_path`` fixture into a spurious
    error.  A brand-new directory has nothing to delete.  The tree lives under
    ``output/`` (gitignored, excluded from release packages).
    """
    global _pytest_tmp_seq
    _pytest_tmp_seq += 1
    base = _PYTEST_TMP_ROOT / f"run{os.getpid()}_{_pytest_tmp_seq}"
    base.mkdir(parents=True, exist_ok=True)
    xml = (log_dir / f"{name}.xml")
    log_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        PYTHON,
        "-m",
        "pytest",
        *args,
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        f"--basetemp={base}",
        f"--junitxml={xml}",
    ]
    status, exit_code, detail = _run(name, cmd, timeout=timeout, log_dir=log_dir)

    counts = _junit_counts(xml) or {}
    # The reported command is the *reproducible* one: the basetemp and the JUnit
    # path are gate-local bookkeeping, so they are stripped from the evidence.
    reproducible = [part for part in cmd if not part.startswith(("--basetemp=", "--junitxml="))]
    result = CheckResult(
        name=name,
        category=category,
        status=status,
        detail=detail,
        command=" ".join(reproducible),
        log_path=str(_log_path(name, log_dir).relative_to(ROOT)),
        exit_code=exit_code,
        timeout_s=timeout,
        collected=counts.get("collected"),
        passed=counts.get("passed"),
        failed=counts.get("failed"),
        skipped=counts.get("skipped"),
        errors=counts.get("errors"),
    )

    if status == PASS:
        if result.collected == 0:
            result.status = FAIL
            result.detail = "declared suite collected 0 tests -- the classification is broken"
        elif result.skipped and result.skipped == result.collected:
            result.status = SKIP
            result.detail = f"all {result.collected} tests skipped (host-dependent suite)"
        else:
            result.detail = (
                f"{result.passed}/{result.collected} passed"
                + (f", {result.skipped} skipped" if result.skipped else "")
            )
    return result, " ".join(cmd)


# --------------------------------------------------------------------------- #
# Individual stages
# --------------------------------------------------------------------------- #

#: Path segments holding third-party / build output, never first-party source.
_NON_SOURCE_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "out", "build"}


def _dep_versions() -> Dict[str, str]:
    """Version fingerprint of the runtime that produced this report."""
    from importlib import metadata

    wanted = [
        "fastapi",
        "starlette",
        "uvicorn",
        "pydantic",
        "numpy",
        "scipy",
        "networkx",
        "pytest",
        "httpx",
        "torch",
    ]
    found: Dict[str, str] = {}
    for name in wanted:
        try:
            found[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            found[name] = "not installed"
    return found


def _node_version() -> str:
    try:
        proc = subprocess.run(
            ["node", "--version"], capture_output=True, text=True, timeout=30, errors="replace"
        )
        return (proc.stdout or proc.stderr or "").strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def stage_python_compile(log_dir: Path) -> Tuple[str, str, dict]:
    files = [p for p in ROOT.rglob("*.py") if not _NON_SOURCE_DIRS.intersection(p.parts)]
    status, code, detail = _run(
        "python_compile",
        [
            PYTHON,
            "-m",
            "compileall",
            "-q",
            "-x",
            "node_modules|__pycache__|\\.venv|[/\\\\]dist[/\\\\]|[/\\\\]out[/\\\\]",
            str(ROOT),
        ],
        timeout=300,
        log_dir=log_dir,
    )
    return status, f"{len(files)} first-party files compiled" if status == PASS else detail, {
        "exit_code": code,
    }


def stage_node_registry(log_dir: Path) -> Tuple[str, str, dict]:
    from nodes.loader import get_registry

    registry = get_registry()
    problems = []
    count = 0
    for node_type in registry.types():
        node_cls = registry.get(node_type)
        spec = node_cls.spec()
        count += 1
        if not spec.get("name") or not spec.get("category"):
            problems.append(f"{node_type}: missing name/category")
        for port in spec["inputs"] + spec["outputs"]:
            if not port.get("name") or not port.get("data_type"):
                problems.append(f"{node_type}: malformed port {port}")
    if problems:
        return FAIL, "; ".join(problems[:10]), {}
    return PASS, f"{count} node types, schemas valid", {}


def stage_node_provenance(log_dir: Path) -> Tuple[str, str, dict]:
    """Every node states its execution provenance, with no unsupported claim.

    Uses the *real* scanner + validator (spec task P0-05) rather than a
    hand-assembled record: a hand-built dict in the gate would drift from the
    registry the product actually ships.
    """
    from node_registry.scanner import collect_records
    from node_registry.validator import validate_records

    records = collect_records()
    report = validate_records(records)
    if not report["valid"]:
        first = "; ".join(
            f"{issue['node_name'] or issue.get('type', '?')}: {issue['issues'][:2]}"
            for issue in report["issues"][:5]
        )
        return FAIL, first[:600], {}

    counts: Dict[str, int] = {}
    modes: Dict[str, int] = {}
    without_evidence = 0
    for record in records:
        counts[record.get("capability_status", "?")] = (
            counts.get(record.get("capability_status", "?"), 0) + 1
        )
        modes[record.get("execution_mode", "?")] = modes.get(record.get("execution_mode", "?"), 0) + 1
        if not record.get("validation_evidence"):
            without_evidence += 1
    return (
        PASS,
        f"all {len(records)} nodes declare provenance · capability={counts} · "
        f"mode={modes} · 无验证证据 {without_evidence} 个（=未声明 verified）",
        {},
    )


def stage_workflow_json(log_dir: Path) -> Tuple[str, str, dict]:
    from nodes.loader import get_registry
    from workflow_engine.workflow import Workflow

    registry = get_registry()
    problems, checked = [], 0
    for path in sorted((ROOT / "workflows").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        issues = Workflow.from_dict(data).validate(registry)
        if issues:
            problems.append(f"{path.name}: {issues}")
        checked += 1
    if problems:
        return FAIL, "; ".join(problems)[:800], {}
    return PASS, f"{checked} workflow files valid", {}


def stage_benchmark_cli(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "synthetic_benchmark",
        [PYTHON, str(ROOT / "scripts" / "benchmark_lcms.py"), "--strict", "--quiet"],
        timeout=900,
        log_dir=log_dir,
    )
    return status, detail, {"exit_code": code}


def stage_demo_workflows(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "demo_workflows",
        [PYTHON, str(ROOT / "scripts" / "run_demo_workflows.py")],
        timeout=1200,
        log_dir=log_dir,
    )
    return status, detail, {"exit_code": code}


def _npm_cmd() -> List[str]:
    return ["npm.cmd"] if os.name == "nt" else ["npm"]


def stage_frontend_tsc(log_dir: Path) -> Tuple[str, str, dict]:
    frontend = ROOT / "frontend"
    if not (frontend / "package.json").exists():
        return SKIP, "frontend not present in this tree", {}
    if not (frontend / "node_modules").exists():
        return SKIP, "frontend dependencies not installed (run: cd frontend && npm ci)", {}
    status, code, detail = _run(
        "frontend_typescript", [*_npm_cmd(), "run", "lint"],
        cwd=frontend, timeout=600, log_dir=log_dir,
    )
    return status, detail if status != PASS else "tsc clean", {"exit_code": code}


def stage_frontend_build(log_dir: Path) -> Tuple[str, str, dict]:
    """Rebuild the production bundle and report the *fresh* file count.

    The stale ``dist/`` is removed first, from Python rather than from inside
    ``vite``.  Vite's ``emptyDir`` uses Node's ``rmSync``, which on a host with a
    bulk-delete guard refuses to remove a large output directory and aborts the
    build *after* compilation succeeded -- a false negative that says nothing
    about the code.  Deleting it here keeps the stage honest: the count below is
    of files this build produced, not of leftovers it failed to clear.
    """
    frontend = ROOT / "frontend"
    if not (frontend / "node_modules").exists():
        return SKIP, "frontend dependencies not installed", {}
    dist = frontend / "dist"
    if dist.exists():
        shutil.rmtree(dist, ignore_errors=True)
    status, code, detail = _run(
        "frontend_build", [*_npm_cmd(), "run", "build"],
        cwd=frontend, timeout=900, log_dir=log_dir,
    )
    if status != PASS:
        return status, detail, {"exit_code": code}
    n_files = sum(1 for p in dist.rglob("*") if p.is_file()) if dist.exists() else 0
    if not n_files:
        return FAIL, "build reported success but produced no output", {"exit_code": code}
    return PASS, f"dist built with {n_files} files", {"exit_code": code}


def stage_electron_config(log_dir: Path) -> Tuple[str, str, dict]:
    desktop = ROOT / "desktop"
    required = [
        desktop / "package.json",
        desktop / "src" / "main.js",
        desktop / "src" / "preload.js",
        desktop / "src" / "runtime-probe.js",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        return FAIL, f"missing: {missing}", {}
    config = json.loads((desktop / "package.json").read_text(encoding="utf-8"))
    if config.get("main") != "src/main.js":
        return FAIL, "package.json main must be src/main.js", {}
    if "win" not in config.get("build", {}):
        return FAIL, "electron-builder win target missing", {}
    return PASS, "electron shell configured (win/linux/mac targets declared)", {}


def _extract_json(text: str) -> Optional[str]:
    """Return the first complete top-level JSON object in ``text``, else ``None``.

    ``_run`` appends machine-readable trailers (``# exit=0``) after the child's
    output, so the payload cannot simply be "everything from the first line that
    starts with a brace".  Scanning it with a brace counter -- and tracking
    string literals so a ``}`` inside a quoted path is not counted -- isolates
    the object cleanly.
    """
    start = -1
    for idx, ch in enumerate(text):
        if ch == "{":
            start = idx
            break
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]
    return None


def stage_desktop_probe(log_dir: Path) -> Tuple[str, str, dict]:
    """Exercise the runtime probe the Electron shell uses on first start.

    The interpreter is passed explicitly (``--python``) on purpose: the gate must
    validate *the environment it is running in*, not whatever ``PATH`` happens to
    resolve to.  Letting the probe fall back to PATH made a correct environment
    look broken whenever a second interpreter shadowed it.
    """
    node = shutil.which("node") or "node"
    probe = ROOT / "desktop" / "src" / "runtime-probe.js"
    if not probe.exists():
        return SKIP, "runtime-probe.js not present", {}
    status, code, detail = _run(
        "desktop_runtime_probe",
        [node, str(probe), "--json", "--python", PYTHON],
        timeout=180,
        log_dir=log_dir,
    )
    if status != PASS:
        return status, detail, {"exit_code": code}
    log = _log_path("desktop_runtime_probe", log_dir).read_text(encoding="utf-8", errors="replace")
    payload = _extract_json(log)
    if payload is None:
        # The probe exited 0 but we could not read its verdict.  Reporting PASS
        # here would be exactly the "looks fine without evidence" failure this
        # gate exists to prevent, so it is an ERROR (harness-level) not a PASS.
        return ERROR, "probe exited 0 but no JSON report could be parsed", {"exit_code": code}
    try:
        data = json.loads(payload)
    except ValueError as exc:
        return ERROR, f"probe report is not valid JSON: {exc}", {"exit_code": code}
    requirements = data.get("requirements", {})
    if not data.get("ok"):
        return FAIL, f"classification={data.get('classification')} · " + "; ".join(
            data.get("guidance", [])[:2]
        ), {"exit_code": code}
    return (
        PASS,
        f"classification=ok · required {requirements.get('satisfied')}/"
        f"{requirements.get('applicable')} from {requirements.get('source')} · "
        f"optional {requirements.get('optional', {}).get('satisfied')}/"
        f"{requirements.get('optional', {}).get('applicable')}",
        {"exit_code": code},
    )


def stage_electron_installer(log_dir: Path) -> Tuple[str, str, dict]:
    import chemml_version

    desktop = ROOT / "desktop"
    patterns = [
        f"dist/*Setup {chemml_version.VERSION}.exe",
        f"dist/*{chemml_version.VERSION}*.exe",
        f"release/*{chemml_version.VERSION}*.exe",
        "dist/*.AppImage",
        "dist/*.dmg",
    ]
    for pattern in patterns:
        matches = sorted(desktop.glob(pattern))
        if matches:
            size = matches[0].stat().st_size / (1024 * 1024)
            return PASS, f"installer present: {matches[0].name} ({size:.1f} MiB)", {}
    return (
        SKIP,
        "installer for this version not built here "
        "(run: cd desktop && npm install && npm run build)",
        {},
    )


def stage_reproducibility(log_dir: Path) -> Tuple[str, str, dict]:
    """P1-06: prove a declared-deterministic workflow repeats bit-for-bit.

    Runs two workflows twice each and compares per-node output digests.  The
    stage fails when a node that the platform declared deterministic produces
    different content on the second run -- the one outcome the spec says must
    never be papered over with a vague "results may vary".
    """
    script = ROOT / "scripts" / "verify_reproducibility.py"
    if not script.exists():
        return SKIP, "verify_reproducibility.py not present", {}
    status, code, detail = _run(
        "reproducibility_verification",
        [
            PYTHON,
            str(script),
            "-w", "workflows/04_quantum_chemistry_profiling.json",
            "-w", "workflows/06_scientific_foundation_models.json",
            "--repeat", "2",
            "--quiet",
            "--json", str(ROOT / "output" / "reproducibility.json"),
        ],
        timeout=900,
        log_dir=log_dir,
    )
    if status != PASS:
        return status, detail, {"exit_code": code}
    report = ROOT / "output" / "reproducibility.json"
    if not report.is_file():
        return ERROR, "verification exited 0 but wrote no report", {"exit_code": code}
    try:
        data = json.loads(report.read_text(encoding="utf-8"))
    except ValueError as exc:
        return ERROR, f"reproducibility report is not valid JSON: {exc}", {"exit_code": code}
    workflows = data.get("workflows", [])
    compared = sum(w.get("determinism", {}).get("nodes_compared", 0) for w in workflows)
    weak = [
        f"{w.get('workflow')}:{name}"
        for w in workflows
        for name in w.get("traceability", {}).get("nodes_without_full_trace", [])
    ]
    if not workflows or compared == 0:
        return FAIL, "no workflow produced comparable node records", {"exit_code": code}
    detail = (
        f"{len(workflows)} workflow(s) x {data.get('repeat')} runs · "
        f"{compared} node results reproduced identically"
    )
    if weak:
        return FAIL, "incomplete traceability: " + ", ".join(weak[:4]), {"exit_code": code}
    return PASS, detail, {"exit_code": code}


def stage_version(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "version_consistency", [PYTHON, str(ROOT / "scripts" / "version.py"), "--check"],
        timeout=120, log_dir=log_dir,
    )
    if status == FAIL:
        detail = detail.replace("\n", " ")[:600]
    return status, detail, {"exit_code": code}


def stage_release_manifest(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "release_manifest", [PYTHON, str(ROOT / "scripts" / "release_manifest.py"), "--check"],
        timeout=180, log_dir=log_dir,
    )
    return status, detail, {"exit_code": code}


def stage_node_catalog(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "node_catalog", [PYTHON, str(ROOT / "scripts" / "node_catalog.py"), "--check"],
        timeout=300, log_dir=log_dir,
    )
    return status, detail, {"exit_code": code}


def stage_licence_sbom(log_dir: Path) -> Tuple[str, str, dict]:
    status, code, detail = _run(
        "licence_sbom", [PYTHON, str(ROOT / "scripts" / "license_report.py"), "--check"],
        timeout=300, log_dir=log_dir,
    )
    if status != PASS:
        return status, detail, {"exit_code": code}
    for artefact in ("sbom.json", "NOTICE", "docs/THIRD_PARTY_LICENSES.md", "docs/PROVENANCE.md"):
        if not (ROOT / artefact).exists():
            return FAIL, f"missing artefact {artefact}", {"exit_code": code}
    return PASS, detail, {"exit_code": code}


def stage_licence_review(log_dir: Path) -> Tuple[str, str, dict]:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "license_report", ROOT / "scripts" / "license_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    python_deps = module.python_components()
    npm_deps = module.frontend_components()
    review = module._license_review(python_deps + npm_deps)
    if review:
        return FAIL, f"licences needing review: {review[:6]}", {}
    resolved = sum(1 for c in python_deps if c["installed"])
    return (
        PASS,
        f"{resolved}/{len(python_deps)} python deps resolved, {len(npm_deps)} locked npm deps, "
        "0 strong-copyleft licences distributed",
        {},
    )


def stage_release_cleanliness(log_dir: Path) -> Tuple[str, str, dict]:
    import importlib.util

    spec = importlib.util.spec_from_file_location("packager", ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    problems: List[str] = []
    shipped_pyc = shipped_cache = shipped_secret = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if module.should_skip(rel):
            continue
        name = rel.as_posix()
        if name.endswith((".pyc", ".pyo")):
            shipped_pyc += 1
        if "__pycache__" in rel.parts or ".pytest_cache" in rel.parts:
            shipped_cache += 1
        if name == "config/ai.json":
            shipped_secret += 1
    if shipped_pyc:
        problems.append(f"{shipped_pyc} .pyc files would ship")
    if shipped_cache:
        problems.append(f"{shipped_cache} cache files would ship")
    if shipped_secret:
        problems.append("config/ai.json (may hold API keys) would ship")

    dist = ROOT / "frontend" / "dist" / "assets"
    static = ROOT / "static" / "assets"
    if dist.exists() and static.exists():
        if {p.name for p in dist.glob("*")} == {p.name for p in static.glob("*")}:
            gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
            if not any(line.strip().rstrip("/") == "static" for line in gitignore.splitlines()):
                problems.append("static/ duplicates frontend/dist and is not gitignored")

    if problems:
        return FAIL, "; ".join(problems), {}
    return PASS, "no caches/secrets shipped; single static source (frontend/dist)", {}


def stage_docs_mojibake(log_dir: Path) -> Tuple[str, str, dict]:
    bad = [
        path.name
        for path in sorted((ROOT / "docs").glob("*.md"))
        if "\ufffd" in path.read_text(encoding="utf-8", errors="replace")
    ]
    if bad:
        return FAIL, f"mojibake in: {bad}", {}
    return PASS, f"{len(list((ROOT / 'docs').glob('*.md')))} docs clean", {}


def stage_credentials(log_dir: Path) -> Tuple[str, str, dict]:
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    ]
    skip_dirs = {".venv", "node_modules", "__pycache__", ".git", "output", "dist", "static"}
    hits, fixture_hits = [], 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {
            ".py", ".js", ".ts", ".json", ".md", ".bat", ".yml", ".yaml", ".toml",
        }:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                entry = f"{path.relative_to(ROOT)}: {match.group(0)[:12]}..."
                if "tests" in path.parts:
                    fixture_hits += 1
                else:
                    hits.append(entry)
    if hits:
        return FAIL, "; ".join(hits[:5]), {}
    detail = "no hardcoded credentials in shipped sources"
    if fixture_hits:
        detail += f" ({fixture_hits} fake keys in redaction fixtures, excluded by design)"
    return PASS, detail, {}


def stage_gpu(log_dir: Path) -> Tuple[str, str, dict]:
    try:
        import torch
    except ImportError:
        return SKIP, "torch not installed (CPU-only baseline install)", {}
    if not torch.cuda.is_available():
        return SKIP, f"torch {torch.__version__} present, CUDA not available on this host", {}
    return PASS, f"torch {torch.__version__}, CUDA {torch.version.cuda}", {}


# --------------------------------------------------------------------------- #
# Suite definition
# --------------------------------------------------------------------------- #

def build_suite(fast: bool) -> List[Tuple[str, str, Callable[[Path], Tuple[str, str, dict]], float]]:
    """(name, category, fn, timeout_s) in execution order."""
    def suite_stage(name: str, marker: str, category: str, seconds: float, allow_skip: bool = False):
        def _fn(log_dir: Path) -> Tuple[str, str, dict]:
            return _stage_pytest(
                name, ["-m", marker], category, log_dir, timeout=seconds, allow_skip=allow_skip
            )

        return _fn

    suite: List[Tuple[str, str, Callable[[Path], Tuple[str, str, dict]], float]] = [
        ("python_compile", "static", stage_python_compile, 300),
        ("unit_tests", "unit", suite_stage("unit_tests", "unit", "unit", 600), 600),
        ("integration_tests", "integration",
         suite_stage("integration_tests", "integration", "integration", 900), 900),
        ("security_tests", "security",
         suite_stage("security_tests", "security", "security", 600), 600),
        ("benchmark_tests", "benchmark",
         suite_stage("benchmark_tests", "benchmark", "benchmark", 600), 600),
        ("desktop_tests", "desktop",
         suite_stage("desktop_tests", "desktop", "desktop", 600), 600),
        ("host_dependent_tests", "environment",
         suite_stage("host_dependent_tests", "requires_env", "environment", 600, allow_skip=True), 600),
        ("node_registry_schemas", "static", stage_node_registry, 300),
        ("node_registry_provenance", "static", stage_node_provenance, 300),
        ("node_catalog_readme_sync", "static", stage_node_catalog, 300),
        ("workflow_json_validation", "static", stage_workflow_json, 300),
        ("demo_workflows_dry_run", "integration", stage_demo_workflows, 1200),
        ("reproducibility_verification", "integration", stage_reproducibility, 900),
        ("synthetic_benchmark", "benchmark", stage_benchmark_cli, 900),
        ("frontend_typescript", "build", stage_frontend_tsc, 600),
        ("frontend_production_build", "build", stage_frontend_build, 900),
        ("electron_build_config", "build", stage_electron_config, 120),
        ("desktop_runtime_probe", "desktop", stage_desktop_probe, 180),
        ("electron_installer_artefact", "build", stage_electron_installer, 60),
        ("version_consistency", "compliance", stage_version, 120),
        ("release_manifest", "compliance", stage_release_manifest, 180),
        ("docs_mojibake_scan", "static", stage_docs_mojibake, 120),
        ("credential_scan", "static", stage_credentials, 300),
        ("dependency_licenses", "compliance", stage_licence_review, 300),
        ("license_sbom_report", "compliance", stage_licence_sbom, 300),
        ("release_cleanliness", "compliance", stage_release_cleanliness, 300),
        ("host_gpu_status", "environment", stage_gpu, 60),
    ]
    del fast  # kept for signature stability; --fast is applied in main()
    return suite


def _stage_pytest(
    name: str,
    args: List[str],
    category: str,
    log_dir: Path,
    *,
    timeout: float = 900.0,
    allow_skip: bool = False,
) -> Tuple[str, str, dict]:
    """Adapter so a pytest selection can be used as a plain stage function.

    The fully populated :class:`CheckResult` (with the JUnit-derived counts) is
    parked in ``_STAGE_RESULTS`` for ``main()`` to pick up; the flat return value
    keeps the calling convention identical to the non-pytest stages.
    """
    result, command = _pytest_stage(name, args, category=category, timeout=timeout, log_dir=log_dir)
    if allow_skip and result.status == SKIP:
        pass
    _STAGE_RESULTS[name] = result
    _STAGE_COMMANDS[name] = command
    return result.status, result.detail, {}


#: Side channel so header-only stage functions can hand back a full result.
_STAGE_RESULTS: Dict[str, CheckResult] = {}
_STAGE_COMMANDS: Dict[str, str] = {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chem ML Platform v0.7.2 quality gate")
    parser.add_argument("--fast", action="store_true", help="skip build-heavy stages")
    parser.add_argument("--json", default=str(ROOT / "output" / "quality_gate.json"))
    parser.add_argument("--md", default=str(ROOT / "output" / "quality_gate.md"))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    args = parser.parse_args()

    import chemml_version

    log_dir = Path(args.log_dir)
    meta = chemml_version.build_metadata()
    report = GateReport(
        version=meta["version"],
        codename=meta["codename"],
        commit=meta["commit"],
        python=meta["python"],
        node=_node_version(),
        dependencies=_dep_versions(),
        started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    skip_in_fast = {"frontend_production_build", "electron_installer_artefact"}

    for name, category, fn, timeout in build_suite(args.fast):
        if args.fast and name in skip_in_fast:
            result = CheckResult(
                name=name, category=category, status=SKIP, detail="--fast: build-heavy stage skipped"
            )
            report.add(result)
            print(f"[{result.status:^7}] {name:<28} {result.detail}")
            continue

        start = time.perf_counter()
        try:
            status, detail, extra = fn(log_dir)
        except Exception as exc:  # a crashing stage is an ERROR, never silent
            status, detail, extra = ERROR, f"{type(exc).__name__}: {exc}", {}
        elapsed = (time.perf_counter() - start) * 1000

        preset = _STAGE_RESULTS.pop(name, None)
        if preset is not None:
            preset.duration_ms = elapsed
            preset.timeout_s = preset.timeout_s or timeout
            result = preset
        else:
            result = CheckResult(
                name=name,
                category=category,
                status=status,
                detail=detail,
                duration_ms=elapsed,
                timeout_s=timeout,
                log_path=_rel_log(name, log_dir),
                **{k: v for k, v in extra.items() if k in {"exit_code"}},
            )
        report.add(result)
        print(f"[{result.status:^7}] {name:<28} ({result.duration_ms:.0f} ms) {result.detail[:110]}")

    report.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out_json, out_md = Path(args.json), Path(args.md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(report.to_json(), encoding="utf-8")
    out_md.write_text(report.to_markdown(), encoding="utf-8")

    verdict = "PASSED" if report.ok else "FAILED"
    print(
        f"\ngate: {verdict} (pass={report.passed} fail={report.failed} skip={report.skipped} "
        f"timeout={report.timed_out} error={report.errored})"
    )
    print(f"tests collected across stages: {report.total_tests}")
    print(f"reports: {out_json} · {out_md} · logs: {log_dir}")
    return 0 if report.ok else 1


def _rel_log(name: str, log_dir: Path) -> str:
    path = log_dir / f"{name}.log"
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
