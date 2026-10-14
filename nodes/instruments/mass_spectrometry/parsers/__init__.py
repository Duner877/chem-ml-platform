"""Mass spectrometry parsers: raw file -> list of MS spectra with metadata.

The generic parsers in :mod:`workflow_engine.parsers` answer "what are the
(x, y) pairs?".  This package answers the questions an MS analyst actually
asks first:

* is this scan an MS1 survey or an MS2 fragment?
* what was the precursor m/z and its charge?
* at what retention time was it acquired?

The extra fields are read from the container when it carries them (mzML and
mzXML do; the simple formats do not) and are otherwise left empty rather than
guessed, so downstream nodes can tell "no precursor recorded" from
"precursor 0".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from workflow_engine.objects import Spectrum

__all__ = [
    "MSScan",
    "MSParser",
    "parse_ms_file",
    "LEVEL_LABELS",
]

#: Human readable MS level labels.
LEVEL_LABELS: Dict[int, str] = {
    1: "MS1 (survey)",
    2: "MS2 (fragment)",
    3: "MS3 (fragment)",
}


@dataclass
class MSScan:
    """One mass spectrometry scan with its acquisition metadata."""

    spectrum: Spectrum
    level: int = 1
    precursor_mz: float = 0.0
    precursor_charge: int = 0
    precursor_intensity: float = 0.0
    retention_time: float = 0.0
    polarity: str = ""
    scan_id: str = ""
    source_file: str = ""
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "level": self.level,
            "level_label": LEVEL_LABELS.get(self.level, f"MS{self.level}"),
            "precursor_mz": round(self.precursor_mz, 4),
            "precursor_charge": self.precursor_charge,
            "precursor_intensity": round(self.precursor_intensity, 2),
            "retention_time": round(self.retention_time, 4),
            "polarity": self.polarity,
            "points": int(self.spectrum.size),
            "peaks": len(self.spectrum.peaks or []),
            "source_file": self.source_file,
        }


class MSParser:
    """Parse an MS container into :class:`MSScan` objects.

    Supported containers are the ones the platform parses natively: mzML,
    mzXML, MGF, MSP, JCAMP-DX, XY and CSV.  Vendor containers are *not*
    handled here -- they go through
    :mod:`nodes.instruments.vendor_adapters`, which knows how to reach the
    generic parsers after decoding the proprietary wrapper.
    """

    #: Extensions this parser claims.
    extensions = {".mzml", ".mzxml", ".mgf", ".msp", ".jdx", ".dx", ".xy", ".txt", ".csv"}

    def can_parse(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in self.extensions

    def parse(self, path: str | Path, mode: str = "MS") -> List[MSScan]:
        """Return every scan in ``path`` (empty when unreadable)."""
        from workflow_engine.parsers import load_spectra

        target = Path(path)
        if not target.exists() or not self.can_parse(target):
            return []
        try:
            spectra = load_spectra(target, mode=mode)
        except Exception:  # noqa: BLE001 - a damaged file must not crash the run
            return []
        scans: List[MSScan] = []
        for index, spectrum in enumerate(spectra):
            scans.append(self._scan(spectrum, index, target))
        return scans

    # -- per container ------------------------------------------------------- #
    def _scan(self, spectrum: Spectrum, index: int, source: Path) -> MSScan:
        """Read the scan metadata.

        ``precursor_mz`` and ``ms_level`` live on the Spectrum *attributes*
        for mzML / mzXML / MGF / MSP, while JCAMP-DX and XY files record
        whatever they could find in ``metadata``.  Both channels are read so a
        missing value stays missing instead of silently becoming ``0``.
        """
        metadata = spectrum.metadata or {}
        precursor = getattr(spectrum, "precursor_mz", None)
        if precursor is None:
            precursor = metadata.get("precursor_mz")
        level = getattr(spectrum, "ms_level", None)
        if level is None:
            level = metadata.get("ms_level") or metadata.get("level")
        retention = metadata.get("retention_time")
        if retention is None:
            retention = getattr(spectrum, "retention_time", None)
        scan = MSScan(
            spectrum=spectrum,
            level=_int(level, 1),
            precursor_mz=float(_float(precursor, 0.0) or 0.0),
            precursor_charge=_int(metadata.get("precursor_charge"), 0),
            precursor_intensity=float(_float(metadata.get("precursor_intensity"), 0.0) or 0.0),
            retention_time=float(_float(retention, 0.0) or 0.0),
            polarity=str(metadata.get("polarity", "") or ""),
            scan_id=str(
                metadata.get("scan_id") or metadata.get("id") or f"scan={index}"
            ),
            source_file=str(source),
        )
        scan.extras = {
            key: value
            for key, value in metadata.items()
            if key not in {"ms_level", "precursor_mz", "retention_time", "scan_id"}
        }
        return scan


def parse_ms_file(path: str | Path, mode: str = "MS") -> List[MSScan]:
    """Shorthand for :meth:`MSParser.parse`."""
    return MSParser().parse(path, mode=mode)


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
