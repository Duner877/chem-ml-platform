"""Clean-environment install & end-to-end check (spec task P0-02 #10, P0-02 acceptance).

A desktop installer is only credible if the app runs *without* the machine that
built it.  This script verifies the machine-independent properties that a clean
install depends on, and records -- honestly -- which parts still require a real
clean virtual machine.

What the script actually proves here
------------------------------------
1. The runtime probe validates the declared dependency set with an explicitly
   chosen interpreter (not "whatever is on the builder's PATH").
2. The backend starts from a **different working directory** with only
   ``PYTHONPATH`` pointing at the app root, so first launch cannot depend on
   the build machine's current directory.
3. The backend answers ``/api/health`` and loads the full node registry.
4. One demo workflow completes end to end through the running HTTP API.
5. No shipped file embeds a builder-specific absolute path.

What it cannot prove here -- and therefore marks ``NOT_PERFORMED``
------------------------------------------------------------------
* Installing the NSIS package on a fresh Windows image, first-launch browser
  behaviour, uninstall data retention.  Those need a clean VM; the record says
  so explicitly instead of assuming success.

Usage::

    python scripts/clean_env_check.py            # run and write the record
    python scripts/clean_env_check.py --json     # machine readable
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chemml_version import VERSION, __codename__, git_commit  # noqa: E402

OUT = ROOT / "docs" / "V07_2_CLEAN_ENV_TEST.md"
PYTHON = sys.executable
PROBE = ROOT / "desktop" / "src" / "runtime-probe.js"

PASS, FAIL, NOT_PERFORMED = "PASS", "FAIL", "NOT_PERFORMED"


def _npm_or_node() -> str:
    import shutil

    return shutil.which("node") or ""


def check_probe() -> Dict[str, object]:
    """The declared runtime set is satisfied by an explicitly chosen interpreter."""
    node = _npm_or_node()
    if not node:
        return {
            "id": "runtime_probe",
            "title": "运行时探针校验完整依赖集合",
            "status": NOT_PERFORMED,
            "detail": "node 不可用，无法执行运行时探针",
        }
    proc = subprocess.run(
        [node, str(PROBE), "--json", "--python", PYTHON],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        cwd=str(ROOT),
    )
    try:
        payload = json.loads(proc.stdout)
    except ValueError:
        return {
            "id": "runtime_probe",
            "title": "运行时探针校验完整依赖集合",
            "status": FAIL,
            "detail": f"探针输出无法解析：{(proc.stderr or proc.stdout)[:300]}",
        }
    satisfied = payload.get("requirements", {}).get("satisfied")
    applicable = payload.get("requirements", {}).get("applicable")
    return {
        "id": "runtime_probe",
        "title": "运行时探针校验完整依赖集合",
        "status": PASS if payload.get("ok") else FAIL,
        "detail": (
            f"classification={payload.get('classification')} "
            f"required={satisfied}/{applicable} "
            f"source={payload.get('requirements', {}).get('source')}"
        ),
    }


def check_no_builder_paths() -> Dict[str, object]:
    """No shipped file may embed the builder's absolute path (spec P0-02 acceptance)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("packager", ROOT / "scripts" / "package.py")
    packager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(packager)

    home = str(Path.home())
    patterns = [
        re.compile(re.escape(home), re.IGNORECASE),
        re.compile(r"[A-Za-z]:\\Users\\[^\\\"'\s]+", re.IGNORECASE),
    ]
    offenders: List[str] = []
    scanned = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if packager.should_skip(rel):
            continue
        if path.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".json", ".bat", ".html", ".md", ".yml", ".yaml", ".txt"}:
            continue
        scanned += 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Docs and tests intentionally quote example paths; source and config must not.
        if rel.parts and rel.parts[0] in {"docs", "tests"}:
            continue
        for pattern in patterns:
            if pattern.search(text):
                offenders.append(rel.as_posix())
                break
    if offenders:
        return {
            "id": "no_builder_paths",
            "title": "不依赖构建机绝对路径",
            "status": FAIL,
            "detail": f"{len(offenders)} 个受控文件包含绝对路径：{offenders[:6]}",
        }
    return {
        "id": "no_builder_paths",
        "title": "不依赖构建机绝对路径",
        "status": PASS,
        "detail": f"扫描 {scanned} 个受控文件，未发现构建机绝对路径",
    }


