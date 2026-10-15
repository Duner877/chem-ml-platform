"""Reader for the HUPO PSI mzML standard (``.mzML``).

The parser walks the XML tree, decodes the base64 encoded binary arrays and
supports the two compression schemes seen in practice:

* ``MS:1000574`` zlib / deflate compression
* ``MS:1000576`` no compression

Floating point encodings understood: ``MS:1000521`` (32-bit float) and
``MS:1000523`` (64-bit float), plus the integer encodings
``MS:1000519``/``MS:1000522`` (16/64-bit int).
"""

from __future__ import annotations

import base64
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..objects import Peak, Spectrum

__all__ = ["read_mzml"]

_MZ_ARRAY = "MS:1000514"
_INTENSITY_ARRAY = "MS:1000515"
_ZLIB = "MS:1000574"
_NO_COMPRESSION = "MS:1000576"
_FLOAT32 = "MS:1000521"
_FLOAT64 = "MS:1000523"
_INT16 = "MS:1000519"
_INT32 = "MS:1000520"
_INT64 = "MS:1000522"

_MS_LEVEL = "MS:1000511"
_SCAN_TIME = "MS:1000016"
_SELECTED_ION = "MS:1000744"
_COLLISION_ENERGY = "MS:1000045"
_POSITIVE = "MS:1000130"
_NEGATIVE = "MS:1000129"


def _namespace(tag: str) -> str:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _cv_value(element: ET.Element, accession: str) -> Optional[str]:
    for child in element.iter():
        if child.tag.endswith("cvParam") and child.attrib.get("accession") == accession:
            return child.attrib.get("value")
    return None


def _has_cv(element: ET.Element, accession: str) -> bool:
    for child in element.iter():
        if child.tag.endswith("cvParam") and child.attrib.get("accession") == accession:
            return True
    return False


#: accession -> single ``struct`` format character.  mzML integer arrays are
#: signed; ``<f``/``<d`` cover the two float encodings.
_STRUCT_CODE = {
    _FLOAT32: "f",
    _FLOAT64: "d",
    _INT16: "h",
    _INT32: "i",
    _INT64: "q",
}

def _decode_binary(binary: str, precision: str, compressed: bool) -> List[float]:
    """Decode an mzML ``<binary>`` payload into a list of floats."""
    raw = base64.b64decode("".join(binary.split()))
    if compressed:
        raw = zlib.decompress(raw)
    code = _STRUCT_CODE.get(precision, "d")
    size = struct.calcsize("<" + code)
    count = len(raw) // size
    values = struct.unpack(f"<{count}{code}", raw[: count * size])
    return [float(v) for v in values]


def read_mzml(path: str | Path, max_spectra: int = 200, **kwargs: Any) -> List[Spectrum]:
    """Read an mzML file and return its spectra (at most ``max_spectra``)."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    ns = _namespace(root.tag)
    prefix = f"{{{ns}}}" if ns else ""

    # Collect referenceable param groups: id -> {"accessions": [...]}.
    param_groups: Dict[str, Dict[str, str]] = {}
    for group_element in root.iter(f"{prefix}referenceableParamGroup"):
        group_id = group_element.attrib.get("id", "")
        accessions = [
            cv.attrib.get("accession", "")
            for cv in group_element.findall(f"{prefix}cvParam")
        ]
        param_groups[group_id] = {"accessions": accessions}

    spectra: List[Spectrum] = []
    for spectrum_element in root.iter(f"{prefix}spectrum"):
        if len(spectra) >= max_spectra:
            break
        spectra.append(_parse_spectrum(spectrum_element, prefix, param_groups))

    if not spectra:
        # Some vendors write chromatograms only: still return an empty list.
        return spectra
    return spectra


def _parse_spectrum(
    element: ET.Element,
    prefix: str,
    param_groups: Optional[Dict[str, Dict[str, str]]] = None,
) -> Spectrum:
    index = int(element.attrib.get("index", len(element.attrib)) or 0)
    spectrum_id = element.attrib.get("id", f"scan={index}")

    metadata: Dict[str, Any] = {"id": spectrum_id}
    arrays: Dict[str, List[float]] = {}
    param_groups = param_groups or {}

    for binary_array in element.iter(f"{prefix}binaryDataArray"):
        # v0.7.2 fix: many writers (e.g. imzML converters) put the precision /
        # compression cvParams into ``referenceableParamGroup`` definitions and
        # only place a ``<referenceableParamGroupRef>`` on the array itself, so
        # the group's params must be merged in before the direct children.
        accessions: List[str] = []
        for child in binary_array:
            if child.tag.endswith("cvParam"):
                accessions.append(child.attrib.get("accession", ""))
        ref = binary_array.find(f"{prefix}referenceableParamGroupRef")
        if ref is not None:
            group = param_groups.get(ref.attrib.get("ref", ""), {})
            accessions.extend(group.get("accessions", []))
        precision = _FLOAT64
        for accession in accessions:
            if accession in _STRUCT_CODE:
                precision = accession
                break
        compressed = _ZLIB in accessions
        binary_node = binary_array.find(f"{prefix}binary")
        if binary_node is None or not binary_node.text:
            continue
        values = _decode_binary(binary_node.text, precision, compressed)
        if _MZ_ARRAY in accessions:
            arrays["x"] = values
        elif _INTENSITY_ARRAY in accessions:
            arrays["y"] = values

    level_raw = _cv_value(element, _MS_LEVEL)
    ms_level = int(float(level_raw)) if level_raw else 1
    scan_time = _cv_value(element, _SCAN_TIME)
    if scan_time:
        metadata["scan_time"] = float(scan_time)
        metadata["scan_time_unit"] = "minute"
    selected = _cv_value(element, _SELECTED_ION)
    precursor = float(selected) if selected else None
    ce = _cv_value(element, _COLLISION_ENERGY)
    collision = float(ce) if ce else None

    polarity = "negative" if _has_cv(element, _NEGATIVE) else "positive"

    xs = arrays.get("x", [])
    ys = arrays.get("y", [])
    if len(ys) < len(xs):
        ys = ys + [0.0] * (len(xs) - len(ys))
    peaks = [
        Peak(x=float(x), y=float(y), intensity=float(y)) for x, y in zip(xs, ys)
    ]
    return Spectrum(
        mode="MS",
        technique="MS",
        name=f"scan {index}",
        x=[float(v) for v in xs],
        y=[float(v) for v in ys],
        x_unit="m/z",
        y_unit="intensity",
        peaks=peaks,
        precursor_mz=precursor,
        ms_level=ms_level,
        polarity=polarity,
        collision_energy=collision,
        metadata=metadata,
    )
