"""Node library of the Chem ML Platform.

The package is discovered automatically by
:meth:`workflow_engine.registry.NodeRegistry.discover_package` -- importing a
module is enough for the :func:`~workflow_engine.registry.register_node`
decorator to expose the class.

Layout
------

=======================  ===================================================
Sub-package              Content
=======================  ===================================================
``nodes.question``       Top level scientific questions (what is it? / what
                         should we make?)
``nodes.instruments``    Virtual instruments (MS, NMR, IR, XRD, SEM, ...)
``nodes.ai``             LLM nodes, chemical foundation models, vision models
``nodes.databases``      Spectral / chemical / materials database connectors
``nodes.simulation``     Quantum chemistry, molecular dynamics, solid state
``nodes.io``             File import / export
``nodes.analysis``       Spectral processing, descriptors, similarity
``nodes.report``         Report generation
=======================  ===================================================

Every node inherits from :class:`workflow_engine.node_base.ScientificNode`:

.. code-block:: python

    @register_node
    class MyNode(ScientificNode):
        name = "My Node"
        category = "Analysis"
        input_ports = [Port("spectrum", "Spectrum")]
        output_ports = [Port("spectrum", "Spectrum")]
        parameters = [ParameterSpec("scale", "number", 1.0)]

        def execute(self, inputs, ctx=None):
            return {"spectrum": do_something(inputs["spectrum"])}
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

# --------------------------------------------------------------------------- #
# Make the repository root importable so that ``models``, ``simulations``,
# ``databases`` and ``workflow_engine`` resolve no matter how the nodes are
# loaded (pytest, uvicorn, `python -m nodes.loader`, external SDK, ...).
# --------------------------------------------------------------------------- #
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

__all__ = ["load_nodes", "node_specs", "node_categories", "ROOT"]


def load_nodes(plugins_directory: str | Path | None = None) -> List[str]:
    """Import every node module and return the registered type names.

    Parameters
    ----------
    plugins_directory:
        Optional folder scanned for third party ``*.py`` node plugins.  When
        omitted the ``CHEMML_PLUGINS`` environment variable is honoured and
        ``<root>/plugins`` is used as a last resort.
    """
    from workflow_engine.registry import registry

    registry.discover_package("nodes")

    import os

    candidates: List[Path] = []
    if plugins_directory is not None:
        candidates.append(Path(plugins_directory))
    else:
        if os.environ.get("CHEMML_PLUGINS"):
            candidates.append(Path(os.environ["CHEMML_PLUGINS"]))
        candidates.append(ROOT / "plugins")
    for directory in candidates:
        registry.discover_plugins(directory)

    return registry.types()


def node_specs() -> List[Dict[str, Any]]:
    """JSON description of every registered node."""
    from workflow_engine.registry import registry

    load_nodes()
    return registry.specs()


def node_categories() -> List[Dict[str, Any]]:
    """Registered nodes grouped by category."""
    from workflow_engine.registry import registry

    load_nodes()
    return registry.categories()