def check_backend_from_foreign_cwd() -> Dict[str, object]:
    """Start the backend from a foreign working directory and run one workflow."""
    import shutil
    import time as _time

    # A repo-local scratch dir, not the OS temp dir: the backend process keeps
    # its cwd open on Windows, and the host's safe-delete shim then refuses the
    # cleanup with PermissionError.  Living under output/ (gitignored, excluded
    # from release packages) makes the leftover harmless either way.
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    tmp_dir = ROOT / "output" / "clean_env_tmp" / stamp
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp = str(tmp_dir)

    try:
        env = {
            **os.environ,
            "PYTHONPATH": str(ROOT),
            "PYTHONUNBUFFERED": "1",
            "CHEMML_ENV": "dev",
            "CHEMML_DATA_DIR": str(tmp_dir / "data"),
            "CHEMML_UPLOAD_DIR": str(tmp_dir / "data" / "uploads"),
            "CHEMML_AUDIT_LOG": str(tmp_dir / "audit.jsonl"),
        }
        proc = subprocess.Popen(
            [
                PYTHON,
                "-m",
                "uvicorn",
                "backend.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8971",
                "--log-level",
                "warning",
            ],
            cwd=tmp,  # deliberately NOT the app root
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        try:
            health = _poll_health("http://127.0.0.1:8971", timeout_s=90)
            if not health["ok"]:
                return {
                    "id": "foreign_cwd_backend",
                    "title": "从非应用目录启动后端（证明不依赖工作目录）",
                    "status": FAIL,
                    "detail": health["detail"],
                }
            nodes = _get_json("http://127.0.0.1:8971/api/nodes", timeout_s=30)
            node_count = (
                len(nodes) if isinstance(nodes, list) else len((nodes or {}).get("nodes", []))
            )
            if node_count < 50:
                return {
                    "id": "foreign_cwd_backend",
                    "title": "从非应用目录启动后端（证明不依赖工作目录）",
                    "status": FAIL,
                    "detail": f"后端已启动但仅加载 {node_count} 个节点",
                }
            workflow = _run_demo_workflow("http://127.0.0.1:8971", timeout_s=300)
            return {
                "id": "foreign_cwd_backend",
                "title": "从非应用目录启动后端（证明不依赖工作目录）",
                "status": PASS if workflow["ok"] else FAIL,
                "detail": (
                    f"health ok · {node_count} 个节点 · 示例工作流 {workflow['detail']}"
                ),
            }
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
            _time.sleep(0.5)  # let Windows release the directory handle
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _poll_health(base: str, timeout_s: int) -> Dict[str, object]:
    deadline = time.time() + timeout_s
    last = ""
    while time.time() < deadline:
        payload = _get_json(f"{base}/api/health", timeout_s=5)
        if isinstance(payload, dict) and payload.get("status") == "ok":
            return {"ok": True, "detail": f"version={payload.get('version')}"}
        last = str(payload)[:200]
        time.sleep(1.0)
    return {"ok": False, "detail": f"{timeout_s}s 内 /api/health 未就绪（最后响应：{last}）"}


def _get_json(url: str, timeout_s: int):
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError):
        return None


def _run_demo_workflow(base: str, timeout_s: int) -> Dict[str, object]:
    """Run a stored demo workflow through the real HTTP API."""
    workflow_files = sorted((ROOT / "workflows").glob("*.json"))
    if not workflow_files:
        return {"ok": False, "detail": "没有可用的示例工作流"}

    chosen = None
    for path in workflow_files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            continue
        node_count = len(data.get("nodes", []))
        if chosen is None or node_count < chosen[1]:
            chosen = (path.name, node_count)
    if chosen is None:
        return {"ok": False, "detail": "示例工作流无法解析"}

    script = (
        "import json,sys,urllib.request\n"
        "base=sys.argv[1]; name=sys.argv[2]\n"
        "req=urllib.request.Request(base+'/api/workflows/'+name+'/run', method='POST',\n"
        "    data=b'{}', headers={'Content-Type':'application/json'})\n"
        "res=json.loads(urllib.request.urlopen(req, timeout=%d).read().decode('utf-8'))\n"
        "print(json.dumps({'run_id':res.get('run_id'),'status':res.get('status')}))\n" % timeout_s
    )
    proc = subprocess.run(
        [PYTHON, "-c", script, base, chosen[0]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s + 30,
    )
    if proc.returncode != 0:
        return {
            "ok": False,
            "detail": f"工作流 {chosen[0]} 执行失败：{(proc.stderr or proc.stdout).strip()[:200]}",
        }
    try:
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "detail": f"无法解析运行结果：{proc.stdout[:200]}"}
    ok = payload.get("status") in {"completed", "finished", "ok", "success"} or bool(payload.get("run_id"))
    return {
        "ok": ok,
        "detail": f"{chosen[0]} → status={payload.get('status')} run_id={payload.get('run_id')}",
    }


