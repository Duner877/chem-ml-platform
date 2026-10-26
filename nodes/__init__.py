"""Legacy import facade for the node library.

Since v0.7.4 the node implementations live in :mod:`custom_nodes`, grouped by
device class the way ComfyUI groups its custom nodes::

    custom_nodes/mass_spectrometry/     LC-MS, GC-MS, ICP-MS, MALDI
    custom_nodes/spectroscopy/          UV-Vis, IR, Raman, NMR
    custom_nodes/surface_characterization/   XPS, XAS, BET, DLS
    ...

Why this package still exists
-----------------------------
The node modules used to live here, and about a hundred places in the
repository still say ``from nodes.instruments.ms import LCMSNode``.  Rewriting
every one of them by hand is exactly the kind of bulk source edit that
silently breaks half the imports: ``py_compile`` stays green, the import
error only shows up when that particular node is first executed.

So the old paths are kept working by *aliasing* instead: importing this
package registers the new module objects under their old dotted names in
:data:`sys.modules`.  ``from nodes.instruments.ms import LCMSNode`` therefore
resolves to :mod:`custom_nodes.mass_spectrometry.ms` -- the same class
object, one implementation, no duplicated code.

New code should import from :mod:`custom_nodes` directly.

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

import importlib
import importlib.abc
import importlib.machinery
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


#: Old dotted name -> new dotted name.  The keys are the pre-0.7.4 paths;
#: the values point at the device-grouped packages under ``custom_nodes``.
#:
#: This table is the single place that knows about the old layout.  When a
#: node moves to another device group, one line here changes -- not a hundred
#: import statements.
_LEGACY_ALIASES: Dict[str, str] = {
    # ---- instruments ------------------------------------------------------ #
    "nodes.instruments.ms": "custom_nodes.mass_spectrometry.ms",
    "nodes.instruments.fragmentation": "custom_nodes.mass_spectrometry.fragmentation",
    "nodes.instruments.mass_spectrometry": "custom_nodes.mass_spectrometry.ms",
    "nodes.instruments.electronic": "custom_nodes.spectroscopy.electronic",
    "nodes.instruments.vibrational": "custom_nodes.spectroscopy.vibrational",
    "nodes.instruments.nmr": "custom_nodes.spectroscopy.nmr",
    "nodes.instruments.imaging": "custom_nodes.spectroscopy.imaging",
    "nodes.instruments.surface": "custom_nodes.surface_characterization.surface",
    "nodes.instruments.xas_sim2real": (
        "custom_nodes.surface_characterization.xas_sim2real"
    ),
    "nodes.instruments.particle": "custom_nodes.surface_characterization.particle",
    "nodes.instruments.thermal": "custom_nodes.thermal_analysis.thermal",
    "nodes.instruments.microscopy": "custom_nodes.microscopy.microscopy",
    "nodes.instruments.diffraction": "custom_nodes.diffraction.diffraction",
    "nodes.instruments.electro": "custom_nodes.electrochemistry.electro",
    "nodes.instruments.seismic": "custom_nodes.seismic.seismic",
    "nodes.instruments.desolvation": "custom_nodes.battery_materials.desolvation",
    "nodes.instruments._base": "custom_nodes._shared._base",
    "nodes.instruments.vendor_adapters": "custom_nodes._shared.vendor_adapters",
    # ---- simulation -------------------------------------------------------- #
    "nodes.simulation.quantum": "custom_nodes.quantum_chemistry.quantum",
    "nodes.simulation.materials_sim": (
        "custom_nodes.materials_simulation.materials_sim"
    ),
    "nodes.simulation.molecular_dynamics": (
        "custom_nodes.molecular_dynamics.molecular_dynamics"
    ),
    # ---- data & models ----------------------------------------------------- #
    "nodes.databases.spectral": "custom_nodes.databases.spectral",
    "nodes.databases.chemical": "custom_nodes.databases.chemical",
    "nodes.databases.materials_db": "custom_nodes.databases.materials_db",
    "nodes.ai.foundation": "custom_nodes.foundation_models.foundation",
    "nodes.ai.llm": "custom_nodes.ai_ml.llm",
    "nodes.ai.prediction": "custom_nodes.ai_ml.prediction",
    "nodes.ai.vision": "custom_nodes.ai_ml.vision",
    # ---- generic capabilities ---------------------------------------------- #
    "nodes.io": "custom_nodes.data_io.io",
    "nodes.analysis": "custom_nodes.analysis.analysis",
    "nodes.report": "custom_nodes.reporting.report",
    "nodes.report_agent": "custom_nodes.reporting.report_agent",
    "nodes.agent.agent": "custom_nodes.agent.agent",
    "nodes.agent.planner": "custom_nodes.agent.planner",
    "nodes.agent.reasoning": "custom_nodes.agent.reasoning",
    "nodes.agent.tools": "custom_nodes.agent.tools",
    "nodes.agent.workflow_generator": "custom_nodes.agent.workflow_generator",
    "nodes.question.discovery": "custom_nodes.questions.discovery",
    "nodes.question.identification": "custom_nodes.questions.identification",
    "nodes.gpu.gpu_nodes": "custom_nodes.gpu.gpu_nodes",
    "nodes._helpers": "custom_nodes._shared._helpers",
    "nodes.loader": "custom_nodes.loader",
}

#: The umbrella packages whose re-exports are the union of several device
#: groups.  Importing them must pull in every member group, otherwise
#: ``from nodes.instruments import XRDNode`` would find nothing.
_UMBRELLA_SOURCES: Dict[str, List[str]] = {
    "nodes.instruments": [
        "custom_nodes._shared._base",
        "custom_nodes.mass_spectrometry.ms",
        "custom_nodes.mass_spectrometry.fragmentation",
        "custom_nodes.spectroscopy.electronic",
        "custom_nodes.spectroscopy.vibrational",
        "custom_nodes.spectroscopy.nmr",
        "custom_nodes.spectroscopy.imaging",
        "custom_nodes.surface_characterization.surface",
        "custom_nodes.surface_characterization.xas_sim2real",
        "custom_nodes.surface_characterization.particle",
        "custom_nodes.thermal_analysis.thermal",
        "custom_nodes.microscopy.microscopy",
        "custom_nodes.diffraction.diffraction",
        "custom_nodes.electrochemistry.electro",
        "custom_nodes.seismic.seismic",
        "custom_nodes.battery_materials.desolvation",
    ],
    "nodes.simulation": [
        "custom_nodes.quantum_chemistry.quantum",
        "custom_nodes.materials_simulation.materials_sim",
        "custom_nodes.molecular_dynamics.molecular_dynamics",
    ],
    "nodes.ai": [
        "custom_nodes.foundation_models.foundation",
        "custom_nodes.ai_ml.llm",
        "custom_nodes.ai_ml.prediction",
        "custom_nodes.ai_ml.vision",
    ],
    "nodes.databases": [
        "custom_nodes.databases.spectral",
        "custom_nodes.databases.chemical",
        "custom_nodes.databases.materials_db",
    ],
    "nodes.question": [
        "custom_nodes.questions.discovery",
        "custom_nodes.questions.identification",
    ],
    "nodes.agent": [
        "custom_nodes.agent.agent",
        "custom_nodes.agent.planner",
        "custom_nodes.agent.reasoning",
        "custom_nodes.agent.tools",
        "custom_nodes.agent.workflow_generator",
    ],
    "nodes.gpu": [
        "custom_nodes.gpu.gpu_nodes",
    ],
}

#: Legacy umbrella package -> the modern package that replaced it.  The
#: umbrella forwards the modern package's own ``__all__`` as well, because
#: some public names live on the package itself rather than on one of its
#: modules (``custom_nodes.agent.INTENT_KEYWORDS`` and ``__version__``).
_MODERN_PACKAGES: Dict[str, str] = {
    "nodes.instruments": "custom_nodes",
    "nodes.simulation": "custom_nodes",
    "nodes.ai": "custom_nodes.ai_ml",
    "nodes.databases": "custom_nodes.databases",
    "nodes.question": "custom_nodes.questions",
    "nodes.agent": "custom_nodes.agent",
    "nodes.gpu": "custom_nodes.gpu",
}


def _modern_package_for(legacy: str) -> Any | None:
    """The modern package that backs a legacy umbrella, if there is one.

    Returned lazily and defensively: a missing modern package must not stop
    the legacy name from resolving, it only means the umbrella carries fewer
    names than it used to.
    """
    modern = _MODERN_PACKAGES.get(legacy)
    if modern is None:
        return None
    try:
        return importlib.import_module(modern)
    except ImportError:
        return None


def _build_umbrella(legacy: str) -> Any:
    """Build the umbrella module for a legacy package name.

    One implementation, two callers: the meta-path finder and the eager
    pre-population in :func:`_install_aliases`.  They used to be two copies
    of the same aggregation loop, and they drifted -- the eager copy did not
    know about the modern package's own ``__all__``, so
    ``from nodes.agent import __version__`` silently stopped working while
    the finder-based path still worked.  A facade that answers differently
    depending on *how* it was reached is worse than one that answers
    wrongly, because the failure is order-dependent.
    """
    import types

    members = _UMBRELLA_SOURCES.get(legacy, [])
    umbrella = types.ModuleType(legacy)
    umbrella.__doc__ = (
        f"Legacy facade for the {legacy.split('.')[-1]} node family. "
        "Import the device packages under ``custom_nodes`` directly."
    )
    umbrella.__path__ = []  # mark it as a package
    exported: List[str] = []

    # The modern *package* (not just its modules) is part of the public
    # surface: ``custom_nodes.agent`` defines ``INTENT_KEYWORDS`` and
    # ``__version__`` itself, and ``from nodes.agent import __version__``
    # used to work in 0.7.3.  Aggregating only the sub-modules would
    # silently drop those names.
    package = _modern_package_for(legacy)
    if package is not None:
        for attr in getattr(package, "__all__", []) or []:
            if hasattr(package, attr):
                setattr(umbrella, attr, getattr(package, attr))
                exported.append(attr)

    for member in members:
        try:
            mod = importlib.import_module(member)
        except ImportError:
            continue
        for attr in getattr(mod, "__all__", []) or []:
            if hasattr(mod, attr):
                setattr(umbrella, attr, getattr(mod, attr))
                if attr not in exported:
                    exported.append(attr)

    umbrella.__all__ = exported
    return umbrella


class _AliasLoader(importlib.abc.Loader):
    """Bind an already-imported module under a second, legacy name.

    Why not just hand back the modern module's own ``__spec__``
    -----------------------------------------------------------
    The import machinery keys ``sys.modules`` by ``spec.name`` and, for any
    spec it did not create itself, it *executes the loader* to build the
    module.  Returning ``custom_nodes.agent.agent``'s spec for the legacy
    name ``nodes.agent.agent`` therefore made the machinery re-run the source
    file a second time and register the result under the **modern** key.

    The visible consequence was two distinct module objects for one file::

        sys.modules['nodes.agent.agent']        -> copy A
        sys.modules['custom_nodes.agent.agent'] -> copy B   (copy A is not B)

    Everything that imported the legacy path got copy A while everything that
    imported the modern path got copy B.  A test that patched
    ``nodes.agent.agent.plan_only`` was patching a function the scheduler
    never called, and the failure surfaced as a *state machine* bug -- the
    agent went straight to ``RUNNING`` instead of ``WAITING_FOR_APPROVAL``
    -- which is a thoroughly misleading symptom for a name-resolution
    defect.  Node classes were duplicated the same way, so
    ``isinstance(node, custom_nodes...XNode)`` was false for a node
    instantiated through the legacy path.

    This loader hands the machinery the **existing** module object, so both
    names refer to one module and the file is executed exactly once.
    """

    def __init__(self, module: Any) -> None:
        self._module = module
        # The module's real identity, restored after the import machinery
        # overwrites ``__spec__`` with the alias spec.
        self._real_spec = getattr(module, "__spec__", None)

    def create_module(self, spec: Any) -> Any:
        return self._module

    def exec_module(self, module: Any) -> None:
        if self._real_spec is not None:
            # Keep the module pointing at its true home: ``reload()`` and
            # ``pkgutil`` both read ``__spec__`` to decide what to reload.
            module.__spec__ = self._real_spec


class _LegacyNodeFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Resolve ``nodes.*`` imports to their new home under ``custom_nodes``.

    Why a finder rather than pre-populating ``sys.modules``
    ------------------------------------------------------
    A test module does ``from nodes.agent.planner import Plan`` at **import
    time**, long before anything calls :func:`load_nodes`.  Pre-installing
    aliases would have to run at package-import time, and importing every
    device group eagerly creates a circular import: ``nodes`` -> ``agent`` ->
    ``nodes.agent`` -> ``nodes``.

    A meta-path finder avoids that entirely.  It is consulted only when
    Python actually fails to find ``nodes.x`` the normal way, and it resolves
    the name to the corresponding ``custom_nodes`` module *on demand* --
    one module at a time, exactly as if the old path had never moved.
    """

    def find_spec(self, fullname: str, path=None, target=None):
        if not fullname.startswith("nodes."):
            return None
        if fullname in sys.modules:
            return None

        # ``nodes.instruments`` and friends are umbrella packages whose
        # members now live in several device groups; they need a synthetic
        # module rather than a straight redirect.
        if fullname in _UMBRELLA_SOURCES:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)

        modern = _resolve_legacy(fullname)
        if modern is None:
            return None
        try:
            module = importlib.import_module(modern)
        except ImportError:
            return None

        # Bind the *same* module object under the legacy name.  The spec
        # carries the legacy name so ``sys.modules`` gets the right key, and
        # the loader returns the already-imported module instead of
        # executing the source a second time.
        spec = importlib.machinery.ModuleSpec(fullname, _AliasLoader(module))
        if hasattr(module, "__path__"):
            spec.submodule_search_locations = list(module.__path__)
        return spec

    def create_module(self, spec):
        legacy = spec.name
        return _build_umbrella(legacy)

    def exec_module(self, module) -> None:
        return None


