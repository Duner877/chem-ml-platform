"""Chem ML Platform -- Python Node SDK.

Write a scientific node in a single file and drop it into ``plugins/``::

    # plugins/my_node.py
    from chemml_sdk import ScientificNode, Port, ParameterSpec, register_node
    from workflow_engine.objects import Text

    @register_node
    class HelloNode(ScientificNode):
        name = "Hello Science"
        category = "Custom"
        description = "Greet the operator."
        output_ports = [Port("text", "Text")]

        parameters = [
            ParameterSpec("who", "string", "world", "Whom to greet"),
        ]

        def execute(self, inputs, ctx=None):
            return {"text": Text(text=f"hello {self.get_param('who')}")}

Then either point the platform at the folder::

    CHEMML_PLUGINS=./plugins python -m nodes.loader

or let the default ``<repo>/plugins`` directory pick it up automatically.

The SDK re-exports the engine primitives so a plugin never has to know the
internal package layout.
"""

from chemml_sdk.client import ChemMLClient
from chemml_sdk.node import (
    DATA_TYPES,
    ParameterSpec,
    Port,
    ScientificNode,
    get_registry,
    load_nodes,
    register_node,
)

try:  # single source of truth (spec P0-04)
    from chemml_version import VERSION as __version__
except ImportError:  # pragma: no cover - SDK used outside the monorepo
    __version__ = "0.7.2"

__all__ = [
    "ChemMLClient",
    "DATA_TYPES",
    "ParameterSpec",
    "Port",
    "ScientificNode",
    "get_registry",
    "load_nodes",
    "register_node",
    "__version__",
]
