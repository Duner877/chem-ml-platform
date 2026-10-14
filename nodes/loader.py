"""Canonical node loading entry point.

Running this module imports *every* node package of the platform and therefore
populates :data:`workflow_engine.registry.registry` with all node classes::

    python -m nodes.loader            # human readable listing
    python -m nodes.loader --json     # machine readable listing
    python -m nodes.loader --stats    # per category statistics

The FastAPI backend, the Python SDK and the test-suite all call
:func:`load_nodes` so that exactly one code path is responsible for discovery.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

# ``nodes/__init__.py`` already puts the repository root on ``sys.path``; the
# import below re-uses it and keeps ``python -m nodes.loader`` working from any
# working directory.
from nodes import ROOT, load_nodes, node_categories, node_specs  # noqa: F401

__all__ = [
    "load_nodes",
    "node_specs",
    "node_categories",
    "get_registry",
    "create_node",
    "describe",
    "ROOT",
]


# --------------------------------------------------------------------------- #
# Explicit imports: keep them in sync with ``nodes.__init__`` docstring table. #
# --------------------------------------------------------------------------- #
def _import_all() -> None:
    """Import the node sub-modules in dependency order."""
    from nodes import io, analysis, report  # noqa: F401
    from nodes import question  # noqa: F401
    from nodes import instruments  # noqa: F401
    from nodes.instruments import mass_spectrometry  # noqa: F401
    from nodes import ai  # noqa: F401
    from nodes import databases  # noqa: F401
    from nodes import simulation  # noqa: F401
    from nodes import agent  # noqa: F401


def get_registry():
    """Return the fully populated global registry."""
    load_nodes()
    from workflow_engine.registry import registry

    return registry


def create_node(
    type_name: str, node_id: str = "", params: Dict[str, Any] | None = None
):
    """Instantiate a registered node class by type name or alias."""
    return get_registry().create(type_name, node_id=node_id, params=params)


def describe(query: str = "") -> List[Dict[str, Any]]:
    """Return node specs, optionally filtered by a free text query."""
    registry = get_registry()
    if query:
        return registry.search(query)
    return registry.specs()


# --------------------------------------------------------------------------- #
# Command line interface                                                       #
# --------------------------------------------------------------------------- #
def _load(plugins: str | None) -> List[Dict[str, Any]]:
    _import_all()
    load_nodes(plugins)
    return node_specs()


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m nodes.loader",
        description="Discover and list every scientific node of the platform.",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--stats", action="store_true", help="category statistics")
    parser.add_argument("--query", default="", help="filter nodes by keyword")
    parser.add_argument("--plugins", default=None, help="extra plugin directory")
    args = parser.parse_args(argv)

    specs = _load(args.plugins)
    if args.query:
        needle = args.query.lower()
        specs = [
            spec
            for spec in specs
            if needle in json.dumps(spec, ensure_ascii=False, default=str).lower()
        ]

    if args.json:
        print(json.dumps(specs, indent=2, ensure_ascii=False, default=str))
        return 0

    if args.stats:
        print(f"{'category':<28}{'nodes':>6}")
        print("-" * 34)
        for bucket in node_categories():
            print(f"{bucket['name']:<28}{bucket['count']:>6}")
        print("-" * 34)
        print(f"{'TOTAL':<28}{len(specs):>6}")
        return 0

    print(f"{'type':<34}{'category':<20}{'in':>4}{'out':>5}  name")
    print("-" * 100)
    for spec in specs:
        print(
            f"{spec.get('type', ''):<34}{spec.get('category', ''):<20}"
            f"{len(spec.get('inputs', [])):>4}{len(spec.get('outputs', [])):>5}"
            f"  {spec.get('name', '')}"
        )
    print("-" * 100)
    print(f"{len(specs)} node types registered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
