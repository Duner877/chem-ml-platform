"""Generate node statistics + capability catalogue (v0.7.1 spec §P2-06 / task F).

Node counts used to be hand-maintained in the README, which is exactly how the
number drifts away from the code.  This script makes the registry the single
source of truth and can both *generate* the derived artefacts and *check* that
the docs still agree with it:

    python scripts/node_catalog.py            # regenerate registry + catalogue
    python scripts/node_catalog.py --check    # exit 1 when docs disagree

Generated artefacts
-------------------
``node_registry/registry.json``   machine readable catalogue (also refreshed)
``docs/node-catalog.md``          human readable capability / status catalogue
``node_registry/stats.json``      compact counts used by the README/quality gate
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STATS_FILE = ROOT / "node_registry" / "stats.json"
CATALOG_FILE = ROOT / "docs" / "node-catalog.md"


def build() -> Dict[str, object]:
    from node_registry import scan, write_registry

    write_registry()
    report = scan()
    stats = {
        "total_nodes": report["total_nodes"],
        "categories": len(report["categories"]),
        "modules_scanned": report["modules_scanned"],
        "availability_summary": report["availability_summary"],
        "capability_summary": report["capability_summary"],
        "missing_software_summary": report["missing_software_summary"],
        # -- v0.7.2 task P0-05 -------------------------------------------- #
        "capability_status_summary": report["capability_status_summary"],
        "execution_mode_summary": report["execution_mode_summary"],
        "reproducibility_summary": report["reproducibility_summary"],
        "nodes_without_validation_evidence": report["nodes_without_validation_evidence"],
    }
    STATS_FILE.write_text(json.dumps(stats, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    CATALOG_FILE.write_text(render_catalog(report), encoding="utf-8")
    return stats


def render_catalog(report: Dict[str, object]) -> str:
    from chemml_version import VERSION

    nodes: List[Dict[str, object]] = list(report["nodes"])  # type: ignore[arg-type]
    lines = [
        f"# 节点能力与状态目录（v{VERSION}）",
        "",
        "> 本文件由 `scripts/node_catalog.py` 自动生成，请勿手工编辑。",
        "> 数据来源：`node_registry/registry.json`（节点注册表扫描结果）。",
        "",
        f"- 节点总数：**{report['total_nodes']}**",
        f"- 分类数：**{len(report['categories'])}**",
        f"- 扫描模块：**{report['modules_scanned']}**",
        f"- 尚无验证证据的节点：**{report['nodes_without_validation_evidence']}**"
        "（未验证 ≠ 不可用，但**不得**宣传为已验证）",
        "",
        "## 能力标签说明",
        "",
        "| 能力标签 | 含义 |",
        "| --- | --- |",
        "| `requires_network` | 会访问网络 / 云端服务（不可达时诚实回退内置库） |",
        "| `requires_gpu` | 需要 GPU；不可用时明确回退 CPU 或报告不可用 |",
        "| `requires_external_software` | 调用外部科学软件（缺失时回退内部近似引擎并标注） |",
        "| `writes_files` | 会生成或覆盖产物文件 |",
        "| `experimental` | 实验性能力，结果需人工复核 |",
        "| `sensitive_data` | 可能处理敏感数据，建议使用本地模型 |",
        "| `nondeterministic` | 非确定性节点，不承诺逐位可复现 |",
        "",
        "## 执行来源：capability_status（可以主张什么）",
        "",
        "| 状态 | 含义 |",
        "| --- | --- |",
        "| `verified` | **有独立已知答案验证证据**（`validation_evidence` 非空）；无证据的 `verified` 声明会被自动降级为 `executable` |",
        "| `executable` | 当前环境可运行，但未经过独立验证 |",
        "| `experimental` | 可运行，但科学结论未经确认 |",
        "| `unavailable` | 声明的依赖在当前环境缺失（**绝不伪装成功**） |",
        "",
        "## 执行来源：execution_mode（实际由谁计算）",
        "",
        "| 模式 | 含义 |",
        "| --- | --- |",
        "| `external` | 真实第三方程序执行；必须声明依赖 |",
        "| `internal_approximation` | 内置近似模型代替真实程序；**结果必须标注为近似** |",
        "| `synthetic_demo` | 基于合成数据的演示输出；**不代表真实测量** |",
        "",
        "> ⚠️ `internal_approximation` / `synthetic_demo` 的结果**不得**表述为第三方科研软件的真实计算，",
        "> 也不得作为科研准确率声明。",
        "",
        "## 状态汇总（运行时探测）",
        "",
        "| 状态 | 节点数 |",
        "| --- | --- |",
    ]
    for grade, count in sorted(report["availability_summary"].items()):  # type: ignore[union-attr]
        lines.append(f"| `{grade}` | {count} |")
    lines += [
        "",
        "## capability_status 汇总（v0.7.2）",
        "",
        "| capability_status | 节点数 |",
        "| --- | --- |",
    ]
    for value, count in sorted(report["capability_status_summary"].items()):  # type: ignore[union-attr]
        lines.append(f"| `{value}` | {count} |")
    lines += [
        "",
        "## execution_mode 汇总（v0.7.2）",
        "",
        "| execution_mode | 节点数 |",
        "| --- | --- |",
    ]
    for value, count in sorted(report["execution_mode_summary"].items()):  # type: ignore[union-attr]
        lines.append(f"| `{value}` | {count} |")
    lines += [
        "",
        "## 可复现级别汇总（v0.7.2）",
        "",
        "| reproducibility_level | 节点数 |",
        "| --- | --- |",
    ]
    for value, count in sorted(report["reproducibility_summary"].items()):  # type: ignore[union-attr]
        lines.append(f"| `{value}` | {count} |")
    lines += [
        "",
        "## 能力汇总",
        "",
        "| 能力标签 | 节点数 |",
        "| --- | --- |",
    ]
    for capability, count in sorted(report["capability_summary"].items()):  # type: ignore[union-attr]
        lines.append(f"| `{capability}` | {count} |")
    lines += [
        "",
        "## 全部节点",
        "",
        "| 节点类型 | 分类 | 状态 | capability_status | execution_mode | 可复现 | 验证证据 | 能力标签 | 依赖外部软件 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for node in sorted(nodes, key=lambda n: (str(n["category"]), str(n["type"]))):
        caps = ", ".join(f"`{c}`" for c in node["capabilities"]) or "—"
        req = ", ".join(f"`{s}`" for s in node["required_software"]) or "—"
        missing = node["missing_software"]
        if missing:
            req += "（缺失：" + ", ".join(f"`{m}`" for m in missing) + "）"
        det = "是" if node["deterministic"] else "否"
        evidence = node.get("validation_evidence") or []
        evidence_cell = str(len(evidence)) if evidence else "—"
        status_cell = f"`{node.get('capability_status', '—')}`"
        if node.get("capability_status_note"):
            status_cell += "（已降级）"
        lines.append(
            f"| `{node['type']}` | {node['category']} | `{node['availability']}` | "
            f"{status_cell} | `{node.get('execution_mode', '—')}` | {det} | "
            f"{evidence_cell} | {caps} | {req} |"
        )
    return "\n".join(lines) + "\n"


def check() -> Tuple[bool, List[str]]:
    """Verify the README node counts match the live registry."""
    from node_registry import scan

    report = scan()
    real_nodes = report["total_nodes"]
    real_categories = len(report["categories"])

    problems: List[str] = []
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace")

    # badge
    for m in re.finditer(r"nodes-(\d+)-blueviolet", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README badge says {m.group(1)} nodes, registry {real_nodes}")
    # "节点总数 **N**"
    for m in re.finditer(r"节点总数 \*\*(\d+)\*\*", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README 节点总数 says {m.group(1)}, registry {real_nodes}")
    # "**N 个科学节点，M 个分类"
    for m in re.finditer(r"\*\*(\d+) 个科学节点，(\d+) 个分类", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README node section says {m.group(1)} nodes, registry {real_nodes}")
        if int(m.group(2)) != real_categories:
            problems.append(f"README node section says {m.group(2)} categories, registry {real_categories}")
    # "含 N 个科学节点" / "① N 个节点"
    for m in re.finditer(r"(?:含|逐一实例化并执行 )(\d+) 个(?:科学)?节点", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README says {m.group(1)} nodes in prose, registry {real_nodes}")
    # "N 个科学节点（见下方目录）" tree line
    for m in re.finditer(r"nodes/\s+(\d+) 个科学节点", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README tree says {m.group(1)} nodes, registry {real_nodes}")
    # "'nodes': N"
    for m in re.finditer(r"'nodes':\s*(\d+)", readme):
        if int(m.group(1)) != real_nodes:
            problems.append(f"README SDK example says {m.group(1)} nodes, registry {real_nodes}")

    stats_file = STATS_FILE
    if stats_file.exists():
        stored = json.loads(stats_file.read_text(encoding="utf-8"))
        if stored.get("total_nodes") != real_nodes:
            problems.append(
                f"node_registry/stats.json says {stored.get('total_nodes')}, registry {real_nodes}"
            )
    return (not problems), problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Node statistics + capability catalogue")
    parser.add_argument("--check", action="store_true", help="verify docs match the registry")
    args = parser.parse_args()
    if args.check:
        ok, problems = check()
        if ok:
            print("OK: README / stats agree with the node registry")
            return 0
        for problem in problems:
            print("MISMATCH:", problem)
        return 1
    stats = build()
    print(f"nodes={stats['total_nodes']} categories={stats['categories']} modules={stats['modules_scanned']}")
    print(f"wrote: {STATS_FILE.relative_to(ROOT)} · {CATALOG_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
