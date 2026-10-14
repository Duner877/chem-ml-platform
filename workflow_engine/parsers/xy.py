"""Reader for generic two-column ASCII spectra (``.xy``/``.txt``/``.csv``/``.asc``)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, List

from ..objects import Peak, Spectrum

__all__ = ["read_xy", "read_csv_spectrum"]

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
_SPLIT = re.compile(r"[,;\t]|\s{1,}")


def read_xy(
    path: str | Path,
    mode: str = "Generic",
    x_unit: str = "",
    y_unit: str = "",
    delimiter: str | None = None,
    **kwargs: Any,
) -> List[Spectrum]:
    """Read a two-column text file into a single :class:`Spectrum`.

    Lines starting with ``#``, ``;`` or ``//`` are treated as comments and can
    carry ``key=value`` metadata headers.
    """
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    xs: List[float] = []
    ys: List[float] = []
    metadata: dict = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("//") or line.startswith("!"):
            body = line.lstrip("#/! ").strip()
            if "=" in body:
                key, value = body.split("=", 1)
                metadata[key.strip()] = value.strip()
            continue
        if line.startswith(";"):
            continue
        parts = (
            line.split(delimiter)
            if delimiter
            else [token for token in _SPLIT.split(line) if token]
        )
        numbers: List[float] = []
        for token in parts:
            token = token.strip()
            match = _NUMBER.fullmatch(token)
            if match:
                numbers.append(float(token))
            if len(numbers) == 2:
                break
        if len(numbers) >= 2:
            xs.append(numbers[0])
            ys.append(numbers[1])

    if xs and xs[0] > xs[-1]:  # IR and NMR are usually stored descending
        xs.reverse()
        ys.reverse()

    peaks = [Peak(x=float(x), y=float(y), intensity=float(y)) for x, y in zip(xs, ys)]
    return [
        Spectrum(
            mode=mode,
            technique=mode,
            name=Path(path).stem,
            x=[float(v) for v in xs],
            y=[float(v) for v in ys],
            x_unit=x_unit or _guess_x_unit(mode),
            y_unit=y_unit or _guess_y_unit(mode),
            peaks=peaks,
            metadata=metadata,
        )
    ]


#: Alias kept for readability at call sites dealing with CSV exports.
read_csv_spectrum = read_xy


def _guess_x_unit(mode: str) -> str:
    return {
        "MS": "m/z",
        "NMR": "ppm",
        "IR": "cm-1",
        "Raman": "cm-1",
        "UV-Vis": "nm",
        "Fluorescence": "nm",
        "XRD": "2theta (deg)",
        "XPS": "eV",
        "XAS": "eV",
        "CV": "V",
        "EIS": "ohm",
        "DSC": "degC",
        "TGA": "degC",
        "DMA": "degC",
        "DLS": "nm",
        "BET": "P/P0",
    }.get(mode, "")


def _guess_y_unit(mode: str) -> str:
    return {
        "MS": "relative intensity",
        "NMR": "intensity",
        "IR": "absorbance",
        "Raman": "intensity",
        "UV-Vis": "absorbance",
        "Fluorescence": "intensity",
        "XRD": "intensity",
        "XPS": "counts",
        "XAS": "normalized absorption",
        "CV": "current (A)",
        "EIS": "-Zimag (ohm)",
        "DSC": "heat flow (mW)",
        "TGA": "mass (%)",
        "DMA": "storage modulus (MPa)",
        "DLS": "intensity (%)",
        "BET": "quantity adsorbed",
    }.get(mode, "intensity")
