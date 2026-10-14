"""Chem ML Platform v0.7.2 -- staged release pipeline (spec section 9).

The task book is explicit about *why* this exists:

    "所有阶段应输出独立结果，避免一个汇总脚本在子进程失败时仍生成看似成功的总报告。"

So this is deliberately not "one big script that prints PASS".  Every stage runs
as its own process with its own exit code, its own timeout, its own full log and
its own declared output artefacts.  The aggregate verdict is computed from those
exit codes and can only ever be *as optimistic as the worst stage*: a stage that
times out or crashes makes the pipeline fail, and there is no code path that
turns a non-zero exit into a success.

Stages follow section 9 of the spec, in order:

    1  source format & static checks
    2  python + frontend dependency install
    3  unit tests
    4  integration tests
    5  security tests
    6  scientific benchmark
    7  licence & provenance check
    8  SBOM generation
    9  frontend production build
   10  Electron installer build
   11  clean-environment install & end-to-end test
   12  release manifest, checksums and report generation

Stages that cannot run on the current host (no network, no installer toolchain,
non-Windows) report ``SKIP`` with the reason *and* the exact command a release
engineer must run instead.  They never report PASS.

Usage::

    python scripts/ci_pipeline.py                  # all stages that apply
    python scripts/ci_pipeline.py --only 3 4 5     # a subset, by stage number
    python scripts/ci_pipeline.py --list           # show the stage table
    python scripts/ci_pipeline.py --json out.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Reuse the gate's process harness so both tools classify identically.
#: The module must be registered in ``sys.modules`` *before* it executes:
#: ``@dataclass`` looks its own module up by name to resolve annotations, and a
#: module that only exists as a local variable makes it raise a bare
#: ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
_spec = importlib.util.spec_from_file_location("quality_gate", ROOT / "scripts" / "quality_gate.py")
qg = importlib.util.module_from_spec(_spec)
sys.modules["quality_gate"] = qg
try:
    _spec.loader.exec_module(qg)
except BaseException:
    sys.modules.pop("quality_gate", None)
    raise

from chemml_version import VERSION, __codename__, build_metadata  # noqa: E402

PYTHON = sys.executable
LOG_DIR = ROOT / "output" / "ci_logs"
DEFAULT_JSON = ROOT / "output" / "ci_pipeline.json"
DEFAULT_MD = ROOT / "output" / "ci_pipeline.md"

PASS, FAIL, TIMEOUT, SKIP, ERROR = qg.PASS, qg.FAIL, qg.TIMEOUT, qg.SKIP, qg.ERROR
FAILING = qg.FAILING


@dataclass
class Stage:
    number: int
    title: str
    category: str
    command: List[str]
    timeout: float
    artifacts: List[str] = field(default_factory=list)
    required: bool = True
    #: Returned instead of a command when the stage cannot run on this host.
    skip_reason: str = ""
    manual_command: str = ""
    #: Additional commands belonging to the same stage, each run as its own
    #: process with its own exit code and log.  A stage fails if *any* of them
    #: fails, so one command can never mask another's failure.
    extra_commands: List[List[str]] = field(default_factory=list)


@dataclass
class StageResult:
    number: int
    title: str
    category: str
    status: str
    detail: str = ""
    command: str = ""
    exit_code: Optional[int] = None
    timeout_s: float = 0.0
    duration_ms: float = 0.0
    log_path: str = ""
    artifacts: List[str] = field(default_factory=list)
    artifacts_present: List[str] = field(default_factory=list)
    artifacts_missing: List[str] = field(default_factory=list)
    manual_command: str = ""
    #: One entry per command in the stage, including the primary one, so a
    #: reader can see *which* command failed rather than a merged verdict.
    commands: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _npm() -> List[str]:
    return ["npm.cmd"] if os.name == "nt" else ["npm"]


def _has_frontend_deps() -> bool:
    return (ROOT / "frontend" / "node_modules").exists()


def _has_desktop_deps() -> bool:
    return (ROOT / "desktop" / "node_modules").exists()


def _electron_builder_available() -> bool:
    return (ROOT / "desktop" / "node_modules" / "electron-builder").exists()


#: Per-run pytest temp roots.  Without ``--basetemp`` pytest garbage-collects
#: stale numbered directories in the *global* temp root, and on a hardened
#: host that bulk delete fails closed -- a fully green test run then exits
#: non-zero (observed: one garbage directory holding 856 files, blocked by the
#: safe-delete shim).  The quality gate already uses a per-run root for the
#: same reason; the CI pipeline must not depend on shared temp state either.
_PYTEST_TMP_ROOT = ROOT / "output" / "ci_pytest_tmp"
_pytest_tmp_seq = 0


def _pytest_command(marker: str) -> List[str]:
    global _pytest_tmp_seq
    _pytest_tmp_seq += 1
    base = _PYTEST_TMP_ROOT / f"run{os.getpid()}_{_pytest_tmp_seq}"
    base.mkdir(parents=True, exist_ok=True)
    return [
        PYTHON,
        "-m",
        "pytest",
        "-m",
        marker,
        "-q",
        "--tb=short",
        "-p",
        "no:cacheprovider",
        f"--basetemp={base}",
    ]


def _reproducible_command(command: List[str]) -> str:
    """The command as a reader can re-run it: machine-local paths stripped."""
    return " ".join(part for part in command if not part.startswith("--basetemp="))


def build_stages() -> List[Stage]:
    """The 12 declared stages, in spec order."""
    stages: List[Stage] = []

    stages.append(
        Stage(
            number=1,
            title="源码格式与静态检查",
            category="static",
            command=[PYTHON, str(ROOT / "scripts" / "quality_gate.py"), "--fast"],
            timeout=1800,
            artifacts=["output/quality_gate.json", "output/quality_gate.md"],
            manual_command="python scripts/quality_gate.py --fast",
        )
    )

    stages.append(
        Stage(
            number=2,
            title="Python 与前端依赖安装",
            category="install",
            command=[PYTHON, "-m", "pip", "install", "-r", "requirements.txt"],
            timeout=3600,
            manual_command="python -m pip install -r requirements.txt && cd frontend && npm ci",
        )
    )

    stages.append(
        Stage(
            number=3,
            title="单元测试",
            category="unit",
            command=_pytest_command("unit"),
            timeout=900,
            manual_command="python -m pytest -m unit",
        )
    )
    stages.append(
        Stage(
            number=4,
            title="集成测试",
            category="integration",
            command=_pytest_command("integration"),
            timeout=1800,
            manual_command="python -m pytest -m integration",
        )
    )
    stages.append(
        Stage(
            number=5,
            title="安全测试",
            category="security",
            command=_pytest_command("security"),
            timeout=900,
            manual_command="python -m pytest -m security",
        )
    )
    stages.append(
        Stage(
            number=6,
            title="科研基准测试",
            category="benchmark",
            command=[PYTHON, str(ROOT / "scripts" / "benchmark_lcms.py"), "--strict"],
            # Second, independently recorded command: accuracy against known
            # answers is not the same claim as "a deterministic workflow
            # repeats".  Running it as a separate command (not folded into one
            # script) keeps its own exit code and log, per spec section 9.
            extra_commands=[
                [
                    PYTHON, str(ROOT / "scripts" / "verify_reproducibility.py"),
                    "-w", "workflows/04_quantum_chemistry_profiling.json",
                    "-w", "workflows/06_scientific_foundation_models.json",
                    "--repeat", "2",
                    "--json", str(ROOT / "output" / "reproducibility.json"),
                ]
            ],
            timeout=1200,
            artifacts=[
                "docs/V07_2_SYNTHETIC_BENCHMARK.md",
                "output/reproducibility.json",
            ],
            manual_command=(
                "python scripts/benchmark_lcms.py --strict && "
                "python scripts/verify_reproducibility.py --repeat 2 "
                "--json output/reproducibility.json"
            ),
        )
    )
    stages.append(
        Stage(
            number=7,
            title="许可证与来源检查",
            category="compliance",
            command=[PYTHON, str(ROOT / "scripts" / "license_report.py"), "--check"],
            timeout=600,
            artifacts=["docs/THIRD_PARTY_LICENSES.md", "docs/PROVENANCE.md", "NOTICE"],
            manual_command="python scripts/license_report.py --check",
        )
    )
    stages.append(
        Stage(
            number=8,
            title="SBOM 生成",
            category="compliance",
            command=[PYTHON, str(ROOT / "scripts" / "license_report.py"), "--write"],
            timeout=600,
            artifacts=["sbom.json"],
            manual_command="python scripts/license_report.py --write",
        )
    )
    stages.append(
        Stage(
            number=9,
            title="前端生产构建",
            category="build",
            command=[*_npm(), "run", "build"],
            timeout=1800,
            artifacts=["frontend/dist/index.html"],
            manual_command="cd frontend && npm run build",
        )
    )

    installer_ready = os.name == "nt" and _electron_builder_available()
    stages.append(
        Stage(
            number=10,
            title="Electron 安装包构建",
            category="build",
            command=[*_npm(), "run", "build"],
            timeout=3600,
            artifacts=[f"desktop/dist/Chem ML Platform Setup {VERSION}.exe"],
            required=True,
            skip_reason="" if installer_ready else (
                "installer toolchain unavailable on this host "
                f"(windows={os.name == 'nt'}, electron-builder={_electron_builder_available()}); "
                "run `cd desktop && npm install && npm run build` on a Windows x64 build host"
            ),
            manual_command="cd desktop && npm install && npm run build",
        )
    )

    clean_env_record = ROOT / "docs" / "V07_2_CLEAN_ENV_TEST.md"
    stages.append(
        Stage(
            number=11,
            title="干净环境安装与端到端测试",
            category="e2e",
            command=[PYTHON, str(ROOT / "scripts" / "clean_env_check.py")],
            timeout=900,
            artifacts=["docs/V07_2_CLEAN_ENV_TEST.md"],
            required=True,
            skip_reason="" if clean_env_record.exists() else (
                "no clean-environment test record yet; run scripts/clean_env_check.py on a clean VM"
            ),
            manual_command="python scripts/clean_env_check.py",
        )
    )

    stages.append(
        Stage(
            number=12,
            title="发布清单、校验哈希与报告生成",
            category="release",
            command=[PYTHON, str(ROOT / "scripts" / "release_manifest.py")],
            timeout=900,
            artifacts=["docs/RELEASE_MANIFEST.md", "docs/RELEASE_MANIFEST.json", "SHA256SUMS"],
            manual_command="python scripts/release_manifest.py",
        )
    )
    return stages


def run_stage(stage: Stage) -> StageResult:
    """Run one stage and verify its declared artefacts actually exist."""
    if stage.skip_reason:
        return StageResult(
            number=stage.number,
            title=stage.title,
            category=stage.category,
            status=SKIP,
            detail=stage.skip_reason,
            timeout_s=stage.timeout,
            manual_command=stage.manual_command,
        )

    name = f"stage{stage.number:02d}"
    cwd = ROOT / "frontend" if stage.number == 9 else (
        ROOT / "desktop" if stage.number == 10 else ROOT
    )

    # Never let a "skip" hide behind a missing tool: report it as SKIP, with the
    # manual command, rather than executing something guaranteed to fail.
    if stage.number == 2 and not _network_available():
        return StageResult(
            number=stage.number,
            title=stage.title,
            category=stage.category,
            status=SKIP,
            detail="no network access from this environment; dependencies must already be installed",
            timeout_s=stage.timeout,
            manual_command=stage.manual_command,
        )
    if stage.number == 9 and not _has_frontend_deps():
        return StageResult(
            number=stage.number,
            title=stage.title,
            category=stage.category,
            status=SKIP,
            detail="frontend/node_modules absent -- run `cd frontend && npm ci` first",
            timeout_s=stage.timeout,
            manual_command=stage.manual_command,
        )
    if stage.number == 10 and not _has_desktop_deps():
        return StageResult(
            number=stage.number,
            title=stage.title,
            category=stage.category,
            status=SKIP,
            detail="desktop/node_modules absent -- run `cd desktop && npm install` first",
            timeout_s=stage.timeout,
            manual_command=stage.manual_command,
        )

    started = time.perf_counter()
    status, exit_code, detail = qg._run(
        name, stage.command, cwd=cwd, timeout=stage.timeout, log_dir=LOG_DIR
    )
    elapsed = (time.perf_counter() - started) * 1000

    result = StageResult(
        number=stage.number,
        title=stage.title,
        category=stage.category,
        status=status,
        detail=detail,
        command=_reproducible_command(stage.command),
        exit_code=exit_code,
        timeout_s=stage.timeout,
        duration_ms=elapsed,
        log_path=str((LOG_DIR / f"{name}.log").relative_to(ROOT)),
        artifacts=list(stage.artifacts),
        manual_command=stage.manual_command,
    )
    result.commands.append(
        {
            "command": _reproducible_command(stage.command),
            "status": status,
            "exit_code": exit_code,
            "log": result.log_path,
        }
    )

    # Each additional command runs as its own process, keeps its own log, and
    # can fail the stage on its own.  This is the spec's "all stages must emit
    # independent results" rule applied *inside* a stage.
    for index, extra in enumerate(stage.extra_commands, start=1):
        extra_name = f"{name}_{index}"
        extra_started = time.perf_counter()
        extra_status, extra_code, extra_detail = qg._run(
            extra_name, extra, cwd=cwd, timeout=stage.timeout, log_dir=LOG_DIR
        )
        extra_log = str((LOG_DIR / f"{extra_name}.log").relative_to(ROOT))
        result.commands.append(
            {
                "command": " ".join(extra),
                "status": extra_status,
                "exit_code": extra_code,
                "log": extra_log,
            }
        )
        result.duration_ms += (time.perf_counter() - extra_started) * 1000
        if extra_status != PASS:
            result.status = extra_status
            result.detail = f"`{' '.join(extra[:2])}` -> {extra_detail}"

    # Independent artefact verification: a stage that exits 0 without producing
    # its declared output has NOT succeeded.
    for artifact in stage.artifacts:
        if (ROOT / artifact).exists():
            result.artifacts_present.append(artifact)
        else:
            result.artifacts_missing.append(artifact)
    if result.status == PASS and result.artifacts_missing:
        result.status = FAIL
        result.detail = "exit 0 but declared artefacts missing: " + ", ".join(result.artifacts_missing)
    return result


def _network_available() -> bool:
    """Conservative connectivity probe -- only stage 2 needs it."""
    if os.environ.get("CHEMML_OFFLINE") == "1":
        return False
    try:
        import socket

        socket.create_connection(("pypi.org", 443), timeout=4).close()
        return True
    except OSError:
        return False


def _markdown(results: List[StageResult], meta: dict) -> str:
    passed = sum(1 for r in results if r.status == PASS)
    failed = sum(1 for r in results if r.status == FAIL)
    timed_out = sum(1 for r in results if r.status == TIMEOUT)
    errored = sum(1 for r in results if r.status == ERROR)
    skipped = sum(1 for r in results if r.status == SKIP)
    ok = failed == 0 and timed_out == 0 and errored == 0
    lines = [
        f"# Chem ML Platform v{meta['version']} — Release Pipeline",
        "",
        f"- **codename**: {meta['codename']}",
        f"- **commit**: `{meta['commit']}`",
        f"- **python**: {meta['python']}",
        f"- **started / finished**: {meta['started_at']} → {meta['finished_at']}",
        f"- **PASS**: {passed} · **FAIL**: {failed} · **TIMEOUT**: {timed_out} "
        f"· **ERROR**: {errored} · **SKIP**: {skipped}",
        f"- **pipeline**: {'PASSED' if ok else 'FAILED'}",
        "",
        "> 每个阶段独立执行、独立退出码、独立日志。任一阶段非零退出即使流水线失败；",
        "> 不存在把子进程失败渲染为成功总报告的代码路径。",
        "",
        "| # | Stage | Status | Exit | Duration | Artefacts | Manual command |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        exit_code = "—" if r.exit_code is None else str(r.exit_code)
        if r.artifacts:
            present = len(r.artifacts_present)
            art = f"{present}/{len(r.artifacts)}"
            if r.artifacts_missing:
                art += " (missing: " + ", ".join(r.artifacts_missing) + ")"
        else:
            art = "—"
        lines.append(
            f"| {r.number} | {r.title} | {r.status} | {exit_code} | {r.duration_ms:.0f} ms | "
            f"{art} | `{r.manual_command or r.command}` |"
        )
    lines += ["", "## 逐阶段证据", ""]
    for r in results:
        lines.append(f"### 阶段 {r.number} · {r.title} — {r.status}")
        lines.append("")
        if r.command:
            lines.append(f"- 命令：`{r.command}`")
        lines.append(f"- 超时上限：{r.timeout_s:.0f} s")
        if r.exit_code is not None:
            lines.append(f"- 退出码：{r.exit_code}")
        if r.log_path:
            lines.append(f"- 日志：`{r.log_path}`")
        if r.artifacts:
            lines.append(
                f"- 产物：{', '.join('`' + a + '`' for a in r.artifacts_present) or '（无）'}"
                + (f" · 缺失：{', '.join(r.artifacts_missing)}" if r.artifacts_missing else "")
            )
        lines.append(f"- 说明：{r.detail or '—'}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Chem ML Platform release pipeline")
    parser.add_argument("--only", nargs="+", type=int, help="run only these stage numbers")
    parser.add_argument("--list", action="store_true", help="list the stage table and exit")
    parser.add_argument("--json", default=str(DEFAULT_JSON))
    parser.add_argument("--md", default=str(DEFAULT_MD))
    args = parser.parse_args()

    stages = build_stages()
    if args.list:
        for stage in stages:
            flag = "required" if stage.required else "optional"
            extra = " [SKIP: " + stage.skip_reason[:60] + "]" if stage.skip_reason else ""
            print(f"{stage.number:>2}  {stage.title:<28} {flag:<9}{extra}")
        return 0

    if args.only:
        wanted = set(args.only)
        stages = [s for s in stages if s.number in wanted]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    meta = build_metadata()
    meta["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    results: List[StageResult] = []
    for stage in stages:
        result = run_stage(stage)
        results.append(result)
        print(
            f"[{result.status:^7}] 阶段 {result.number:>2} {result.title:<26} "
            f"({result.duration_ms:.0f} ms) {result.detail[:90]}"
        )

    meta["finished_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "version": meta["version"],
        "codename": meta["codename"],
        "commit": meta["commit"],
        "python": meta["python"],
        "started_at": meta["started_at"],
        "finished_at": meta["finished_at"],
        "stages": [r.to_dict() for r in results],
    }
    verdict = not any(r.status in FAILING for r in results)
    payload["ok"] = verdict

    out_json, out_md = Path(args.json), Path(args.md)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(_markdown(results, meta), encoding="utf-8")

    print(
        f"\npipeline: {'PASSED' if verdict else 'FAILED'} "
        f"(pass={sum(1 for r in results if r.status == PASS)} "
        f"fail={sum(1 for r in results if r.status == FAIL)} "
        f"timeout={sum(1 for r in results if r.status == TIMEOUT)} "
        f"error={sum(1 for r in results if r.status == ERROR)} "
        f"skip={sum(1 for r in results if r.status == SKIP)})"
    )
    print(f"reports: {out_json} · {out_md} · logs: {LOG_DIR}")
    return 0 if verdict else 1


if __name__ == "__main__":
    raise SystemExit(main())
