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


def _decode_binary(binary: str, precision: str, compressed: bool) -> List[float]:
    """Decode an mzML ``<binary>`` payload into a list of floats."""
    raw = base64.b64decode("".join(binary.split()))
    if compressed:
        raw = zlib.decompress(raw)
    fmt = {
        _FLOAT32: "<f4",
        _FLOAT64: "<f8",
        _INT16: "<i2",
        _INT32: "<i4",
        _INT64: "<i8",
    }.get(precision, "<f8")
    count = len(raw) // struct.calcsize(fmt)
    values = struct.unpack(f"{fmt[0]}{count}{fmt[1:]}", raw[: count * struct.calcsize(fmt)])
    return [float(v) for v in values]


def read_mzml(path: str | Path, max_spectra: int = 200, **kwargs: Any) -> List[Spectrum]:
    """Read an mzML file and return its spectra (at most ``max_spectra``)."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    ns = _namespace(root.tag)
    prefix = f"{{{ns}}}" if ns else ""

    spectra: List[Spectrum] = []
    for spectrum_element in root.iter(f"{prefix}spectrum"):
        if len(spectra) >= max_spectra:
            break
        spectra.append(_parse_spectrum(spectrum_element, prefix))

    if not spectra:
        # Some vendors write chromatograms only: still return an empty list.
        return spectra
    return spectra


def _parse_spectrum(element: ET.Element, prefix: str) -> Spectrum:
    index = int(element.attrib.get("index", len(element.attrib)) or 0)
    spectrum_id = element.attrib.get("id", f"scan={index}")

    metadata: Dict[str, Any] = {"id": spectrum_id}
    arrays: Dict[str, List[float]] = {}

    for binary_array in element.iter(f"{prefix}binaryDataArray"):
        precision = _FLOAT64
        for cv in binary_array.findall(f"{prefix}cvParam"):
            accession = cv.attrib.get("accession", "")
            if accession in {_FLOAT32, _FLOAT64, _INT16, _INT32, _INT64}:
                precision = accession
        compressed = _has_cv(binary_array, _ZLIB)
        binary_node = binary_array.find(f"{prefix}binary")
        if binary_node is None or not binary_node.text:
            continue
        values = _decode_binary(binary_node.text, precision, compressed)
        if _has_cv(binary_array, _MZ_ARRAY):
            arrays["x"] = values
        elif _has_cv(binary_array, _INTENSITY_ARRAY):
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
