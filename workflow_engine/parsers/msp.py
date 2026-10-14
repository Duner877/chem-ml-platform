"""Reader for NIST / MassBank ``.msp`` spectral library files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from ..objects import Peak, Spectrum

__all__ = ["read_msp"]

#: Keys carrying numeric values, used to populate the spectrum metadata.
_NUMERIC_KEYS = {"MW", "EXACTMASS", "PRECURSORMZ", "RETENTIONTIME"}


def read_msp(path: str | Path, **kwargs: Any) -> List[Spectrum]:
    """Parse an MSP file, returning one :class:`Spectrum` per record."""
    text = Path(path).read_text(encoding="utf-8", errors="ignore")
    spectra: List[Spectrum] = []
    header: Dict[str, Any] = {"metadata": {}}
    peaks: List[Peak] = []
    in_peaks = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if header or peaks:
                spectra.append(_build(header, peaks))
                header = {"metadata": {}}
                peaks = []
                in_peaks = False
            continue
        if ":" in stripped and not in_peaks:
            key, value = stripped.split(":", 1)
            key, value = key.strip(), value.strip()
            upper = key.upper()
            if upper in {"NUM PEAKS", "NUMPEAKS", "NPEAKS"}:
                in_peaks = True
                continue
            if upper == "NAME":
                header["name"] = value
            elif upper == "FORMULA":
                header["formula"] = value
            elif upper in {"PRECURSORMZ", "PRECURSOR M/Z", "EXACTMASS"}:
                try:
                    header["precursor_mz"] = float(value)
                except ValueError:
                    pass
            elif upper == "IONMODE" or upper == "ION_MODE":
                header["polarity"] = (
                    "negative" if value.lower().startswith("neg") else "positive"
                )
            else:
                if upper in _NUMERIC_KEYS:
                    try:
                        header["metadata"][key] = float(value)
                        continue
                    except ValueError:
                        pass
                header["metadata"][key] = value
            continue

        parts = stripped.replace(";", " ").replace(",", " ").split()
        if len(parts) < 2:
            continue
        try:
            x = float(parts[0])
            y = float(parts[1])
        except ValueError:
            continue
        in_peaks = True
        peaks.append(Peak(x=x, y=y, intensity=y))

    if header or peaks:
        spectra.append(_build(header, peaks))
    return spectra


def _build(header: Dict[str, Any], peaks: List[Peak]) -> Spectrum:
    peaks = sorted(peaks, key=lambda p: p.x)
    metadata = dict(header.get("metadata") or {})
    if header.get("formula"):
        metadata["formula"] = header["formula"]
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
        polarity=str(header.get("polarity") or "positive"),
        metadata=metadata,
    )
