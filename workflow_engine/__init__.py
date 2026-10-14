"""Chem ML Platform -- scientific workflow engine.

The package is deliberately framework agnostic: it only depends on NetworkX,
NumPy and Pydantic so that it can be embedded in the FastAPI backend, in a
Jupyter notebook, in the CLI or in the Node SDK without pulling the whole
stack.

Quick start
-----------

.. code-block:: python

    import nodes.loader as loader
    from workflow_engine import Workflow, WorkflowEngine

    loader.load_all()

    workflow = Workflow.from_dict(
        {
            "name": "demo",
            "nodes": [
                {"id": "1", "type": "LCMSNode", "params": {"compound": "caffeine"}},
                {"id": "2", "type": "PeakPickingNode", "params": {}},
            ],
            "edges": [["1", "2"]],
        }
    )
    result = WorkflowEngine().run(workflow)
    print(result.records["2"].outputs)
"""

from __future__ import annotations

from .cache import ResultCache, compute_cache_key
from .engine import ExecutionContext, RunResult, WorkflowEngine
from .errors import (
    ChemMLError,
    ExternalToolError,
    NodeExecutionError,
    NodeInputError,
    NodeNotFoundError,
    ObjectParseError,
    PortError,
    WorkflowValidationError,
)
from .events import ALL_EVENTS, Event, EventBus
from .node_base import ParameterSpec, ScientificNode
from .objects import (
    Atom,
    Bond,
    Component,
    CrystalStructure,
    Image,
    Material,
    Molecule,
    Peak,
    Reaction,
    ScientificObject,
    ScientificReport,
    SpectralMatch,
    Spectrum,
    Table,
    Text,
    deserialize_object,
    serialize_object,
)
from .ports import Port, port_by_name, types_compatible
from .registry import NodeRegistry, get_registry, register_node, registry
from .workflow import Workflow, WorkflowEdge, WorkflowNode

try:  # single source of truth (spec P0-04)
    from chemml_version import VERSION as __version__
except ImportError:  # pragma: no cover - package-standalone fallback
    __version__ = "0.7.2"

__all__ = [
    # engine
    "WorkflowEngine",
    "ExecutionContext",
    "RunResult",
    "ResultCache",
    "compute_cache_key",
    # models
    "Workflow",
    "WorkflowNode",
    "WorkflowEdge",
    # nodes
    "ScientificNode",
    "ParameterSpec",
    "registry",
    "get_registry",
    "NodeRegistry",
    "register_node",
    # ports
    "Port",
    "port_by_name",
    "types_compatible",
    # objects
    "ScientificObject",
    "Spectrum",
    "Peak",
    "Atom",
    "Bond",
    "Molecule",
    "Material",
    "Component",
    "CrystalStructure",
    "Table",
    "Image",
    "SpectralMatch",
    "Reaction",
    "Text",
    "ScientificReport",
    "serialize_object",
    "deserialize_object",
    # events & errors
    "Event",
    "EventBus",
    "ALL_EVENTS",
    "ChemMLError",
    "WorkflowValidationError",
    "NodeNotFoundError",
    "NodeInputError",
    "NodeExecutionError",
    "PortError",
    "ObjectParseError",
    "ExternalToolError",
    "__version__",
]
