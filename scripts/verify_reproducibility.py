"""Reproducibility verification -- v0.7.2 task P1-06.

Spec acceptance criteria this tool exists to satisfy:

* "从一次运行记录可以追溯输入、参数、算法版本和输出" -- checked by resolving every
  node's recorded inputs, params, node version and output digests.
* "对声明为确定性的任务，可以通过重复运行测试验证结果一致性" -- each workflow is
  executed ``--repeat`` times and per-node output digests are compared.
* "对非确定性任务，报告明确记录可能导致差异的因素" -- nodes that differ are
  reported *with* the factors that explain them.
* "不使用『所有输入永远产生完全相同的输出』这样的绝对承诺" -- the tool states
  exactly which nodes it verified and refuses to generalise beyond them.

Usage::

    python scripts/verify_reproducibility.py                 # all demo workflows, 2 runs
    python scripts/verify_reproducibility.py --repeat 3 -w workflows/04_*.json
    python scripts/verify_reproducibility.py --json output/reproducibility.json

Exit codes: 0 all verified runs agreed, 1 a declared-deterministic node diverged,
2 the harness itself could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workflow_engine.engine import WorkflowEngine  # noqa: E402

#: Small enough to run several times, cheap to recompute, and covering both a
#: real numerical node (quantum/materials) and a text pipeline.
DEFAULT_WORKFLOWS = [
    "workflows/04_quantum_chemistry_profiling.json",
    "workflows/02_molecular_properties.json",
]


def _run_once(workflow: Dict[str, Any], workdir: Path, run_id: str) -> Dict[str, Any]:
    """Execute one workflow and return its provenance payload."""
    from nodes.loader import get_registry

    engine = WorkflowEngine(
        registry=get_registry(), workdir=workdir, use_cache=False, max_workers=4
    )
    # The run id is pinned so the *only* thing that differs between repeats is
    # the run directory, which is what a real re-run would look like.
    result = engine.run(workflow, run_id=run_id)
    if not result.provenance_path:
        raise RuntimeError(f"workflow {workflow.get('name')!r} wrote no provenance.json")
    payload = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))
    payload["_run_status"] = result.status
    return payload


def _traceability(payload: Dict[str, Any], workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Report whether every node record is traceable end to end.

    A node is only blamed for a missing parameter if the workflow actually
    declared one: a node with no parameters has nothing to lose, and flagging it
    would be a false alarm that devalues the check.
    """
    declared = {
        str(node.get("id")): dict(node.get("params") or {})
        for node in workflow.get("nodes", [])
    }
    weak: List[str] = []
    for node_id, node in payload.get("nodes", {}).items():
        missing = []
        if not node.get("node_type"):
            missing.append("node_type")
        if not node.get("node_version"):
            missing.append("node_version")
        expected = declared.get(node_id, {})
        recorded = dict(node.get("params") or {})
        for key, value in expected.items():
            if key not in recorded or recorded[key] != value:
                missing.append(f"params.{key}")
        if node.get("status") == "completed" and not node.get("output_digests"):
            missing.append("output_digests")
        if missing:
            weak.append(f"{node_id}({','.join(missing)})")
    return {
        "workflow_definition_digest": payload.get("workflow", {}).get("definition_digest", ""),
        "platform_version": payload.get("platform", {}).get("version", ""),
        "node_count": len(payload.get("nodes", {})),
        "nodes_without_full_trace": weak,
    }


