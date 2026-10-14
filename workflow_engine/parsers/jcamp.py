"""Reader for JCAMP-DX files (``.jdx``/``.dx``).

Supports the blocks produced by most IR/NMR/MS instruments:

* ``##XYDATA=(X++(Y..Y))`` -- first abscissa followed by packed ordinates
* ``##XYDATA=(XY..XY)``    -- explicit pairs
* ``##PEAK TABLE=(XY..XY)``-- peak lists

Packed/difference encodings (``PAC``, ``SQZ``, ``DIF``, ``DUP``, ``EZQ``) are
*detected* and reported: they are vendor specific and outside the scope of the
core reader.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..objects import Peak, Spectrum

__all__ = ["read_jcamp", "is_jcamp"]

_DATA_TYPE_MAP = {
    "INFRARED SPECTRUM": "IR",
    "IR SPECTRUM": "IR",
    "RAMAN SPECTRUM": "Raman",
    "NMR SPECTRUM": "NMR",
    "MASS SPECTRUM": "MS",
    "UV/VIS SPECTRUM": "UV-Vis",
    "FLUORESCENCE SPECTRUM": "Fluorescence",
}

_NUMBER = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")


def is_jcamp(path: str | Path) -> bool:
    """Heuristic: does the file look like a JCAMP-DX document?"""
    try:
        with Path(path).open("r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                if line.lstrip().startswith("##"):
                    return line.lstrip().upper().startswith("##JCAMP-DX")
                if line.strip():
                    break
    except OSError:
        return False
    return False


def read_jcamp(path: str | Path, **kwargs: Any) -> List[Spectrum]:
    """Parse a JCAMP-DX file into a list of spectra (usually one)."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    header: Dict[str, Any] = {"metadata": {}}
    xs: List[float] = []
    ys: List[float] = []
    peaks: List[Peak] = []
    mode = "Generic"
    data_format = ""
    in_data = False
    first_x = 0.0
    delta_x = 0.0
    x_factor = 1.0
    y_factor = 1.0

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("##"):
            upper = line.upper()
            if "XYDATA" in upper or "PEAK TABLE" in upper or "XYPOINTS" in upper:
                in_data = True
                data_format = line[line.find("(") + 1 : line.rfind(")")] if "(" in line else ""
                continue
            if upper.startswith("##END"):
                break
            key, _, value = line[2:].partition("=")
            key = key.strip().upper()
            value = value.strip()
            header["metadata"].setdefault(key, value)
            if key == "TITLE":
                header["name"] = value
            elif key == "DATA TYPE":
                mode = _DATA_TYPE_MAP.get(value.upper(), value.upper() or "Generic")
            elif key == "XUNITS":
                header["x_unit"] = value
            elif key == "YUNITS":
                header["y_unit"] = value
            elif key == "FIRSTX":
                try:
                    first_x = float(value)
                except ValueError:
                    pass
            elif key == "LASTX":
                try:
                    header["last_x"] = float(value)
                except ValueError:
                    pass
            elif key == "DELTAX":
                try:
                    delta_x = float(value)
                except ValueError:
                    pass
            elif key == "XFACTOR":
                try:
                    x_factor = float(value)
                except ValueError:
                    pass
            elif key == "YFACTOR":
                try:
                    y_factor = float(value)
                except ValueError:
                    pass
            elif key == "JCAMPDX":
                header["metadata"]["jcamp_version"] = value
            continue

        if not in_data:
            continue

        fmt = data_format.upper()
        if fmt.startswith("X++"):
            # "x y1 y2 y3 ..." on the FIRST data line; every following line
            # carries ordinates only.  Getting this wrong silently drops the
            # first ordinate of each continuation line, which shifts the whole
            # spectrum by one point.
            numbers = _NUMBER.findall(line)
            if not numbers:
                continue
            if not xs:
                first_x = float(numbers[0])
                ordinates = numbers[1:]
            else:
                ordinates = numbers
            for offset, token in enumerate(ordinates):
                xs.append(
                    first_x + (len(xs)) * abs(delta_x) * (-1.0 if delta_x < 0 else 1.0)
                )
                ys.append(float(token) * y_factor)
            continue
        if fmt.startswith("XY"):
            numbers = _NUMBER.findall(line)
            for i in range(0, len(numbers) - 1, 2):
                x_value = float(numbers[i]) * x_factor
                y_value = float(numbers[i + 1]) * y_factor
                if "PEAK" in fmt:
                    peaks.append(
                        Peak(x=x_value, y=y_value, intensity=y_value)
                    )
                else:
                    xs.append(x_value)
                    ys.append(y_value)
            continue
        # Unknown packed format
        if not header["metadata"].get("WARNING"):
            header["metadata"]["WARNING"] = (
                f"unsupported JCAMP data format {data_format!r}"
            )

    if not peaks and xs:
        peaks = [
            Peak(x=float(x), y=float(y), intensity=float(y))
            for x, y in zip(xs, ys)
        ]

    spectrum = Spectrum(
        mode=mode,
        technique=header["metadata"].get("DATA TYPE", mode),
        name=str(header.get("name") or Path(path).stem),
        x=[float(v) for v in xs],
        y=[float(v) for v in ys],
        x_unit=str(header.get("x_unit") or ""),
        y_unit=str(header.get("y_unit") or ""),
        peaks=peaks,
        metadata={
            key: value
            for key, value in header["metadata"].items()
            if value not in {"", None}
        },
    )
    return [spectrum]
