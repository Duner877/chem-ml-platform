"""Node authoring primitives.

These are thin re-exports of :mod:`workflow_engine` so that a plugin author
only imports ``chemml_sdk``.  Everything a node needs is available:

``ScientificNode``  base class (``execute(inputs, ctx)``, ``get_param``, ``log``)
``Port``            named, typed connection point of a node
``ParameterSpec``   declarative parameter description
``register_node``   class decorator that publishes the node in the registry
``load_nodes``      discover the built-in nodes plus ``plugins/``
``get_registry``    the global :class:`~workflow_engine.registry.NodeRegistry`
"""

from __future__ import annotations

from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.ports import DATA_TYPES, Port
from workflow_engine.registry import (
    NodeRegistry,
    get_registry,
    register_node,
)

__all__ = [
    "DATA_TYPES",
    "ParameterSpec",
    "Port",
    "ScientificNode",
    "NodeRegistry",
    "get_registry",
    "register_node",
    "load_nodes",
    "node_specs",
    "node_categories",
]


def load_nodes(plugins_directory: str | None = None) -> list:
    """Import every built-in node and every plugin found in the directory.

    Parameters
    ----------
    plugins_directory:
        Folder scanned for third-party ``*.py`` node plugins.  When omitted,
        ``CHEMML_PLUGINS`` is honoured and ``<repo>/plugins`` is the fallback.
    """
    from nodes import load_nodes as _load

    return _load(plugins_directory)


def node_specs() -> list:
    """JSON description of every registered node."""
    from nodes import node_specs as _specs

    return _specs()


def node_categories() -> list:
    """Registered nodes grouped by category."""
    from nodes import node_categories as _categories

    return _categories()
