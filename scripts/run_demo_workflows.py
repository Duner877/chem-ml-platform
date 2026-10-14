#!/usr/bin/env python
"""Execute the official demo workflows end to end.

Each workflow JSON in ``workflows/`` is validated against the node registry and
executed by :class:`workflow_engine.engine.WorkflowEngine`.  The script exits
with a non-zero status as soon as one workflow fails to validate or execute.

Usage
-----
    python scripts/run_demo_workflows.py                 # run every workflow
    python scripts/run_demo_workflows.py 02              # only workflow 02
    python scripts/run_demo_workflows.py --list          # list and exit
    python scripts/run_demo_workflows.py --events        # print node events
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
from workflow_engine.events import Event  # noqa: E402
from workflow_engine.workflow import Workflow  # noqa: E402

WORKFLOWS_DIR = ROOT / "workflows"
OUTPUT_DIR = ROOT / "output" / "demo_runs"


def discover(directory: Path) -> List[Path]:
    """Return every ``*.json`` workflow, ordered by name."""
    return sorted(directory.glob("*.json"))


def run(path: Path, show_events: bool = False) -> Dict[str, Any]:
    """Validate and execute a single workflow, returning a summary dict."""
    workflow = Workflow.from_file(path)
    registry = get_registry()

    engine = WorkflowEngine(
        registry=registry,
        workdir=OUTPUT_DIR / workflow.name.replace("/", "-").replace(" ", "_"),
        max_workers=4,
        use_cache=False,
    )

    events: List[str] = []
    if show_events:
        engine._listeners.append(lambda event: events.append(str(event)))

    started = time.time()
    result = engine.run(workflow)
    elapsed = time.time() - started

    summary: Dict[str, Any] = {
        "file": path.name,
        "workflow": workflow.name,
        "ok": result.ok,
        "status": result.status,
        "nodes": len(workflow.nodes),
        "edges": len(workflow.edges),
        "elapsed_s": round(elapsed, 2),
        "run_id": result.run_id,
        "artifacts": list(result.artifacts),
    }

    if result.errors:
        summary["errors"] = result.errors

    print(
        f"[{'PASS' if result.ok else 'FAIL'}] {path.name}  "
        f"{workflow.name}  ({summary['nodes']} nodes / {summary['edges']} edges, "
        f"{summary['elapsed_s']}s, status={result.status})"
    )
    for node_id, record in (result.records or {}).items():
        status = "ok" if record.status == "completed" else record.status
        print(
            f"      - {node_id:<18} {status:<10} {record.duration_ms / 1000.0:.2f}s"
        )
        if record.error:
            print(f"        ! {record.error}")
    if show_events:
        for line in events:
            print(f"        event: {line}")
    return summary


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("filter", nargs="*", help="substring filter on file names")
    parser.add_argument("--list", action="store_true", help="list workflows and exit")
    parser.add_argument("--events", action="store_true", help="print node events")
    args = parser.parse_args(argv)

    if not WORKFLOWS_DIR.exists():
        print(f"workflow directory {WORKFLOWS_DIR} does not exist")
        return 2

    paths = discover(WORKFLOWS_DIR)
    if args.filter:
        paths = [
            p
            for p in paths
            if any(token.lower() in p.name.lower() for token in args.filter)
        ]

    if args.list:
        for path in paths:
            workflow = Workflow.from_file(path)
            print(f"{path.name}: {workflow.name} ({len(workflow.nodes)} nodes)")
        return 0

    if not paths:
        print("no workflow matched the given filter")
        return 2

    print(f"discovered {len(paths)} workflow(s) in {WORKFLOWS_DIR}\n")
    summaries: List[Dict[str, Any]] = []
    for path in paths:
        summaries.append(run(path, show_events=args.events))

    failed = [s for s in summaries if not s["ok"]]
    print("-" * 90)
    print(
        f"{len(summaries) - len(failed)}/{len(summaries)} workflows executed successfully"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
