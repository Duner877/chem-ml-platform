"""Node registry scanner: discover nodes by walking ``nodes/``.

The scanner is the automation the specification asks for: instead of relying on
a hand maintained list (which is how README node counts drift away from the
code), it imports every module under ``nodes/`` and reads the classes that
registered themselves.

Usage::

    from node_registry import scan, write_registry

    report = scan()                 # -> {"nodes": [...], "categories": [...]}
    write_registry()                # -> node_registry/registry.json

The result is a list of records with exactly the shape required by the spec::

    {
      "node_name": "LC-MS",
      "type": "LCMSNode",
      "version": "0.7.1",
      "inputs": [...],
      "outputs": [...],
      "author": "",
      "description": "..."
    }
"""

from __future__ import annotations

import importlib
import inspect
import os
import pkgutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_engine.node_base import ScientificNode
from workflow_engine.registry import registry

__all__ = ["scan", "iter_node_modules", "collect_records", "author_of"]

#: Repository root (the parent of ``node_registry``).
ROOT = Path(__file__).resolve().parents[1]


def iter_node_modules(package: str = "nodes") -> List[str]:
    """Return the dotted names of every module inside ``nodes/``.

    Since v0.7.4 the node implementations live in ``custom_nodes``; the
    ``nodes`` package is a compatibility facade over it.  Scanning the
    facade would report zero modules (it holds no implementation), so the
    scan targets ``custom_nodes`` and the legacy name stays a fallback for a
    checkout that has not been migrated yet.
    """
    modules: List[str] = []
    target = package
    if not _package_has_modules(package):
        target = "custom_nodes"
    try:
        imported = importlib.import_module(target)
    except ImportError:  # pragma: no cover - defensive
        return modules
    if not hasattr(imported, "__path__"):
        return [target]
    for info in pkgutil.walk_packages(imported.__path__, prefix=f"{target}."):
        modules.append(info.name)
    return sorted(modules)


def _package_has_modules(package: str) -> bool:
    """True when ``package`` contains at least one importable submodule.

    The facade package ``nodes`` contains only ``__init__.py``, so walking it
    yields nothing.  The check is a filesystem probe rather than an import
    because importing the facade to find out would be circular.
    """
    try:
        mod = importlib.import_module(package)
    except ImportError:
        return False
    path = getattr(mod, "__path__", None)
    if not path:
        return False
    for root in path:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for name in filenames:
                if name.endswith(".py") and name != "__init__.py":
                    return True
    return False


def author_of(node_cls: type) -> str:
    """Best effort author of a node class (``Author:`` docstring tag)."""
    for source in (inspect.getdoc(node_cls), inspect.getdoc(inspect.getmodule(node_cls))):
        for line in (source or "").splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("author:"):
                return stripped.split(":", 1)[1].strip()
    return ""


