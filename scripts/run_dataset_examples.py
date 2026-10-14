"""Validate and execute every ``example_workflow.json`` shipped with a dataset.

Each dataset folder in ``datasets/`` carries its own raw data, a
``*.metadata.json`` description, a ``*.parser.json`` parser configuration and
an ``example_workflow.json`` that consumes it.  This script walks the tree,
executes each of those workflows and reports what was produced, so a broken
dataset is caught by CI instead of by a user::

    python scripts/run_dataset_examples.py            # run all
    python scripts/run_dataset_examples.py --validate # validate only
    python scripts/run_dataset_examples.py --events   # print node events
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodes.loader import get_registry  # noqa: E402
from workflow_engine.engine import WorkflowEngine  # noqa: E402
from workflow_engine.workflow import Workflow  # noqa: E402

OUTPUT_DIR = ROOT / "output" / "dataset_examples"


def discover() -> List[Path]:
    """Every dataset example workflow, in a stable order."""
    return sorted(ROOT.glob("datasets/**/example_workflow.json"))


def load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_one(path: Path, events: bool = False, validate_only: bool = False) -> Dict[str, Any]:
    """Validate (and optionally execute) a single dataset workflow."""
    document = load(path)
    workflow = Workflow.from_dict(document)
    issues = workflow.validate(get_registry())
    record: Dict[str, Any] = {
        "dataset": path.parent.relative_to(ROOT).as_posix(),
        "name": document.get("name", path.parent.name),
        "nodes": len(workflow.nodes),
        "edges": len(workflow.edges),
        "valid": not issues,
        "issues": issues,
    }
    if issues or validate_only:
        record["status"] = "invalid" if issues else "validated"
        return record

    engine = WorkflowEngine(
        registry=get_registry(),
        workdir=OUTPUT_DIR / path.parent.name,
        max_workers=1,
        use_cache=False,
    )
    started = time.perf_counter()
    result = engine.run(workflow)
    record["status"] = result.status
    record["duration_ms"] = round((time.perf_counter() - started) * 1000.0, 1)
    record["failed"] = [
        node_id for node_id, node in result.records.items() if node.status == "failed"
    ]
    record["artifacts"] = sorted(
        str(artifact) for artifact in (result.artifacts or [])
    )
    if events:
        for node_id, node in result.records.items():
            print(f"    [{node.status:<9}] {node_id:<12} {node.duration_ms:8.1f} ms")
            for line in (node.logs or [])[:3]:
                print(f"               | {line}")
    return record


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true", help="validate only, do not run")
    parser.add_argument("--events", action="store_true", help="print per node events")
    parser.add_argument("--json", action="store_true", help="machine readable output")
    args = parser.parse_args(argv)

    workflows = discover()
    if not workflows:
        print("no dataset example workflows found under datasets/")
        return 1

    records: List[Dict[str, Any]] = []
    for path in workflows:
        if not args.json:
            print(f"==> {path.parent.relative_to(ROOT).as_posix()}")
        try:
            records.append(run_one(path, events=args.events, validate_only=args.validate))
        except Exception as exc:  # noqa: BLE001 - report and continue
            records.append(
                {
                    "dataset": path.parent.relative_to(ROOT).as_posix(),
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "valid": False,
                }
            )
        if not args.json:
            record = records[-1]
            if record.get("status") == "error":
                print(f"    ERROR {record['error']}")
            else:
                print(
                    f"    {record['status']:<10} nodes={record.get('nodes')} "
                    f"edges={record.get('edges')} "
                    f"{record.get('duration_ms', '')} ms "
                    f"artifacts={len(record.get('artifacts', []))}"
                )

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    ok = [r for r in records if r.get("status") in {"completed", "validated"}]
    print()
    print(f"{len(ok)}/{len(records)} dataset example workflows "
          f"{'validated' if args.validate else 'executed'} successfully")
    return 0 if len(ok) == len(records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