def _resolve_legacy(fullname: str) -> str | None:
    """Map ``nodes.a.b`` onto the ``custom_nodes`` path that replaced it."""
    if fullname in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[fullname]
    for legacy, modern in _LEGACY_ALIASES.items():
        if fullname.startswith(legacy + "."):
            return modern + fullname[len(legacy):]
    return None


def _install_aliases() -> None:
    """Make sure the legacy import paths keep resolving.

    The meta-path finder does the real work; this function only guarantees
    it is registered, and additionally pre-populates the umbrella packages
    so that ``from nodes.instruments import XRDNode`` works even when the
    finder is bypassed.
    """
    if not any(isinstance(f, _LegacyNodeFinder) for f in sys.meta_path):
        sys.meta_path.insert(0, _LegacyNodeFinder())

    for legacy in _UMBRELLA_SOURCES:
        if legacy in sys.modules:
            continue
        umbrella = _build_umbrella(legacy)
        sys.modules[legacy] = umbrella
        parent, _, leaf = legacy.rpartition(".")
        if parent and parent in sys.modules:
            setattr(sys.modules[parent], leaf, umbrella)


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

    _install_aliases()
    registry.discover_package("custom_nodes")
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


# --------------------------------------------------------------------------- #
# Register the finder at import time.                                      #
#                                                                            #
# A test module does ``from nodes.agent.planner import Plan`` while it is    #
# being collected -- long before anything calls ``load_nodes()``.  Waiting    #
# for that call would mean every such import fails with                     #
# ``ModuleNotFoundError: No module named 'nodes.agent'``, and the failure    #
# appears as a *collection* error, which reads like a broken test file      #
# rather than a missing alias.                                               #
# --------------------------------------------------------------------------- #
_install_aliases()