def collect_records() -> List[Dict[str, Any]]:
    """Import every node module and describe the registered classes."""
    from nodes import load_nodes  # local import: avoids a circular dependency

    from node_registry.capabilities import node_status

    load_nodes()
    records: List[Dict[str, Any]] = []
    for type_name in sorted(registry.types()):
        node_cls = registry.get(type_name)
        spec = node_cls.spec()
        status = node_status(node_cls)
        records.append(
            {
                "node_name": spec.get("name", ""),
                "type": spec.get("type", type_name),
                "version": spec.get("version", ""),
                "inputs": spec.get("inputs", []),
                "outputs": spec.get("outputs", []),
                "author": author_of(node_cls),
                "description": spec.get("description", ""),
                # -- bilingual display mirrors (see ``node_i18n``) ----------- #
                "name_zh": spec.get("name_zh", ""),
                "category_zh": spec.get("category_zh", ""),
                "description_en": spec.get("description_en", ""),
                "category": spec.get("category", ""),
                "tags": spec.get("tags", []),
                "module": getattr(node_cls, "__module__", ""),
                # -- v0.7.1 task E/F: capability tags + honest status grade -- #
                "capabilities": status["capabilities"],
                "implementation_status": status["implementation_status"],
                "availability": status["availability"],
                "deterministic": status["deterministic"],
                "required_software": status["required_software"],
                "missing_software": status["missing_software"],
                # -- v0.7.2 task P0-05: execution provenance --------------- #
                "capability_status": status["capability_status"],
                "execution_mode": status["execution_mode"],
                # -- v0.7.3 audit P0-4: the declaration above cannot describe a
                # run, so the modes the node *may* use and the one it uses by
                # default travel separately.  What a specific run used is
                # recorded in provenance, not here.
                "supported_execution_modes": status["supported_execution_modes"],
                "default_execution_mode": status["default_execution_mode"],
                "execution_mode_source": status["execution_mode_source"],
                "execution_mode_note": status["execution_mode_note"],
                "required_dependencies": status["required_dependencies"],
                "input_constraints": status["input_constraints"],
                "validation_evidence": status["validation_evidence"],
                "limitations": status["limitations"],
                "reproducibility_level": status["reproducibility_level"],
                **(
                    {"capability_status_note": status["capability_status_note"]}
                    if status.get("capability_status_note")
                    else {}
                ),
                **(
                    {"execution_mode_note": status["execution_mode_note"]}
                    if status.get("execution_mode_note")
                    else {}
                ),
            }
        )
    return records


def scan(package: str = "nodes") -> Dict[str, Any]:
    """Full scan report: modules imported, node records and category summary."""
    modules = iter_node_modules(package)
    records = collect_records()
    categories: Dict[str, int] = {}
    for record in records:
        categories[record["category"]] = categories.get(record["category"], 0) + 1

    # -- capability / status roll-up (v0.7.1 task F) ----------------------- #
    availability: Dict[str, int] = {}
    capability_counts: Dict[str, int] = {}
    missing_software: Dict[str, int] = {}
    capability_status: Dict[str, int] = {}
    execution_mode: Dict[str, int] = {}
    reproducibility: Dict[str, int] = {}
    for record in records:
        availability[record["availability"]] = availability.get(record["availability"], 0) + 1
        for capability in record["capabilities"]:
            capability_counts[capability] = capability_counts.get(capability, 0) + 1
        for name in record["missing_software"]:
            missing_software[name] = missing_software.get(name, 0) + 1
        # -- v0.7.2 task P0-05: how many nodes declare each execution mode -- #
        cs = record.get("capability_status", "executable")
        capability_status[cs] = capability_status.get(cs, 0) + 1
        em = record.get("execution_mode", "internal_approximation")
        execution_mode[em] = execution_mode.get(em, 0) + 1
        rl = record.get("reproducibility_level", "deterministic")
        reproducibility[rl] = reproducibility.get(rl, 0) + 1

    #: Nodes that must be assessed before a release: no evidence, or an
    #: external node whose program is absent.  Reported, never hidden.
    unverified = [
        record["type"]
        for record in records
        if not record.get("validation_evidence")
    ]

    return {
        "package": package,
        "modules_scanned": len(modules),
        "modules": modules,
        "nodes": records,
        "categories": [
            {"category": name, "count": count}
            for name, count in sorted(categories.items())
        ],
        "total_nodes": len(records),
        "availability_summary": dict(sorted(availability.items())),
        "capability_summary": dict(sorted(capability_counts.items())),
        "missing_software_summary": dict(sorted(missing_software.items())),
        # -- v0.7.2 task P0-05: execution provenance roll-up -------------- #
        "capability_status_summary": dict(sorted(capability_status.items())),
        "execution_mode_summary": dict(sorted(execution_mode.items())),
        "reproducibility_summary": dict(sorted(reproducibility.items())),
        "nodes_without_validation_evidence": len(unverified),
    }


def write_registry(path: Optional[str | Path] = None) -> Path:
    """Write ``registry.json`` next to this module and return its path."""
    import json

    target = Path(path) if path else Path(__file__).resolve().parent / "registry.json"
    report = scan()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return target
