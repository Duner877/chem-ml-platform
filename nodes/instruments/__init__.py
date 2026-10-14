"""Virtual instrument nodes.

Each instrument behaves like its physical counterpart: it accepts a sample,
acquires a spectrum (or reuses the one provided upstream) and attaches an
interpretation table plus a textual report.  Formats understood by the
importers are listed in :data:`workflow_engine.parsers.SUPPORTED_EXTENSIONS`.
"""

from __future__ import annotations

from nodes.instruments._base import InstrumentNode
from nodes.instruments.ms import (
    GCMSNode,
    ICPMSNode,
    LCMSNode,
    MALDINode,
    MassSpectrometryNode,
)
from nodes.instruments.nmr import NMRNode
from nodes.instruments.vibrational import IRNode, RamanNode
from nodes.instruments.electronic import FluorescenceNode, UVVisNode
from nodes.instruments.surface import XPSNode, XASNode
from nodes.instruments.diffraction import SingleCrystalXRDNode, XRDNode
from nodes.instruments.microscopy import AFMNode, SEMNode, TEMNode
from nodes.instruments.thermal import DMANode, DSCNode, TGANode
from nodes.instruments.particle import BETNode, DLSNode
from nodes.instruments.imaging import (
    FTIRImagingNode,
    HyperspectralNode,
    RamanMappingNode,
)

__all__ = [
    "InstrumentNode",
    "MassSpectrometryNode",
    "LCMSNode",
    "GCMSNode",
    "MALDINode",
    "ICPMSNode",
    "NMRNode",
    "IRNode",
    "RamanNode",
    "UVVisNode",
    "FluorescenceNode",
    "XPSNode",
    "XASNode",
    "XRDNode",
    "SingleCrystalXRDNode",
    "SEMNode",
    "TEMNode",
    "AFMNode",
    "DSCNode",
    "TGANode",
    "DMANode",
    "DLSNode",
    "BETNode",
    "RamanMappingNode",
    "FTIRImagingNode",
    "HyperspectralNode",
]
