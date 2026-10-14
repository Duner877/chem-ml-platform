"""Node registry validator: check that a node record is well formed.

The validator is what keeps the auto-generated ``registry.json`` trustworthy.
It re-implements the structural rules of :class:`ScientificNode` without
importing the node, so a *stored* record can be checked long after the code
moved on -- which is exactly what the Node Marketplace needs before it offers
a node for installation.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflow_engine.ports import DATA_TYPES

__all__ = [
    "validate_record",
    "validate_records",
    "REQUIRED_KEYS",
    "KNOWN_PARAM_TYPES",
]

#: Keys every registry record must carry (spec section 2.1 + v0.7.2 task P0-05).
#: The execution-provenance keys are mandatory: a node that cannot state how it
#: runs and what backs that claim must not ship.
REQUIRED_KEYS = (
    "node_name",
    "type",
    "version",
    "inputs",
    "outputs",
    "description",
    "capability_status",
    "execution_mode",
    "reproducibility_level",
    "validation_evidence",
    "limitations",
)

#: Allowed values for the v0.7.2 provenance enums.
CAPABILITY_STATUSES = ("verified", "executable", "experimental", "unavailable")
EXECUTION_MODES = ("external", "internal_approximation", "synthetic_demo")
REPRODUCIBILITY_LEVELS = ("deterministic", "seeded", "nondeterministic")

#: Parameter types accepted by ``ParameterSpec.coerce``.
KNOWN_PARAM_TYPES = {
    "string",
    "text",
    "integer",
    "float",
    "number",
    "boolean",
    "enum",
    "path",
    "file",
    "molecule",
    "material",
    "list",
    "dict",
}

_PORT_KEYS = ("name", "data_type")


def _validate_ports(ports: Any, label: str, issues: List[str]) -> None:
    if not isinstance(ports, list):
        issues.append(f"{label} must be a list, got {type(ports).__name__}")
        return
    seen: set[str] = set()
    for index, port in enumerate(ports):
        if not isinstance(port, dict):
            issues.append(f"{label}[{index}] must be an object")
            continue
        for key in _PORT_KEYS:
            if key not in port:
                issues.append(f"{label}[{index}] is missing {key!r}")
        name = str(port.get("name", ""))
        if not name:
            issues.append(f"{label}[{index}] has an empty name")
        if name in seen:
            issues.append(f"{label} declares the duplicate port {name!r}")
        seen.add(name)
        data_type = str(port.get("data_type", "Any"))
        if data_type not in DATA_TYPES:
            issues.append(
                f"{label}[{index}] uses the unknown data type {data_type!r}"
            )


def _validate_parameters(parameters: Any, issues: List[str]) -> None:
    if parameters is None:
        return
    if not isinstance(parameters, list):
        issues.append("parameters must be a list")
        return
    seen: set[str] = set()
    for index, spec in enumerate(parameters):
        if not isinstance(spec, dict):
            issues.append(f"parameters[{index}] must be an object")
            continue
        name = str(spec.get("name", ""))
        if not name:
            issues.append(f"parameters[{index}] has an empty name")
        if name in seen:
            issues.append(f"parameters declares the duplicate entry {name!r}")
        seen.add(name)
        param_type = str(spec.get("type", "string"))
        if param_type not in KNOWN_PARAM_TYPES:
            issues.append(
                f"parameters[{index}] ({name!r}) uses the unknown type {param_type!r}"
            )
        if param_type == "enum" and not spec.get("options"):
            issues.append(f"parameters[{index}] ({name!r}) is an enum without options")


def validate_record(record: Dict[str, Any]) -> List[str]:
    """Return the list of problems of a single registry record (empty = valid)."""
    issues: List[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]

    for key in REQUIRED_KEYS:
        if key not in record:
            issues.append(f"missing required key {key!r}")

    if not str(record.get("node_name", "")).strip():
        issues.append("node_name is empty")
    type_name = str(record.get("type", ""))
    if not type_name.strip():
        issues.append("type is empty")
    elif not type_name[0].isalpha() or not type_name.replace("_", "").isalnum():
        issues.append(f"type {type_name!r} is not a valid identifier")
    version = str(record.get("version", ""))
    if version and not _looks_like_version(version):
        issues.append(f"version {version!r} is not semver-like")

    _validate_ports(record.get("inputs"), "inputs", issues)
    _validate_ports(record.get("outputs"), "outputs", issues)
    _validate_parameters(record.get("parameters"), issues)
    _validate_provenance(record, issues)
    return issues


def _validate_provenance(record: Dict[str, Any], issues: List[str]) -> None:
    """v0.7.2 task P0-05: the execution-provenance fields must be coherent.

    The point of these checks is honesty, not bureaucracy: a record that claims
    ``verified`` with no evidence, or ``external`` execution with no named
    dependency, is *wrong* and must fail the registry gate rather than reach a
    report.
    """
    status = str(record.get("capability_status", ""))
    if status not in CAPABILITY_STATUSES:
        issues.append(f"capability_status {status!r} is not one of {CAPABILITY_STATUSES}")
    elif status == "verified" and not list(record.get("validation_evidence") or []):
        issues.append("capability_status 'verified' requires a non-empty validation_evidence")

    mode = str(record.get("execution_mode", ""))
    if mode not in EXECUTION_MODES:
        issues.append(f"execution_mode {mode!r} is not one of {EXECUTION_MODES}")
    elif mode == "external":
        named = list(record.get("required_software") or []) + list(
            record.get("required_dependencies") or []
        )
        if not named:
            issues.append("execution_mode 'external' must name a required dependency")

    level = str(record.get("reproducibility_level", ""))
    if level not in REPRODUCIBILITY_LEVELS:
        issues.append(f"reproducibility_level {level!r} is not one of {REPRODUCIBILITY_LEVELS}")

    # A node whose external program is missing may not advertise itself as
    # available/verified -- the runtime probe already forced ``unavailable``.
    if record.get("availability") == "unavailable" and status not in {"unavailable", "experimental"}:
        issues.append(
            f"availability 'unavailable' contradicts capability_status {status!r}"
        )


def validate_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Validate a whole registry payload; returns a summary with per-record issues."""
    problems: Dict[str, List[str]] = {}
    types: Dict[str, int] = {}
    for record in records:
        issues = validate_record(record)
        if issues:
            problems[str(record.get("type", "<unknown>"))] = issues
        type_name = str(record.get("type", ""))
        types[type_name] = types.get(type_name, 0) + 1
    duplicates = [name for name, count in types.items() if count > 1]
    for name in duplicates:
        problems.setdefault(name, []).append(f"type {name!r} is registered more than once")
    return {
        "valid": not problems,
        "records": len(records),
        "problems": problems,
        "duplicate_types": duplicates,
    }


def _looks_like_version(value: str) -> bool:
    parts = value.strip().split(".")
    if not 1 <= len(parts) <= 3:
        return False
    return all(part.isdigit() for part in parts if part != "")
