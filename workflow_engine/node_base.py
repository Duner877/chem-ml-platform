"""Node base class and parameter specification.

Every node of the platform inherits from :class:`ScientificNode` and only has
to override :meth:`ScientificNode.execute`.  A node is a *pure function*:

.. code-block:: python

    class MyNode(ScientificNode):
        name = "My Node"
        category = "Analysis"
        input_ports = [Port("spectrum", "Spectrum")]
        output_ports = [Port("spectrum", "Spectrum")]
        parameters = [ParameterSpec("scale", "number", 1.0)]

        def execute(self, inputs, ctx):
            spectrum = inputs["spectrum"]
            return {"spectrum": scale(spectrum, self.get_param("scale"))}
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .errors import NodeExecutionError, NodeInputError
from .objects import ScientificObject
from .ports import Port, port_by_name, types_compatible

__all__ = [
    "ParameterSpec",
    "ScientificNode",
    "CAPABILITY_STATUSES",
    "EXECUTION_MODES",
    "REPRODUCIBILITY_LEVELS",
    "DependencyMissingError",
    "resolve_executable",
]

#: Allowed ``capability_status`` values (spec task P0-05).
CAPABILITY_STATUSES = ("verified", "executable", "experimental", "unavailable")

#: Allowed ``execution_mode`` values (spec task P0-05).
EXECUTION_MODES = ("external", "internal_approximation", "synthetic_demo")

#: Allowed ``reproducibility_level`` values (spec task P0-05).
REPRODUCIBILITY_LEVELS = ("deterministic", "seeded", "nondeterministic")


class DependencyMissingError(NodeExecutionError):
    """A declared external dependency is not installed.

    Distinct from a generic execution error so the API, the UI and the report
    can say "install X" instead of "the node failed".

    ``NodeExecutionError`` is constructed as ``(node_id, node_type, message)``
    because the engine raises it while a *running* node is already known.
    ``require_dependencies()`` is a classmethod called **before** a node instance
    exists, so it only has the class name and a message.  Accept both forms:
    ``DependencyMissingError("msg")`` and ``DependencyMissingError(id, type, "msg")``.
    """

    def __init__(self, *args: str):
        if len(args) == 1:
            # No node instance exists yet -- keep the caller's message verbatim
            # (no "[id:type]" prefix to leak an empty identifier).
            Exception.__init__(self, args[0])
            self.node_id = ""
            self.node_type = ""
        elif len(args) == 3:
            super().__init__(args[0], args[1], args[2])
        else:  # pragma: no cover - defensive, keeps linters happy
            raise TypeError(
                "DependencyMissingError expects (message) or (node_id, node_type, message)"
            )


def resolve_executable(name: str) -> Optional[str]:
    """Resolve an external program name to a path (PATH or ``CHEMML_*_PATH``).

    Mirrors :func:`node_registry.capabilities.resolve_software` but lives here so
    the engine can raise :class:`DependencyMissingError` without importing the
    registry (dependency direction: ``nodes`` -> ``workflow_engine``).
    """
    import os

    key = name.upper().replace(".", "_")
    for candidate in (
        os.environ.get(f"CHEMML_{key}_PATH"),
        os.environ.get(f"{key}_PATH"),
        os.environ.get(f"{key}_EXE"),
        shutil.which(name),
    ):
        if candidate and os.path.isfile(candidate):
            return str(candidate)
    return None


@dataclass
class ParameterSpec:
    """Declarative description of a node parameter (drives the GUI)."""

    name: str
    type: str = "string"  # string | text | number | integer | boolean | enum | file
    default: Any = None
    description: str = ""
    options: List[Any] = field(default_factory=list)
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    unit: str = ""
    advanced: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "description": self.description,
            "options": list(self.options),
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "unit": self.unit,
            "advanced": self.advanced,
        }

    def coerce(self, value: Any) -> Any:
        """Cast a raw (JSON) value to the declared parameter type."""
        if value is None:
            return self.default
        try:
            if self.type == "number":
                return float(value)
            if self.type == "integer":
                return int(float(value))
            if self.type == "boolean":
                if isinstance(value, bool):
                    return value
                return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
            if self.type == "enum":
                # Options are either plain values or ``(value, label)`` pairs;
                # accept both the raw value and its label.
                candidates = []
                for option in self.options:
                    if isinstance(option, (list, tuple)) and len(option) == 2:
                        candidates.append((option[0], option[1]))
                    else:
                        candidates.append((option, str(option)))
                for value_, label in candidates:
                    if value == value_ or value == label:
                        return value_
                if self.options:
                    first = self.options[0]
                    return first[0] if isinstance(first, (list, tuple)) and len(first) == 2 else first
                return value
            if self.type in {"string", "text", "file"}:
                return str(value)
        except (TypeError, ValueError):
            return self.default
        return value


class ScientificNode:
    """Base class of every scientific node."""

    # -- metadata (override in subclasses) -------------------------------- #
    name: str = "Scientific Node"
    category: str = "General"
    description: str = ""
    version: str = "0.1.0"
    icon: str = ""
    tags: List[str] = []
    aliases: List[str] = []
    #: Capability tags (v0.7.1 spec §4 / task E): requires_network,
    #: requires_gpu, requires_external_software, writes_files, long_running,
    #: experimental, sensitive_data, nondeterministic.  The GUI, the permission
    #: prompt and the agent task scheduler all read these.
    capabilities: List[str] = []

    #: Implementation / validation grade (task F, spec §F.2):
    #: ``implemented``   -- code exists and runs;
    #: ``executable``    -- runnable in this environment right now;
    #: ``validated``     -- passed a documented benchmark (task I);
    #: ``experimental``  -- works but is not scientifically validated;
    #: ``unavailable``   -- a dependency / runtime condition is missing.
    #: Nodes only *declare* their static grade; the registry combines it with a
    #: live executability probe so a missing external program is reported as
    #: ``unavailable`` instead of pretending to have run.
    implementation_status: str = "implemented"

    #: External executables this node may invoke (task E -- controlled
    #: execution).  ``simulations.runners.find_executable`` resolves them and
    #: the registry reports any that are missing.
    required_software: List[str] = []

    #: Determinism declaration (task F / H).  ``False`` for seeded-random,
    #: wall-clock-dependent or model-sampling nodes, so the platform never
    #: promises bit-identical repeat runs it cannot deliver.
    deterministic: bool = True

    # ------------------------------------------------------------------ #
    # v0.7.2 (spec task P0-05): execution provenance & capability bounds
    # ------------------------------------------------------------------ #
    #: ``verified``     -- an *independent* known-answer check proves the
    #:                     claim; **requires** ``validation_evidence``.
    #: ``executable``   -- runs correctly here, but not independently verified.
    #: ``experimental`` -- runs, but the science is not validated.
    #: ``unavailable``  -- a declared dependency is missing in this environment.
    capability_status: str = "executable"

    #: ``external``               -- the real third-party program does the work;
    #: ``internal_approximation`` -- a built-in model stands in for it;
    #: ``synthetic_demo``         -- demonstrative output over synthetic data.
    execution_mode: str = "internal_approximation"

    #: Concrete dependencies with optional version bounds, e.g.
    #: ``["orca >= 5.0", "openmm >= 8"]``.  ``required_software`` remains the
    #: machine-probeable executable list; this is the human-facing one.
    required_dependencies: List[str] = []

    #: Free-text statement of what inputs the node accepts and what it refuses.
    input_constraints: str = ""

    #: Evidence that backs ``capability_status``: test ids, benchmark reports,
    #: reference datasets.  Empty evidence can never yield ``verified``.
    validation_evidence: List[str] = []

    #: Known limitations, surfaced verbatim in the UI and exported reports.
    limitations: List[str] = []

    #: ``deterministic`` | ``seeded`` | ``nondeterministic``.
    reproducibility_level: str = "deterministic"

    cacheable: bool = True

    input_ports: List[Port] = []
    output_ports: List[Port] = []

    parameters: List[ParameterSpec] = []

    # -- runtime ----------------------------------------------------------- #
    def __init__(self, node_id: str = "", params: Optional[Dict[str, Any]] = None):
        self.node_id = node_id or ""
        self.params: Dict[str, Any] = dict(params or {})
        self.logs: List[str] = []

    # -- parameters -------------------------------------------------------- #
    def get_param(self, name: str, default: Any = None) -> Any:
        """Return a coerced parameter value with its declared default."""
        spec = self.param_spec(name)
        if spec is None:
            value = self.params.get(name, default)
            return value
        if name in self.params:
            return spec.coerce(self.params[name])
        return spec.default if spec.default is not None else default

    def param_spec(self, name: str) -> Optional[ParameterSpec]:
        for spec in self.parameters:
            if spec.name == name:
                return spec
        return None

    # -- logging ----------------------------------------------------------- #
    def log(self, message: str) -> None:
        self.logs.append(str(message))

    # -- graph contract ---------------------------------------------------- #
    @classmethod
    def node_type(cls) -> str:
        """Canonical node type identifier (the class name)."""
        return cls.__name__

    @classmethod
    def effective_capabilities(cls) -> List[str]:
        """Declared capability tags plus the determinism-derived tag."""
        caps = list(cls.capabilities)
        if not cls.deterministic and "nondeterministic" not in caps:
            caps.append("nondeterministic")
        return caps

    @classmethod
    def effective_capability_status(cls) -> Tuple[str, Optional[str]]:
        """The status a node may *honestly* claim, and why it was downgraded.

        v0.7.2 task P0-05: "未验证节点不得仅凭可以执行就标记为 verified" and
        "所有声明为 verified 的节点都有可追溯验证证据".  A node that declares
        ``verified`` without pointing at real evidence is silently downgraded to
        ``executable`` -- a self-assessment is not a verification.
        """
        declared = str(getattr(cls, "capability_status", "executable") or "executable")
        if declared not in CAPABILITY_STATUSES:
            return "executable", f"unknown capability_status {declared!r}"
        if declared == "verified" and not list(getattr(cls, "validation_evidence", []) or []):
            return "executable", "declared 'verified' but carries no validation_evidence"
        if declared == "verified" and "external" in str(getattr(cls, "execution_mode", "")):
            if list(getattr(cls, "required_software", []) or []) and not list(
                getattr(cls, "validation_evidence", []) or []
            ):
                return "executable", "external node without validation evidence"
        return declared, None

    @classmethod
    def effective_execution_mode(cls) -> Tuple[str, Optional[str]]:
        """The execution mode a node may honestly claim."""
        declared = str(getattr(cls, "execution_mode", "") or "")
        if declared not in EXECUTION_MODES:
            # Fall back to the most defensible reading of the declared metadata.
            if list(getattr(cls, "required_software", []) or []):
                return "internal_approximation", f"unknown execution_mode {declared!r}"
            return "internal_approximation", f"unknown execution_mode {declared!r}"
        if declared == "external" and not (
            list(getattr(cls, "required_software", []) or [])
            or list(getattr(cls, "required_dependencies", []) or [])
        ):
            return "internal_approximation", "declared 'external' without naming a dependency"
        return declared, None

    @classmethod
    def effective_reproducibility(cls) -> str:
        """Reproducibility level, kept consistent with ``deterministic``."""
        declared = str(getattr(cls, "reproducibility_level", "") or "")
        if declared in REPRODUCIBILITY_LEVELS:
            if declared == "deterministic" and not cls.deterministic:
                return "nondeterministic"
            return declared
        return "deterministic" if cls.deterministic else "nondeterministic"

    @classmethod
    def require_dependencies(cls) -> None:
        """Refuse to run when an ``external`` node's program is missing.

        Spec P0-05 #4: "不可用节点应阻止执行或明确要求安装依赖".  Raising here is
        the honest behaviour -- a node that silently degrades would let a user
        believe a real third-party calculation ran.
        """
        missing = [name for name in list(getattr(cls, "required_software", []) or [])
                   if resolve_executable(name) is None]
        if missing:
            hint = ", ".join(getattr(cls, "required_dependencies", []) or missing)
            raise DependencyMissingError(
                f"{cls.__name__}: 缺少外部程序 {', '.join(missing)}。"
                f"请安装后重试，或改用内置近似节点。声明的依赖：{hint}"
            )

    @classmethod
    def spec(cls) -> Dict[str, Any]:
        """Full JSON description consumed by the frontend."""
        status, status_note = cls.effective_capability_status()
        mode, mode_note = cls.effective_execution_mode()
        spec: Dict[str, Any] = {
            "type": cls.__name__,
            "name": cls.name,
            "category": cls.category,
            "description": cls.description,
            "version": cls.version,
            "icon": cls.icon or cls.name[:1].upper(),
            "tags": list(cls.tags),
            "capabilities": cls.effective_capabilities(),
            "implementation_status": cls.implementation_status,
            "deterministic": bool(cls.deterministic),
            "required_software": list(cls.required_software),
            "aliases": list(cls.aliases),
            # -- v0.7.2 task P0-05: execution provenance ------------------ #
            "capability_status": status,
            "execution_mode": mode,
            "required_dependencies": list(cls.required_dependencies),
            "input_constraints": cls.input_constraints,
            "validation_evidence": list(cls.validation_evidence),
            "limitations": list(cls.limitations),
            "reproducibility_level": cls.effective_reproducibility(),
            "inputs": [p.to_dict() for p in cls.input_ports],
            "outputs": [p.to_dict() for p in cls.output_ports],
            "parameters": [p.to_dict() for p in cls.parameters],
        }
        # A downgrade is recorded, never hidden: the frontend and the report can
        # both show *why* a node is not what it claimed.
        if status_note:
            spec["capability_status_note"] = status_note
        if mode_note:
            spec["execution_mode_note"] = mode_note
        return spec

    def validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """Check that every mandatory input is present and correctly typed."""
        provided = set(inputs or {})
        for port in self.input_ports:
            if port.name not in provided:
                if port.optional:
                    continue
                raise NodeInputError(
                    f"{self.node_type()}: missing mandatory input {port.name!r} "
                    f"({port.data_type})"
                )
            value = inputs[port.name]
            if value is None and not port.optional:
                raise NodeInputError(
                    f"{self.node_type()}: input {port.name!r} is empty"
                )
            if isinstance(value, list) and not port.multi and value and isinstance(
                value[0], ScientificObject
            ):
                raise NodeInputError(
                    f"{self.node_type()}: input {port.name!r} accepts a single "
                    f"connection but received {len(value)}"
                )
            if isinstance(value, ScientificObject):
                actual = getattr(value, "type", "Any")
                if not types_compatible(actual, port.data_type):
                    raise NodeInputError(
                        f"{self.node_type()}: input {port.name!r} expects "
                        f"{port.data_type} but received {actual}"
                    )

    # -- execution --------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """Run the node.  Override this method in subclasses."""
        raise NotImplementedError(
            f"{self.node_type()} must implement execute(inputs, ctx)"
        )

    def process(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """Validate inputs, execute the node and normalise the outputs."""
        inputs = dict(inputs or {})
        self.validate_inputs(inputs)
        try:
            outputs = self.execute(inputs, ctx)
        except (NodeInputError, NodeExecutionError):
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced to the GUI
            raise NodeExecutionError(self.node_id, self.node_type(), str(exc)) from exc
        if outputs is None:
            outputs = {}
        if not isinstance(outputs, dict):
            raise NodeExecutionError(
                self.node_id,
                self.node_type(),
                f"execute() must return a dict, got {type(outputs).__name__}",
            )
        return self._normalize_outputs(outputs)

    def _normalize_outputs(self, outputs: Dict[str, Any]) -> Dict[str, Any]:
        """Keep outputs aligned with the declared output ports."""
        declared = [p.name for p in self.output_ports]
        clean: Dict[str, Any] = {}
        for key, value in outputs.items():
            if declared and key not in declared:
                # Unknown key: keep it but do not break the run.
                self.log(f"warning: undeclared output {key!r}")
            clean[key] = value
        for port in self.output_ports:
            if port.name not in clean:
                clean[port.name] = None
        return clean

    # -- helpers for subclasses -------------------------------------------- #
    @staticmethod
    def first(value: Any) -> Any:
        """Return the first element when several connections were merged."""
        if isinstance(value, list):
            return value[0] if value else None
        return value

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<{self.node_type()} id={self.node_id!r}>"


def resolve_inputs(
    node: ScientificNode, incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """Map incoming edge data onto the declared input ports of ``node``.

    ``incoming`` maps a *target port name* to the value carried by the edge.
    When the port is unknown the value is forwarded with its raw key so that
    nodes with dynamic inputs can still consume it.
    """
    resolved: Dict[str, Any] = {}
    for key, value in incoming.items():
        port = port_by_name(node.input_ports, key)
        name = port.name if port else key
        resolved[name] = value
    return resolved
