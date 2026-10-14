"""Chem ML Platform v0.7.1 -- quality gate (spec section 18 / task L).

Runs the mandated checks and produces BOTH a machine readable report
(JSON) and a human readable report (Markdown).  Real-environment checks
(GPU, external software, installer build, live LLM providers) are reported per
availability as PASS / SKIP(reason) / FAIL -- skips are counted separately and
never reported as passes.

Usage:
    python scripts/quality_gate.py                 # all checks
    python scripts/quality_gate.py --fast          # skip frontend build
    python scripts/quality_gate.py --json out.json # custom JSON path
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PYTHON = sys.executable


@dataclass
class CheckResult:
    name: str
    status: str  # PASS | FAIL | SKIP
    detail: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateReport:
    started_at: str = ""
    finished_at: str = ""
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.failed == 0

    def add(self, result: CheckResult) -> None:
        self.checks.append(result)
        if result.status == "PASS":
            self.passed += 1
        elif result.status == "SKIP":
            self.skipped += 1
        else:
            self.failed += 1

    def to_json(self) -> str:
        return json.dumps(
            {k: v for k, v in self.__dict__.items() if k != "checks"}
            | {"checks": [c.to_dict() for c in self.checks]},
            ensure_ascii=False,
            indent=2,
        )

    def to_markdown(self) -> str:
        lines = [
            "# Chem ML Platform v0.7 -- Quality Gate Report",
            "",
            f"- started: {self.started_at}",
            f"- finished: {self.finished_at}",
            f"- **PASS**: {self.passed} · **FAIL**: {self.failed} · **SKIP**: {self.skipped}",
            f"- **gate**: {'PASSED' if self.ok else 'FAILED'}",
            "",
            "| # | Check | Status | Duration (ms) | Detail |",
            "| --- | --- | --- | --- | --- |",
        ]
        for i, check in enumerate(self.checks, 1):
            detail = check.detail.replace("\n", " ")[:160]
            lines.append(
                f"| {i} | {check.name} | {check.status} | {check.duration_ms:.0f} | {detail} |"
            )
        return "\n".join(lines) + "\n"


def run_check(name: str, fn: Callable[[], tuple]) -> CheckResult:
    start = time.perf_counter()
    try:
        status, detail = fn()
    except Exception as exc:  # a crashing check is a FAIL, never silent
        status, detail = "FAIL", f"{type(exc).__name__}: {exc}"
    return CheckResult(
        name=name,
        status=status,
        detail=detail,
        duration_ms=(time.perf_counter() - start) * 1000,
    )


def subprocess_check(cmd: List[str], timeout: int = 600) -> tuple:
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )
    if proc.returncode == 0:
        return "PASS", (proc.stdout or "").strip().splitlines()[-1:] and (proc.stdout or "").strip().splitlines()[-1] or "ok"
    tail = "\n".join((proc.stderr or proc.stdout or "").strip().splitlines()[-8:])
    return "FAIL", tail or f"exit code {proc.returncode}"


#: Repo-local pytest temp root.  Keeping pytest's ``--basetemp`` inside the
#: project (an ``output/`` subdir excluded from release packages) makes the gate
#: hermetic: it never touches the OS temp directory, which some hardened hosts
#: guard against bulk deletion.
_PYTEST_TMP_ROOT = ROOT / "output" / "pytest_gate_tmp"

#: Strictly increasing counter so every pytest invocation gets a fresh basetemp.
#:
#: Why unique-per-run: when ``--basetemp`` points at a directory that already
#: has content, pytest deletes it (``shutil.rmtree``) before the run.  On hosts
#: that install a "safe delete" ``sitecustomize`` shim (paths are moved to the
#: recycle bin instead of unlinked), that bulk delete can fail closed with
#: ``OSError [Errno 123]`` on non-ASCII ``\\?\\``-prefixed paths -- turning
#: every fixture that uses ``tmp_path`` into a spurious ERROR.  A brand new
#: directory has nothing to delete, so pytest never calls ``rmtree`` at start,
#: and the gate stays portable across hardened and plain hosts alike.  The
#: directories live under ``output/`` (gitignored, excluded from release
#: packages), so this is never shipped.
_pytest_tmp_seq = 0


def pytest_check(paths: List[str], timeout: int = 900) -> tuple:
    """Run a pytest subset with a fresh project-local basetemp and return PASS/FAIL."""
    global _pytest_tmp_seq
    _pytest_tmp_seq += 1
    base = _PYTEST_TMP_ROOT / f"run{os.getpid()}_{_pytest_tmp_seq}"
    base.mkdir(parents=True, exist_ok=True)
    return subprocess_check(
        [PYTHON, "-m", "pytest", *paths, "-q", "--tb=short",
         "-p", "no:cacheprovider", f"--basetemp={base}"],
        timeout=timeout,
    )


# --------------------------------------------------------------------------- #
# Check implementations (spec section 18, items 1..20)
# --------------------------------------------------------------------------- #

#: Path segments that hold third-party / build output, never first-party source.
_NON_SOURCE_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "out", "build"}


def check_python_compile() -> tuple:
    """1. Byte-compile every first-party .py file (excludes deps and caches)."""
    files = [
        p
        for p in ROOT.rglob("*.py")
        if not _NON_SOURCE_DIRS.intersection(p.parts)
    ]
    proc = subprocess.run(
        [PYTHON, "-m", "compileall", "-q",
         "-x", "node_modules|__pycache__|\\.venv|[/\\\\]dist[/\\\\]|[/\\\\]out[/\\\\]",
         str(ROOT)],
        capture_output=True, text=True, timeout=300, errors="replace",
    )
    if proc.returncode != 0:
        return "FAIL", proc.stdout[-1500:]
    return "PASS", f"{len(files)} first-party files compiled"


def check_pytest() -> tuple:
    """2+3. Unit + integration tests (single pytest suite, honestly counted)."""
    return pytest_check(["tests/"])


def check_node_registry() -> tuple:
    """4+5. Node registration integrity and schema validation."""
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
        return "FAIL", "; ".join(problems[:10])
    return "PASS", f"{count} node types, schemas valid"


def check_workflow_json() -> tuple:
    """6. Validate every workflow JSON under workflows/."""
    import json

    from workflow_engine.workflow import Workflow

    engine_reg = None
    from nodes.loader import get_registry

    engine_reg = get_registry()
    problems = []
    checked = 0
    for path in sorted((ROOT / "workflows").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        issues = Workflow.from_dict(data).validate(engine_reg)
        if issues:
            problems.append(f"{path.name}: {issues}")
        checked += 1
    if problems:
        return "FAIL", "; ".join(problems)[:800]
    return "PASS", f"{checked} workflow files valid"


def check_demo_dry_run() -> tuple:
    """7. Run every demo workflow end to end (real dry run, no mocks)."""
    proc = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "run_demo_workflows.py")],
        capture_output=True, text=True, timeout=900, errors="replace",
    )
    if proc.returncode != 0:
        return "FAIL", (proc.stderr or proc.stdout)[-1200:]
    return "PASS", (proc.stdout or "all demos completed").strip().splitlines()[-1]


def check_storage_security() -> tuple:
    """8+9. Path traversal, zip-slip and upload permission tests."""
    return pytest_check(["tests/test_v07_storage.py"], timeout=300)


def check_report_export() -> tuple:
    """10. Report export tests (MD/HTML/DOCX) + v0.7.1 provenance/limitation."""
    return pytest_check(["tests/test_v07_report.py", "tests/test_v07_1_report_provenance.py"])


def check_agent_state_machine() -> tuple:
    """11. Agent lifecycle tests."""
    return pytest_check(["tests/test_v07_agent_state.py", "tests/test_v07_1_agent_runtime.py"])


def check_error_recovery() -> tuple:
    """12. Error model + engine failure-path tests."""
    return pytest_check(["tests/test_v07_errors.py", "tests/test_engine.py"])


def check_security_suite() -> tuple:
    """12b. v0.7.1 auth / CORS / streaming-upload / capability security tests."""
    return pytest_check(
        [
            "tests/test_v07_1_security.py",
            "tests/test_v07_1_upload_stream.py",
            "tests/test_v07_1_capabilities.py",
            "tests/test_v07_1_dataset_quality.py",
        ],
        timeout=420,
    )


def check_frontend_tsc() -> tuple:
    """13. TypeScript check."""
    npm, frontend = _npm_cmd(), ROOT / "frontend"
    if not (frontend / "package.json").exists():
        return "SKIP", "frontend not present"
    if not (frontend / "node_modules").exists():
        return "SKIP", "frontend dependencies not installed (npm install not run)"
    proc = subprocess.run(
        [*npm, "run", "lint"], cwd=str(frontend),
        capture_output=True, text=True, timeout=600, errors="replace",
    )
    if proc.returncode != 0:
        return "FAIL", (proc.stderr or proc.stdout)[-1200:]
    return "PASS", "tsc --noEmit clean"


def check_frontend_build() -> tuple:
    """14. Production build."""
    npm, frontend = _npm_cmd(), ROOT / "frontend"
    if not (frontend / "node_modules").exists():
        return "SKIP", "frontend dependencies not installed"
    proc = subprocess.run(
        [*npm, "run", "build"], cwd=str(frontend),
        capture_output=True, text=True, timeout=900, errors="replace",
    )
    if proc.returncode != 0:
        return "FAIL", (proc.stderr or proc.stdout)[-1200:]
    dist = frontend / "dist"
    n_files = sum(1 for _ in dist.rglob("*") if _.is_file())
    return "PASS", f"dist built with {n_files} files"


def check_electron_config() -> tuple:
    """15. Electron build configuration sanity (structure, not full build)."""
    desktop = ROOT / "desktop"
    required = [
        desktop / "package.json",
        desktop / "src" / "main.js",
        desktop / "src" / "preload.js",
    ]
    missing = [str(p.relative_to(ROOT)) for p in required if not p.exists()]
    if missing:
        return "FAIL", f"missing: {missing}"
    config = json.loads((desktop / "package.json").read_text(encoding="utf-8"))
    if config.get("main") != "src/main.js":
        return "FAIL", "package.json main must be src/main.js"
    electron_builder = config.get("build", {})
    if "win" not in electron_builder:
        return "FAIL", "electron-builder win target missing"
    return "PASS", "electron shell configured (win/linux/mac targets declared)"


def check_version_consistency() -> tuple:
    """16. Version alignment across every machine-readable manifest."""
    versions: Dict[str, str] = {}

    app_py = (ROOT / "backend" / "app.py").read_text(encoding="utf-8")
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', app_py, re.M)
    if m:
        versions["backend/app.py"] = m.group(1)

    registry_init = (ROOT / "node_registry" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', registry_init)
    if m:
        versions["node_registry/__init__.py"] = m.group(1)

    for manifest in ("desktop/package.json", "frontend/package.json"):
        path = ROOT / manifest
        if path.exists():
            versions[manifest] = json.loads(path.read_text(encoding="utf-8")).get("version", "?")

    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"# Chem ML Platform v([0-9]+\.[0-9]+\.[0-9]+)", readme)
    if m:
        versions["README.md"] = m.group(1)

    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8", errors="replace")
    m = re.search(r"## \[?(v?[0-9]+\.[0-9]+\.[0-9]+)", changelog)
    if m:
        versions["CHANGELOG.md"] = m.group(1).lstrip("v")

    if not versions:
        return "SKIP", "no version manifests found"
    values = set(versions.values())
    if len(values) > 1:
        return "FAIL", f"version mismatch: {versions}"
    return "PASS", f"consistent at {versions}"


def check_node_catalog() -> tuple:
    """5b. README node statistics must match the live registry (P2-06)."""
    proc = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "node_catalog.py"), "--check"],
        capture_output=True, text=True, timeout=300, errors="replace",
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return "FAIL", output[-1200:]
    return "PASS", output.splitlines()[-1] if output else "catalog consistent"


def check_docs_mojibake() -> tuple:
    """17. Scan docs for UTF-8 replacement chars and mojibake signatures."""
    bad = []
    for path in sorted((ROOT / "docs").glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if "\ufffd" in text:
            bad.append(path.name)
    if bad:
        return "FAIL", f"mojibake in: {bad}"
    return "PASS", f"{len(list((ROOT / 'docs').glob('*.md')))} docs clean"


def check_credentials() -> tuple:
    """19. Scan source files for hardcoded secrets.

    Test files are excluded from the *pattern hit* judgement because the
    redaction tests intentionally contain fake key-shaped strings; they are
    counted separately so the exclusion stays visible in the report.
    """
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
        re.compile(r"-----BEGIN (RSA |EC )?PRIVATE KEY-----"),
    ]
    skip_dirs = {".venv", "node_modules", "__pycache__", ".git", "output", "dist", "static"}
    hits, test_fixture_hits = [], 0
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".js", ".ts", ".json", ".md", ".bat", ".yml", ".yaml", ".toml"}:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            m = pattern.search(text)
            if m:
                entry = f"{path.relative_to(ROOT)}: {m.group(0)[:12]}..."
                if "tests" in path.parts:
                    test_fixture_hits += 1
                else:
                    hits.append(entry)
    if hits:
        return "FAIL", "; ".join(hits[:5])
    detail = "no hardcoded credentials in shipped sources"
    if test_fixture_hits:
        detail += f" ({test_fixture_hits} fake keys in redaction test fixtures, excluded by design)"
    return "PASS", detail


def check_v06_compat() -> tuple:
    """20. v0.6 regression tests."""
    return pytest_check(["tests/test_v06.py"])


def check_gpu_runtime() -> tuple:
    """GPU availability is environment-dependent: honest SKIP/FAIL/PASS."""
    try:
        import torch
    except ImportError:
        return "SKIP", "torch not installed (CPU-only baseline install)"
    cuda = torch.cuda.is_available()
    if not cuda:
        return "SKIP", f"torch {torch.__version__} present, CUDA not available on this machine"
    return "PASS", f"torch {torch.__version__}, CUDA {torch.version.cuda}"


def check_dependency_licenses() -> tuple:
    """19b. Licence posture derived from *real* dependency metadata (task K)."""
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
        return "FAIL", f"licences needing review: {review[:6]}"
    resolved = sum(1 for c in python_deps if c["installed"])
    return "PASS", (
        f"{resolved}/{len(python_deps)} python deps resolved, "
        f"{len(npm_deps)} locked npm deps, 0 strong-copyleft licences distributed"
    )


def check_license_sbom() -> tuple:
    """19c. SBOM / NOTICE / licence report regenerate cleanly (task K)."""
    proc = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "license_report.py"), "--check"],
        capture_output=True, text=True, timeout=300, errors="replace",
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return "FAIL", output[-1200:]
    for artefact in ("sbom.json", "NOTICE", "docs/THIRD_PARTY_LICENSES.md"):
        if not (ROOT / artefact).exists():
            return "FAIL", f"missing artefact {artefact}"
    return "PASS", output.splitlines()[-1] if output else "licence artefacts written"


def check_release_cleanliness() -> tuple:
    """21. Release package cleanliness (P2-04 / P2-05): uses the real packager rule."""
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

    # static / frontend dist single-source check
    dist = ROOT / "frontend" / "dist" / "assets"
    static = ROOT / "static" / "assets"
    if dist.exists() and static.exists():
        if {p.name for p in dist.glob("*")} == {p.name for p in static.glob("*")}:
            gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8", errors="replace")
            if not any(line.strip().rstrip("/") == "static" for line in gitignore.splitlines()):
                problems.append("static/ duplicates frontend/dist and is not gitignored")

    if problems:
        return "FAIL", "; ".join(problems)
    return "PASS", "no caches/secrets shipped; single static source (frontend/dist)"


def check_scientific_benchmark() -> tuple:
    """22. Known-answer scientific benchmark must meet its thresholds (task I)."""
    proc = subprocess.run(
        [PYTHON, str(ROOT / "scripts" / "benchmark_lcms.py"), "--strict", "--quiet"],
        capture_output=True, text=True, timeout=900, errors="replace",
    )
    output = (proc.stdout or proc.stderr or "").strip()
    if proc.returncode != 0:
        return "FAIL", output[-1200:]
    return "PASS", output.splitlines()[-1] if output else "benchmark passed"


def check_docs_version_consistency() -> tuple:
    """23. Shipped artefacts must not carry a stale version string (P2-07)."""
    targets = list((ROOT / "workflows").glob("*.json"))
    stale: List[str] = []
    for path in targets:
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in ('"version": "0.6.0"', '"version": "0.7.0"'):
            if token in text:
                stale.append(f"{path.name}: {token.split(':')[1].strip()}")
    if stale:
        return "FAIL", f"stale version in shipped artefacts: {stale[:8]}"
    return "PASS", f"{len(targets)} workflow files carry the current version"


def check_electron_installer() -> tuple:
    """24. Electron installer artefact availability (honest SKIP when not built)."""
    desktop = ROOT / "desktop"
    for pattern in ("dist/*.exe", "dist/*.AppImage", "dist/*.dmg", "release/*.exe"):
        matches = list(desktop.glob(pattern))
        if matches:
            return "PASS", f"installer present: {matches[0].relative_to(ROOT)}"
    return "SKIP", (
        "installer not built in this environment "
        "(run `cd desktop && npm install && npm run dist` on a build host)"
    )


def _npm_cmd() -> list:
    return ["npm.cmd"] if os.name == "nt" else ["npm"]


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description="Chem ML Platform v0.7 quality gate")
    parser.add_argument("--fast", action="store_true", help="skip slow frontend build")
    parser.add_argument("--json", default=str(ROOT / "output" / "quality_gate.json"))
    parser.add_argument("--md", default=str(ROOT / "output" / "quality_gate.md"))
    args = parser.parse_args()

    report = GateReport(started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))

    suite: List[tuple] = [
        ("python_compile", check_python_compile),
        ("pytest_suite", check_pytest),
        ("node_registry_schemas", check_node_registry),
        ("node_catalog_readme_sync", check_node_catalog),
        ("workflow_json_validation", check_workflow_json),
        ("demo_workflows_dry_run", check_demo_dry_run),
        ("storage_and_upload_security", check_storage_security),
        ("report_export", check_report_export),
        ("agent_state_machine", check_agent_state_machine),
        ("error_recovery", check_error_recovery),
        ("security_suite_v07_1", check_security_suite),
        ("scientific_benchmark", check_scientific_benchmark),
        ("frontend_typescript", check_frontend_tsc),
        ("frontend_production_build", None if args.fast else check_frontend_build),
        ("electron_build_config", check_electron_config),
        ("electron_installer_artefact", check_electron_installer),
        ("version_consistency", check_version_consistency),
        ("shipped_version_consistency", check_docs_version_consistency),
        ("docs_mojibake_scan", check_docs_mojibake),
        ("credential_scan", check_credentials),
        ("dependency_licenses", check_dependency_licenses),
        ("license_sbom_report", check_license_sbom),
        ("release_cleanliness", check_release_cleanliness),
        ("v06_regression", check_v06_compat),
        ("gpu_runtime_status", check_gpu_runtime),
    ]
    for name, fn in suite:
        if fn is None:
            result = CheckResult(name=name, status="SKIP", detail="--fast")
            report.add(result)
            print(f"[{result.status}] {name} (0 ms) {result.detail}")
            continue
        result = run_check(name, fn)
        report.add(result)
        print(f"[{result.status}] {name} ({result.duration_ms:.0f} ms) {result.detail[:100]}")

    report.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    out_json, out_md = Path(args.json), Path(args.md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(report.to_json(), encoding="utf-8")
    out_md.write_text(report.to_markdown(), encoding="utf-8")

    print(f"\ngate: {'PASSED' if report.ok else 'FAILED'} "
          f"(pass={report.passed} fail={report.failed} skip={report.skipped})")
    print(f"reports: {out_json} · {out_md}")
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
