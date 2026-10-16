"""Virtual instrument nodes.

Each instrument behaves like its physical counterpart: it accepts a sample,
acquires a spectrum (or reuses the one provided upstream) and attaches an
interpretation table plus a textual report.  Formats understood by the
importers are listed in :data:`workflow_engine.parsers.SUPPORTED_EXTENSIONS`.
"""

from __future__ import annotations

from nodes.instruments._base import InstrumentNode
from nodes.instruments.desolvation import (
    DesolvationSieveNode,
    DoubleSEIEnergeticsNode,
    ElectrolyteAgingNode,
    PreDesolvationMechanismNode,
)
from nodes.instruments.ms import (
    GCMSNode,
    ICPMSNode,
    LCMSNode,
    MALDINode,
    MassSpectrometryNode,
)
from nodes.instruments.seismic import (
    FWIInversionNode,
    SeismicForwardNode,
    SeismicSubmissionNode,
    SeismicSurveyNode,
)
from nodes.instruments.nmr import NMRNode
from nodes.instruments.vibrational import IRNode, RamanNode
from nodes.instruments.electronic import FluorescenceNode, UVVisNode
from nodes.instruments.surface import XPSNode, XASNode
from nodes.instruments.xas_sim2real import XASSim2RealNode
from nodes.instruments.diffraction import SingleCrystalXRDNode, XRDNode
from nodes.instruments.microscopy import AFMNode, SEMNode, TEMNode
from nodes.instruments.thermal import DMANode, DSCNode, TGANode
from nodes.instruments.particle import BETNode, DLSNode
from nodes.instruments.imaging import (
    FTIRImagingNode,
    HyperspectralNode,
    RamanMappingNode,
)
from nodes.instruments.fragmentation import FragmentationPathwayNode

__all__ = [
    "DesolvationSieveNode",
    "ElectrolyteAgingNode",
    "PreDesolvationMechanismNode",
    "DoubleSEIEnergeticsNode",
    "SeismicSurveyNode",
    "SeismicForwardNode",
    "FWIInversionNode",
    "SeismicSubmissionNode",
    "XASSim2RealNode",
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
    "FragmentationPathwayNode",
]