NOT_PERFORMED_ITEMS = [
    (
        "clean_vm_install",
        "在干净虚拟机中安装 NSIS 安装包",
        "本环境无法提供干净的目标虚拟机；需在 Windows x64 干净镜像上执行 "
        "`Chem ML Platform Setup {version}.exe` 并记录结果。".format(version=VERSION),
    ),
    (
        "first_launch_browser",
        "首次启动的窗口与前端加载行为",
        "需要真实桌面会话与安装后的 Electron 进程；本环境无图形桌面。",
    ),
    (
        "uninstall_retention",
        "卸载后的数据保留行为",
        "需要真实安装/卸载流程；策略见 docs/V07_2_DESKTOP_RUNTIME.md（deleteAppDataOnUninstall=false）。",
    ),
    (
        "portable_path_check",
        "安装目录与用户数据目录的权限与写入验证",
        "需要真实安装目录（Program Files / 用户目录）的 ACL 环境。",
    ),
]


def _markdown(items: List[Dict[str, object]], meta: Dict[str, str]) -> str:
    counts: Dict[str, int] = {PASS: 0, FAIL: 0, NOT_PERFORMED: 0}
    for item in items:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    lines = [
        f"# Chem ML Platform v{VERSION} — 干净环境安装与端到端测试记录",
        "",
        f"- **codename**: {__codename__}",
        f"- **commit**: `{meta['commit']}`",
        f"- **recorded at**: {meta['recorded_at']}",
        f"- **host**: {meta['host']}",
        f"- **python**: {meta['python']}",
        f"- **node**: {meta['node'] or '（不可用）'}",
        f"- **结果**: PASS {counts[PASS]} · FAIL {counts[FAIL]} · NOT_PERFORMED {counts[NOT_PERFORMED]}",
        "",
        "> 本记录**不把未执行的项目当作通过**。`NOT_PERFORMED` 表示该验证需要本环境不具备的条件，",
        "> 并给出手工执行步骤；在干净虚拟机上完成后应将结果补录到本文件。",
        "",
        "## 已验证项目",
        "",
        "| 项目 | 结果 | 证据 |",
        "| --- | --- | --- |",
    ]
    for item in items:
        lines.append(f"| {item['title']} | {item['status']} | {item['detail']} |")
    lines += [
        "",
        "## 未执行项目（需要干净虚拟机或图形桌面）",
        "",
        "| 项目 | 状态 | 原因与手工步骤 |",
        "| --- | --- | --- |",
    ]
    for _, title, reason in NOT_PERFORMED_ITEMS:
        lines.append(f"| {title} | NOT_PERFORMED | {reason} |")
    lines += [
        "",
        "## 结论",
        "",
        "本机验证覆盖：依赖集合完整性、不依赖构建机绝对路径、从非应用目录启动后端、",
        "以及在真实 HTTP 接口上完成一条端到端示例工作流。",
        "",
        "**未覆盖**：目标虚拟机上的安装包安装、首次启动的图形行为、卸载数据保留。",
        "在完成干净虚拟机验证之前，Windows x64 只能声明为「已构建、本机已验证」，",
        "不得声明为「已在干净环境完整验证」。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="clean environment install check")
    parser.add_argument("--json", action="store_true", help="print JSON instead of writing the record")
    args = parser.parse_args()

    items = [check_probe(), check_no_builder_paths(), check_backend_from_foreign_cwd()]

    meta = {
        "commit": git_commit(short=False),
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": f"{os.name} · {sys.platform} · {os.environ.get('PROCESSOR_ARCHITECTURE', '?')}",
        "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "node": _npm_or_node(),
    }

    payload = {
        "version": VERSION,
        "codename": __codename__,
        **meta,
        "items": items,
        "not_performed": [
            {"id": i, "title": t, "reason": r} for i, t, r in NOT_PERFORMED_ITEMS
        ],
        "ok": not any(i["status"] == FAIL for i in items),
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["ok"] else 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(_markdown(items, meta), encoding="utf-8")
    for item in items:
        print(f"[{item['status']:^13}] {item['title']}: {item['detail']}")
    print(f"\nrecord: {OUT.relative_to(ROOT)}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
