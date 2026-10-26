"""Custom node library -- ComfyUI-style device-grouped node packages.

Why this exists
---------------
Before v0.7.4 the nodes lived in a single ``nodes/`` package whose
sub-packages followed the *code* layout (``instruments/``, ``simulation/``,
``ai/``) rather than the *user's* mental model.  Someone adding a new
LC-MS instrument had to guess which of those directories was theirs, and
adding a whole new device class meant creating a new top-level package plus
editing the loader's hard-coded import list.

This package follows the ComfyUI convention instead: **one directory per
device class, each a self-contained package**.  Adding a node is then

1. drop a ``.py`` file into the matching device directory, or
2. create a new device directory with an ``__init__.py`` and drop files in.

No registry edit, no loader edit -- discovery is automatic (see
:func:`discover`).

Layout
------
=================================  =============================================
Directory                           Device class

``mass_spectrometry/``              LC-MS, GC-MS, ICP-MS, MALDI, fragmentation
``spectroscopy/``                   UV-Vis, fluorescence, IR, Raman, NMR, imaging
``surface_characterization/``       XPS, XAS, BET, DLS, particle size
``thermal_analysis/``               TGA, DSC, DMA
``microscopy/``                     SEM, TEM, AFM
``diffraction/``                    XRD, single-crystal XRD
``electrochemistry/``               CV, EIS
``seismic/``                        survey, forward modelling, FWI
``battery_materials/``              pre-desolvation, dual-SEI, ageing
``quantum_chemistry/``              ORCA, Gaussian, Psi4, CP2K
``materials_simulation/``           ABACUS, VASP, Quantum ESPRESSO
``molecular_dynamics/``             GROMACS, LAMMPS, OpenMM
``databases/``                      spectral, chemical, materials databases
``foundation_models/``              ChemBERTa, GROVER, Graphormer, Uni-Mol
``ai_ml/``                          LLM, vision, property prediction, training
``data_io/``                        file import / export
``analysis/``                       generic spectrum analysis
``reporting/``                      report building, figure export
``agent/``                          scientific agent and planner
``questions/``                      high-level scientific question nodes
``gpu/``                            GPU / PyTorch nodes
``_shared/``                        base classes and vendor adapters
=================================  =============================================

How discovery works
-------------------
:func:`discover` walks this package with :func:`pkgutil.walk_packages`,
which is *recursive*: a device directory may hold sub-packages of its own
without any change here.  Importing a module is what registers its node
classes -- the ``@register_node`` decorator does the work -- so importing is
all discovery needs to do.

The legacy ``nodes`` package remains as a thin compatibility shim (see
``nodes/__init__.py``) so that ``from custom_nodes.mass_spectrometry.ms import LCMSNode``
keeps working; new code should import from ``custom_nodes`` directly.
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path
from typing import Any, Dict, List

__all__ = [
    "ROOT",
    "DISCOVERED_MODULES",
    "device_groups",
    "discover",
    "load_custom_nodes",
    "node_specs",
    "node_categories",
]

#: Repository root, so that ``models`` / ``simulations`` / ``workflow_engine``
#: stay importable no matter where the process was started from.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: Dotted names of every module this package imported, in discovery order.
DISCOVERED_MODULES: List[str] = []


def device_groups() -> List[str]:
    """Return the device-group directory names, sorted.

    A directory counts as a device group when it is a package (has an
    ``__init__.py``) and is not private (does not start with ``_``).
    """
    groups: List[str] = []
    for entry in sorted(Path(__file__).resolve().parent.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue
        if not (entry / "__init__.py").exists():
            continue
        groups.append(entry.name)
    return groups


def discover(package: str = "custom_nodes") -> List[str]:
    """Import every module under ``package`` so the nodes self-register.

    Returns the dotted names of the modules that were imported successfully.
    A module that fails to import is reported and skipped, so one broken
    third-party node cannot take the whole platform down.
    """
    imported: List[str] = []
    try:
        pkg = importlib.import_module(package)
    except ImportError:
        return imported

    for module_info in pkgutil.walk_packages(
        pkg.__path__, prefix=f"{pkg.__name__}."
    ):
        name = module_info.name
        if ".tests" in name or name.endswith("._tests"):
            continue
        try:
            importlib.import_module(name)
            imported.append(name)
        except Exception as exc:  # pragma: no cover - plugin isolation
            print(f"[custom_nodes] failed to import {name}: {exc}")

    DISCOVERED_MODULES[:] = imported
    return imported


def load_custom_nodes() -> List[str]:
    """Discover the custom nodes and return the imported module names."""
    return discover("custom_nodes")


def node_specs() -> List[Dict[str, Any]]:
    """Return the machine-readable description of every registered node."""
    from workflow_engine.registry import registry

    return registry.specs()


def node_categories() -> List[Dict[str, Any]]:
    """Return the per-category node counts."""
    from workflow_engine.registry import registry

    return registry.categories()
