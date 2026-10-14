"""Node Registry Service.

Automates what used to be a hand maintained list: on start-up the platform
scans ``nodes/``, imports every module and records what registered itself.
The result is ``registry.json`` -- a machine readable catalogue that the REST
API, the Node Marketplace and the README all read from, so the node count can
never drift away from the code again.

Usage::

    from node_registry import scan, validate, write_registry, summary

    report = scan()                       # 77+ nodes discovered
    write_registry()                      # node_registry/registry.json
    print(validate(report)["valid"])      # True
    print(summary())                      # "77 nodes / 24 categories"

Layout
------
=======================  ===================================================
``node_registry.scanner``    walk ``nodes/`` and build the records
``node_registry.validator``  structural checks on a record / a whole registry
``node_registry.registry.json``  generated catalogue (checked in, refreshed by
                                 ``python -m node_registry``)
=======================  ===================================================
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from node_registry.scanner import ROOT, collect_records, iter_node_modules, scan, write_registry
from node_registry.capabilities import GRADES, node_status, resolve_software
from node_registry.validator import (
    KNOWN_PARAM_TYPES,
    REQUIRED_KEYS,
    validate_record,
    validate_records,
)

#: Read from the single source of truth (spec task P0-04) so the registry can
#: never drift from the backend / desktop / frontend version.
try:  # pragma: no cover - import shim for the odd extracted-zip layout
    from chemml_version import __version__
except ImportError:  # pragma: no cover
    __version__ = "0.7.2"

REGISTRY_FILE = Path(__file__).resolve().parent / "registry.json"

__all__ = [
    "scan",
    "validate",
    "write_registry",
    "load_registry",
    "summary",
    "collect_records",
    "iter_node_modules",
    "validate_record",
    "validate_records",
    "GRADES",
    "node_status",
    "resolve_software",
    "REQUIRED_KEYS",
    "KNOWN_PARAM_TYPES",
    "REGISTRY_FILE",
    "ROOT",
    "__version__",
]


def validate(report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Validate a scan report (or the freshly scanned one)."""
    payload = report if report is not None else scan()
    return validate_records(payload.get("nodes", []))


def load_registry(path: Optional[str | Path] = None) -> Dict[str, Any]:
    """Load ``registry.json`` from disk."""
    target = Path(path) if path else REGISTRY_FILE
    if not target.exists():
        write_registry(target)
    return json.loads(target.read_text(encoding="utf-8"))


def summary(report: Optional[Dict[str, Any]] = None) -> str:
    """One line description of the scanned node population."""
    payload = report if report is not None else scan()
    nodes = payload.get("total_nodes", len(payload.get("nodes", [])))
    categories = len(payload.get("categories", []))
    modules = payload.get("modules_scanned", 0)
    availability = payload.get("availability_summary", {})
    suffix = ""
    if availability:
        suffix = " · " + " ".join(f"{k}={v}" for k, v in availability.items())
    return f"{nodes} nodes / {categories} categories / {modules} modules scanned{suffix}"


def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m node_registry",
        description="Scan nodes/ and (re)generate node_registry/registry.json",
    )
    parser.add_argument("--write", action="store_true", help="write registry.json")
    parser.add_argument("--check", action="store_true", help="fail when invalid")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    args = parser.parse_args()

    report = scan()
    verdict = validate(report)

    if args.write:
        target = write_registry()
        if not args.quiet:
            print(f"written: {target}")

    if not args.quiet:
        print(f"modules scanned : {report['modules_scanned']}")
        print(f"nodes discovered: {report['total_nodes']}")
        print(f"categories      : {len(report['categories'])}")
        for bucket in report["categories"]:
            print(f"  {bucket['category']:<28}{bucket['count']:>4}")
        print(f"valid           : {verdict['valid']}")
        for type_name, issues in verdict["problems"].items():
            for issue in issues:
                print(f"  ! {type_name}: {issue}")

    if args.check and not verdict["valid"]:
        return 1
    print(summary(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
