"""Bruker vendor adapter (TopSpin ``.d`` experiment folders, ``.fid``, ``.ser``).

Two Bruker containers are genuinely readable without vendor software:

* the **parameter files** ``acqus`` / ``procs`` / ``title`` are plain text
  ``##$KEY = value`` files -- parsed for real;
* the **processed 1r** spectrum is a flat int32 array preceded by four header
  words.  The byte order is not stamped, so the adapter tries both and keeps
  the interpretation whose header is plausible (``0 < FTSIZE <= 2^28``).

Everything else (``fid`` free induction decay, ``ser`` time series, ``2rr``)
is reported with its metadata and handed to the generic adapter, which keeps
the provenance of the run honest instead of failing the workflow.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Peak, Spectrum

from nodes.instruments.vendor_adapters.base import (
    VendorAdapter,
    centroid,
    register_vendor_adapter,
)

__all__ = ["BrukerAdapter", "read_bruker_1r", "parse_bruker_parameter_file"]

#: 1r header word meanings, in order.
_1R_HEADER = ("FTSIZE", "FTTYPE", "FTSTPTS", "FTRESERVE")


@register_vendor_adapter
class BrukerAdapter(VendorAdapter):
    """Reads Bruker TopSpin experiment folders."""

    name = "BrukerAdapter"
    vendor = "bruker"
    extensions = [".d", ".fid", ".ser", ".1r", ".1rr"]
    formats = ["Bruker FID", "Bruker SER", "Bruker 1r", "Bruker 1rr"]
    description = "Bruker TopSpin (.d folder, acqus/procs, 1r/1rr) and fid/ser"
    directory_markers = ["acqus", "pdata", "fid", "1r"]
    sidecar_files = ["acqus", "procs", "title", "pulseprog", "samplename"]

    # -- discovery ----------------------------------------------------------- #
    def can_handle(self, path: str | Path) -> bool:
        target = Path(path)
        if target.is_dir():
            return self._directory_score(target) >= 2 or super().can_handle(target)
        return super().can_handle(target)

    # -- reading ------------------------------------------------------------- #
    def read_vendor(
        self,
        target: Path,
        sidecar: Dict[str, Any],
        **kwargs: Any,
    ) -> List[ScientificDataObject]:
        if target.is_dir():
            return self._read_experiment(target, sidecar)
        suffix = target.suffix.lower()
        if suffix == ".1r":
            spectrum = read_bruker_1r(target, parameters=sidecar)
            if spectrum is None:
                return []
            return [self.envelope(spectrum, path=target, format_name="Bruker 1r")]
        # fid / ser / 1rr / .d as a file: report metadata, let the caller
        # fall back to the generic adapter for the payload.
        return []

    def _read_experiment(
        self, target: Path, sidecar: Dict[str, Any]
    ) -> List[ScientificDataObject]:
        """Read the processed spectra stored under ``pdata/<n>/1r``."""
        objects: List[ScientificDataObject] = []
        for processed in sorted(target.glob("pdata/*")):
            for candidate in sorted(processed.glob("1r")) + sorted(processed.glob("1rr")):
                spectrum = read_bruker_1r(candidate, parameters=sidecar)
                if spectrum is None:
                    continue
                objects.append(
                    self.envelope(spectrum, path=candidate, format_name="Bruker 1r")
                )
        return objects


def parse_bruker_parameter_file(path: str | Path) -> Dict[str, Any]:
    """Parse a Bruker ``acqus`` / ``procs`` style parameter file."""
    found: Dict[str, Any] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip().lstrip("#$").strip()
        value = value.strip()
        if not key or key in found:
            continue
        if value.startswith("<") and value.endswith(">"):
            inner = value[1:-1].strip()
            found[key] = [
                _coerce(token.strip()) for token in inner.split(",") if token.strip()
            ]
        else:
            found[key] = _coerce(value)
    return found


def _coerce(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def read_bruker_1r(
    path: str | Path, parameters: Optional[Dict[str, Any]] = None
) -> Optional[Spectrum]:
    """Read a Bruker ``1r`` processed spectrum.

    The file starts with four int32 header words (``FTSIZE``, ``FTTYPE``,
    ``FTSTPTS``, ``FTRESERVE``) followed by ``FTSTPTS`` int32 data points.
    The byte order is not recorded, so both are tried and the plausible one
    wins -- a technique that keeps the reader usable across Bruker platforms.
    """
    target = Path(path)
    try:
        raw = target.read_bytes()
    except OSError:
        return None
    if len(raw) < 32:
        return None

    for order in ("<", ">"):
        header = struct.unpack_from(f"{order}4i", raw, 0)
        ftsize, _fttype, ftstpts, _ftreserve = header
        if not 0 < ftsize <= 2**28:
            continue
        if not 0 < ftstpts <= ftsize:
            continue
        expected = 16 + ftstpts * 4
        if len(raw) < expected:
            continue
        data = struct.unpack_from(f"{order}{ftstpts}i", raw, 16)
        return _spectrum_from_1r(target, data, header, order, parameters or {})
    return None


def _spectrum_from_1r(
    target: Path,
    data: tuple,
    header: tuple,
    order: str,
    parameters: Dict[str, Any],
) -> Spectrum:
    """Build a Spectrum out of a decoded 1r array."""
    count = len(data)
    y = [float(value) for value in data]

    # Bruker stores the sweep width and the offset in **ppm** in ``acqus``
    # (``SW_h`` is the same width in Hz).  The offset is the spectrum centre,
    # so the axis runs from ``O1 + SW/2`` down to ``O1 - SW/2``.
    x: List[float]
    x_unit = "point index"
    sw = _numeric(parameters.get("SW"))
    o1 = _numeric(parameters.get("O1"))
    if sw and o1 is not None:
        start_ppm = float(o1) + float(sw) / 2.0
        x = [
            round(start_ppm - float(sw) * (index / max(1, count - 1)), 6)
            for index in range(count)
        ]
        x_unit = "ppm"
    else:
        x = [float(index) for index in range(count)]

    peaks = [
        Peak(
            x=round(item["x"], 4),
            y=round(item["y"], 4),
            intensity=round(item["y"], 4),
            area=round(item["area"], 4),
            label="",
        )
        for item in centroid(x, y)
    ]

    nucleus = _first_text(parameters.get("NUC1") or parameters.get("nuc1"))
    technique = f"Bruker NMR ({nucleus})" if nucleus else "Bruker processed spectrum"

    return Spectrum(
        mode="NMR" if nucleus else "Bruker",
        technique=technique,
        name=target.stem,
        x=x,
        y=y,
        x_unit=x_unit,
        y_unit="intensity (a.u.)",
        peaks=peaks,
        metadata={
            "source_format": "Bruker 1r",
            "vendor": "bruker",
            "byte_order": "little" if order == "<" else "big",
            "FTSIZE": header[0],
            "FTSTPTS": header[2],
            "synthetic": False,
            "extras": {
                k: v
                for k, v in parameters.items()
                if k in {"SW", "SW_h", "O1", "SFO1", "NUC1", "TE", "P1", "D1", "NS", "RG", "AQ"}
            },
        },
    )


def _numeric(value: Any) -> Optional[float]:
    """First numeric value of a parameter (Bruker values may be lists)."""
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _numeric(item)
            if result is not None:
                return result
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _first_text(value: Any) -> str:
    """First string entry of a parameter (Bruker ``<a, b>`` becomes a list)."""
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return ""
    return str(value or "").strip()