def _compare(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare per-node output digests across repeated runs."""
    first = records[0]
    node_ids = sorted(first.get("nodes", {}))
    diverged: List[str] = []
    compared = 0
    for node_id in node_ids:
        digests = []
        for payload in records:
            node = payload.get("nodes", {}).get(node_id, {})
            digests.append((node.get("output_digests") or {}, node.get("status")))
        baseline = digests[0]
        if baseline[1] != "completed":
            continue  # a failed/skipped node has no result to reproduce
        compared += 1
        if any(d != baseline for d in digests[1:]):
            diverged.append(node_id)

    declared_nondeterministic = sorted(
        set(first.get("reproducibility", {}).get("nondeterministic_nodes", []))
    )
    unseeded = sorted(
        set(first.get("reproducibility", {}).get("unseeded_random_nodes", []))
    )
    # A node that diverges is only excused if the record *said in advance* that
    # it could diverge.  Silently unstable nodes are failures.
    excused = set(declared_nondeterministic) | set(unseeded)
    unexplained = [n for n in diverged if n not in excused]
    return {
        "nodes_compared": compared,
        "diverged_nodes": diverged,
        "declared_nondeterministic_nodes": declared_nondeterministic,
        "unseeded_random_nodes": unseeded,
        "unexplained_divergence": unexplained,
        "divergence_factors": first.get("reproducibility", {}).get("divergence_factors", []),
        "claim": first.get("reproducibility", {}).get("claim", ""),
    }


def verify(workflow_path: Path, repeat: int, out_root: Path) -> Dict[str, Any]:
    workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    name = str(workflow.get("name") or workflow_path.stem)
    # All repeats share ONE workdir, exactly as a researcher re-running the same
    # experiment would.  Only the per-run directory differs.  Giving each repeat
    # its own parent directory would make every absolute path differ and report
    # a divergence that no user would ever see.
    workdir = out_root / workflow_path.stem
    records = []
    for index in range(repeat):
        records.append(_run_once(workflow, workdir, f"run{index + 1}"))
    return {
        "workflow": name,
        "file": str(workflow_path.relative_to(ROOT)).replace("\\", "/"),
        "repeat": repeat,
        "statuses": [r.get("_run_status") for r in records],
        "traceability": _traceability(records[0], workflow),
        "determinism": _compare(records),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Reproducibility verification (P1-06)")
    parser.add_argument("-w", "--workflow", action="append", default=None,
                        help="workflow JSON to verify (repeatable)")
    parser.add_argument("--repeat", type=int, default=2, help="runs per workflow (default 2)")
    parser.add_argument("--json", dest="json_out", default="", help="write a JSON report here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.repeat < 2:
        print("ERROR: --repeat must be at least 2 to compare anything")
        return 2

    targets = [Path(p) for p in (args.workflow or DEFAULT_WORKFLOWS)]
    out_root = ROOT / "output" / "reproducibility"

    results = []
    failures = 0
    for target in targets:
        path = target if target.is_absolute() else ROOT / target
        if not path.is_file():
            print(f"MISSING: {path}")
            failures += 1
            continue
        try:
            report = verify(path, args.repeat, out_root)
        except Exception as exc:  # noqa: BLE001 - report, do not crash the gate
            print(f"ERROR: {path.name}: {type(exc).__name__}: {exc}")
            failures += 1
            continue
        results.append(report)

        if not args.quiet:
            det = report["determinism"]
            trace = report["traceability"]
            status = "一致" if not det["unexplained_divergence"] else "不一致"
            print(f"\n=== {report['workflow']} ({report['file']}) x{report['repeat']} ===")
            print(f"  运行状态        : {', '.join(str(s) for s in report['statuses'])}")
            print(f"  平台 / 工作流摘要: {trace['platform_version'] or '—'} / "
                  f"{trace['workflow_definition_digest'][:23] or '—'}")
            print(f"  可追溯节点       : {trace['node_count']} （缺字段: "
                  f"{', '.join(trace['nodes_without_full_trace']) or '无'}）")
            print(f"  比对节点         : {det['nodes_compared']}")
            print(f"  结果一致性       : {status}")
            if det["diverged_nodes"]:
                print(f"  产生差异的节点   : {', '.join(det['diverged_nodes'])}")
            if det["unexplained_divergence"]:
                print(f"  未解释的差异     : {', '.join(det['unexplained_divergence'])}"
                      " ← 声明为确定性却发生了变化")
            if det["unseeded_random_nodes"]:
                print(f"  未固定随机种子   : {', '.join(det['unseeded_random_nodes'])}")
            if det["divergence_factors"]:
                for factor in det["divergence_factors"][:3]:
                    print(f"    · 可能因素：{factor}")
            print(f"  声明             : {det['claim']}")

        if report["determinism"]["unexplained_divergence"]:
            failures += 1

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "tool": "verify_reproducibility",
                    "repeat": args.repeat,
                    "workflows": results,
                    "failures": failures,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        if not args.quiet:
            print(f"\n报告：{out}")

    if failures:
        print(f"\nFAILED: {failures} workflow(s) with unexplained divergence or error")
        return 1
    print(
        f"\nOK: {len(results)} workflow(s) x {args.repeat} runs -- every node declared "
        "deterministic reproduced identical output digests. "
        "该结论仅覆盖本次比对的节点，不构成「所有输入永远产生相同输出」的承诺。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
