"""File format readers used by the instrument nodes.

Supported containers
--------------------

===============  ===========================================================
Extension        Reader
===============  ===========================================================
``.mzML``        HUPO PSI standard (base64 + zlib binary arrays)
``.mzXML``       Legacy XML format (m/z + intensity ``<peaks>`` payload)
``.mgf``         Mascot Generic Format
``.msp``         NIST / MassBank spectral library
``.jdx``/.dx``   JCAMP-DX (IR, Raman, NMR, MS, UV-Vis)
``.xy/.txt/.csv`` Generic two column ASCII
``.raw``         Thermo RAW: **not** parsed (proprietary) -- a clear error is
                 raised pointing to a conversion step (msconvert)
Bruker folders    ``fid``/``ser`` + ``acqus``, or ``1r``/``1rr`` + ``procs``
===============  ===========================================================
"""

from __future__ import annotations

import base64
import struct
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..objects import Peak, Spectrum
from ..utils import to_array

__all__ = [
    "load_spectrum",
    "load_spectra",
    "SUPPORTED_EXTENSIONS",
    "read_mgf",
    "read_msp",
    "read_mzml",
    "read_mzxml",
    "read_jcamp",
    "read_xy",
]

from .bruker import read_bruker, read_bruker_1r, read_bruker_fid, synthesize_fid  # noqa: E402
from .jcamp import is_jcamp, read_jcamp  # noqa: E402
from .mgf import read_mgf  # noqa: E402
from .msp import read_msp  # noqa: E402
from .mzml import read_mzml  # noqa: E402
from .xy import read_xy  # noqa: E402

SUPPORTED_EXTENSIONS = (
    ".mzml",
    ".mzxml",
    ".mgf",
    ".msp",
    ".jdx",
    ".dx",
    ".xy",
    ".txt",
    ".csv",
    ".asc",
)


# --------------------------------------------------------------------------- #
# mzXML legacy support
# --------------------------------------------------------------------------- #
def _decode_peaks(payload: str, precision: int, compressed: bool) -> tuple[list[float], list[float]]:
    raw = base64.b64decode("".join(payload.split()))
    if compressed:
        raw = zlib.decompress(raw)
    fmt = "<f8" if precision >= 64 else "<f4"
    count = len(raw) // struct.calcsize(fmt)
    values = struct.unpack(f"{fmt[0]}{count}{fmt[1:]}", raw[: count * struct.calcsize(fmt)])
    xs = [float(v) for v in values[0::2]]
    ys = [float(v) for v in values[1::2]]
    return xs, ys


def read_mzxml(path: str | Path, max_spectra: int = 200, **kwargs: Any) -> List[Spectrum]:
    """Read a legacy mzXML file (``<peaks>`` base64 payload)."""
    tree = ET.parse(str(path))
    root = tree.getroot()
    spectra: List[Spectrum] = []

    for scan in root.iter():
        if not scan.tag.endswith("scan"):
            continue
        if len(spectra) >= max_spectra:
            break
        peaks_node = None
        for child in scan:
            if child.tag.endswith("peaks"):
                peaks_node = child
                break
        if peaks_node is None or not peaks_node.text:
            continue
        precision = int(peaks_node.attrib.get("precision", "64"))
        compressed = peaks_node.attrib.get("compressionType", "none").lower() != "none"
        xs, ys = _decode_peaks(peaks_node.text, precision, compressed)
        precursor = None
        for child in scan.iter():
            if child.tag.endswith("precursorMz"):
                try:
                    precursor = float((child.text or "").strip())
                except ValueError:
                    precursor = None
                break
        spectra.append(
            Spectrum(
                mode="MS",
                technique="MS",
                name=f"scan {scan.attrib.get('num', len(spectra))}",
                x=xs,
                y=ys,
                x_unit="m/z",
                y_unit="intensity",
                peaks=[
                    Peak(x=float(x), y=float(y), intensity=float(y))
                    for x, y in zip(xs, ys)
                ],
                precursor_mz=precursor,
                metadata={"source_format": "mzXML"},
            )
        )
    return spectra


# --------------------------------------------------------------------------- #
# Dispatcher
# --------------------------------------------------------------------------- #
def load_spectra(
    path: str | Path, mode: str = "Generic", **kwargs: Any
) -> List[Spectrum]:
    """Load any supported spectral file and return its spectra."""
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"No such file: {source}")
    suffix = source.suffix.lower()

    if source.is_dir():
        return [read_bruker(source, **kwargs)]

    if suffix == ".mzml":
        return read_mzml(source, **kwargs)
    if suffix == ".mzxml":
        return read_mzxml(source, **kwargs)
    if suffix == ".mgf":
        return read_mgf(source, **kwargs)
    if suffix == ".msp":
        return read_msp(source, **kwargs)
    if suffix in {".jdx", ".dx"} or is_jcamp(source):
        return read_jcamp(source, **kwargs)
    if suffix in {".xy", ".txt", ".csv", ".asc", ".dat", ""}:
        return read_xy(source, mode=mode, **kwargs)
    if suffix == ".raw":
        raise ValueError(
            "Thermo .raw files are proprietary and cannot be read directly. "
            "Convert them first, e.g. `msconvert input.raw --mzML`."
        )
    raise ValueError(f"Unsupported file format: {suffix}")


def load_spectrum(
    path: str | Path, mode: str = "Generic", index: int = 0, **kwargs: Any
) -> Spectrum:
    """Load a single spectrum (``index`` selects the scan for containers)."""
    spectra = load_spectra(path, mode=mode, **kwargs)
    if not spectra:
        raise ValueError(f"No spectrum found in {path}")
    return spectra[min(index, len(spectra) - 1)]
