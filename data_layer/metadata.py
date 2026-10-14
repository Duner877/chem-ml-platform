"""Universal Scientific Data Layer -- metadata schema and provenance.

Every piece of experimental data entering the platform is described by the same
metadata vocabulary, no matter whether it came from a Thermo RAW file, a
JCAMP-DX export, a PubChem query or a built-in simulator.

The canonical envelope is :class:`data_layer.objects.ScientificDataObject`; this
module only describes *how* the data was obtained (provenance) and provides the
controlled vocabularies used to fill the envelope.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflow_engine.utils import new_id, now_iso

__all__ = [
    "DataProvenance",
    "VENDORS",
    "GENERIC_FORMATS",
    "VENDOR_FORMATS",
    "DATA_TYPES",
    "infer_data_type",
    "normalise_metadata",
]


# --------------------------------------------------------------------------- #
# Controlled vocabularies
# --------------------------------------------------------------------------- #
#: Instrument / database vendors recognised by the platform.  Each entry maps
#: the canonical vendor key to the file extensions it is known to produce.
VENDORS: Dict[str, Dict[str, Any]] = {
    "thermo": {
        "label": "Thermo Fisher",
        "extensions": [".raw", ".rawlf", ".d"],
        "adapters": ["ThermoAdapter"],
        "notes": "RAW is proprietary; msconvert / FreeStyle export required",
    },
    "waters": {
        "label": "Waters",
        "extensions": [".raw", ".arw", ".mwd"],
        "adapters": ["WatersAdapter"],
        "notes": "MassLynx .RAW directory; .arw single injection",
    },
    "agilent": {
        "label": "Agilent",
        "extensions": [".d", ".yep", ".ses"],
        "adapters": ["AgilentAdapter"],
        "notes": "ChemStation/MassHunter .d data directory",
    },
    "bruker": {
        "label": "Bruker",
        "extensions": [".d", ".fid", ".ser", ".1r", ".1rr"],
        "adapters": ["BrukerAdapter"],
        "notes": "fid/ser + acqus, or 1r/1rr + procs (TopSpin)",
    },
    "shimadzu": {
        "label": "Shimadzu",
        "extensions": [".qgd", ".lcd", ".spc"],
        "adapters": ["ShimadzuAdapter"],
        "notes": "LabSolutions export / classic .spc",
    },
    "generic": {
        "label": "Generic / open format",
        "extensions": [".mzml", ".mzxml", ".mgf", ".msp", ".jdx", ".dx", ".xy", ".txt", ".csv"],
        "adapters": [],
        "notes": "Vendor independent containers",
    },
}

#: Open, vendor independent containers the platform reads natively.
GENERIC_FORMATS: Dict[str, str] = {
    ".mzml": "mzML",
    ".mzxml": "mzXML",
    ".mgf": "MGF",
    ".msp": "MSP",
    ".jdx": "JCAMP-DX",
    ".dx": "JCAMP-DX",
    ".xy": "XY",
    ".txt": "XY",
    ".csv": "CSV",
}

#: Proprietary / vendor containers, mapped to the adapter able to open them.
VENDOR_FORMATS: Dict[str, str] = {
    ".raw": "Thermo RAW / Waters RAW",
    ".arw": "Waters ARW",
    ".d": "vendor data directory (Agilent / Bruker)",
    ".fid": "Bruker FID",
    ".ser": "Bruker SER",
    ".1r": "Bruker 1r",
    ".1rr": "Bruker 1rr",
    ".yep": "Agilent YEP",
    ".qgd": "Shimadzu QGD",
    ".lcd": "Shimadzu LCD",
    ".spc": "Shimadzu SPC",
}

#: Scientific data types carried by the data layer.  The values match the
#: ``type`` field of the wrapped scientific object wherever possible.
DATA_TYPES: List[str] = [
    "MassSpectrum",
    "NMRSpectrum",
    "IRSpectrum",
    "RamanSpectrum",
    "UVVisSpectrum",
    "FluorescenceSpectrum",
    "XPSSpectrum",
    "XASSpectrum",
    "XRDPattern",
    "SEMImage",
    "TEMImage",
    "AFMImage",
    "RamanMap",
    "FTIRImage",
    "HyperspectralImage",
    "ThermalCurve",
    "Voltammogram",
    "ImpedanceSpectrum",
    "ParticleSizeDistribution",
    "Isotherm",
    "Molecule",
    "Material",
    "Reaction",
    "Table",
    "Text",
    "Image",
    "ScientificReport",
]

#: Map a scientific object ``mode`` / ``technique`` onto a data-layer type.
_MODE_TO_TYPE: Dict[str, str] = {
    "ms": "MassSpectrum",
    "lcms": "MassSpectrum",
    "gcms": "MassSpectrum",
    "maldi": "MassSpectrum",
    "icpms": "MassSpectrum",
    "nmr": "NMRSpectrum",
    "ir": "IRSpectrum",
    "raman": "RamanSpectrum",
    "uv": "UVVisSpectrum",
    "uvvis": "UVVisSpectrum",
    "uv-vis": "UVVisSpectrum",
    "fluorescence": "FluorescenceSpectrum",
    "xps": "XPSSpectrum",
    "xes": "XASSpectrum",
    "xas": "XASSpectrum",
    "xrd": "XRDPattern",
    "sem": "SEMImage",
    "tem": "TEMImage",
    "afm": "AFMImage",
    "raman mapping": "RamanMap",
    "ftir imaging": "FTIRImage",
    "hyperspectral": "HyperspectralImage",
    "dsc": "ThermalCurve",
    "tga": "ThermalCurve",
    "dma": "ThermalCurve",
    "cv": "Voltammogram",
    "eis": "ImpedanceSpectrum",
    "dls": "ParticleSizeDistribution",
    "bet": "Isotherm",
}


def infer_data_type(scientific_object: Any) -> str:
    """Best-effort mapping of a scientific object onto a data-layer type."""
    obj_type = str(getattr(scientific_object, "type", "") or "")
    if obj_type and obj_type not in {"Spectrum", "Image"}:
        return obj_type

    # ``mode`` / ``technique`` are the primary hints; the object metadata is a
    # fallback because some parsers only record the technique there.
    metadata = getattr(scientific_object, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    hints: List[str] = []
    for attribute in ("mode", "technique"):
        hints.append(str(getattr(scientific_object, attribute, "") or "").strip().lower())
    for key in ("mode", "technique", "source_format"):
        hints.append(str(metadata.get(key, "") or "").strip().lower())

    for hint in hints:
        if hint and hint != "generic" and hint in _MODE_TO_TYPE:
            return _MODE_TO_TYPE[hint]
    return obj_type or "ScientificObject"


# --------------------------------------------------------------------------- #
# Provenance
# --------------------------------------------------------------------------- #
class DataProvenance:
    """Where a data object came from and how it was produced.

    The provenance is what makes a scientific result auditable: the same
    spectrum produced by a real instrument, by a vendor adapter with a missing
    binary, or by a built-in simulator carry different ``engine`` values.
    """

    __slots__ = ("acquired_at", "engine", "operator", "instrument", "notes")

    def __init__(
        self,
        acquired_at: str = "",
        engine: str = "",
        operator: str = "",
        instrument: str = "",
        notes: str = "",
    ) -> None:
        self.acquired_at = acquired_at or now_iso()
        self.engine = engine
        self.operator = operator
        self.instrument = instrument
        self.notes = notes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "acquired_at": self.acquired_at,
            "engine": self.engine,
            "operator": self.operator,
            "instrument": self.instrument,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "DataProvenance":
        payload = dict(data or {})
        return cls(
            acquired_at=str(payload.get("acquired_at", "") or ""),
            engine=str(payload.get("engine", "") or ""),
            operator=str(payload.get("operator", "") or ""),
            instrument=str(payload.get("instrument", "") or ""),
            notes=str(payload.get("notes", "") or ""),
        )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Provenance engine={self.engine!r} instrument={self.instrument!r}>"


# --------------------------------------------------------------------------- #
# Metadata helpers
# --------------------------------------------------------------------------- #
#: Canonical metadata keys.  Anything else a vendor adapter finds is preserved
#: verbatim under ``extras``.
CANONICAL_KEYS: List[str] = [
    "sample",
    "operator",
    "instrument",
    "method",
    "acquired_at",
    "vendor",
    "calibration",
    "conditions",
    "extras",
]


def normalise_metadata(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return ``raw`` with the canonical keys guaranteed to exist."""
    metadata: Dict[str, Any] = dict(raw or {})
    for key in CANONICAL_KEYS:
        metadata.setdefault(key, {} if key == "extras" else "")
    return metadata


def new_data_id() -> str:
    """Identifier of a freshly created data object."""
    return new_id("data_")
