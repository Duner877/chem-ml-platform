"""Reader for Mascot Generic Format (``.mgf``) peak lists."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..objects import Peak, Spectrum

__all__ = ["read_mgf"]


def read_mgf(path: str | Path, **kwargs: Any) -> List[Spectrum]:
    """Read an MGF file and return one :class:`Spectrum` per ``BEGIN IONS``."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    spectra: List[Spectrum] = []
    current: Dict[str, Any] | None = None
    peaks: List[Peak] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("BEGIN IONS"):
            current = {"metadata": {}}
            peaks = []
            continue
        if line.startswith("END IONS"):
            if current is not None:
                spectra.append(_build(current, peaks))
            current = None
            peaks = []
            continue
        if current is None:
            continue
        if line.startswith("TITLE="):
            current["name"] = line.split("=", 1)[1].strip()
            continue
        if line.startswith("PEPMASS="):
            token = line.split("=", 1)[1].strip().split()
            try:
                current["precursor_mz"] = float(token[0])
            except (ValueError, IndexError):
                pass
            continue
        if line.startswith("CHARGE="):
            token = line.split("=", 1)[1].strip()
            current["polarity"] = "negative" if "-" in token else "positive"
            continue
        if line.startswith("SCANS=") or line.startswith("RTINSECONDS="):
            key = "scan" if line.startswith("SCANS") else "rt"
            try:
                current["metadata"][key] = float(line.split("=", 1)[1].strip())
            except ValueError:
                current["metadata"][key] = line.split("=", 1)[1].strip()
            continue
        if line.startswith("MSLEVEL="):
            try:
                current["ms_level"] = int(float(line.split("=", 1)[1]))
            except ValueError:
                pass
            continue
        if "=" in line and not line[0].isdigit():
            key, value = line.split("=", 1)
            current["metadata"][key.strip()] = value.strip()
            continue
        # Peak line: "mz intensity [charge]"
        parts = line.replace(";", " ").split()
        if not parts:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1]) if len(parts) > 1 else 0.0
        except ValueError:
            continue
        peaks.append(Peak(x=x, y=y, intensity=y))

    if current is not None:
        spectra.append(_build(current, peaks))
    return spectra


def _build(header: Dict[str, Any], peaks: List[Peak]) -> Spectrum:
    peaks = sorted(peaks, key=lambda p: p.x)
    return Spectrum(
        mode="MS",
        technique="MS",
        name=str(header.get("name") or ""),
        x=[p.x for p in peaks],
        y=[p.y for p in peaks],
        x_unit="m/z",
        y_unit="relative intensity",
        peaks=peaks,
        precursor_mz=header.get("precursor_mz"),
        ms_level=int(header.get("ms_level") or 1),
        polarity=str(header.get("polarity") or "positive"),
        metadata=dict(header.get("metadata") or {}),
    )
