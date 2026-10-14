"""Data source adapters: raw file -> :class:`ScientificDataObject`.

An adapter knows one container (``mzML``, ``JCAMP-DX``, ``Thermo RAW``, ...).
It turns bytes on disk into the universal envelope defined in
:mod:`data_layer.objects`.  Adapters are *registered* in
:class:`data_layer.registry.DataLayerRegistry`; vendor adapters register
themselves on import, so importing ``nodes.instruments.vendor_adapters`` is
enough to make them available.

Design rule: an adapter never raises for an unsupported file -- it returns an
empty list, and the registry reports which adapter *would* have been needed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.metadata import DataProvenance, VENDOR_FORMATS
from data_layer.objects import ScientificDataObject

__all__ = ["DataSourceAdapter", "GenericSpectrumAdapter", "sniff_format", "sniff_vendor"]


def sniff_format(path: str | Path) -> str:
    """Return the container name implied by a file extension."""
    suffix = Path(path).suffix.lower()
    return VENDOR_FORMATS.get(suffix, suffix.lstrip(".").upper() or "unknown")


def sniff_vendor(path: str | Path) -> str:
    """Guess the vendor from a file extension (``generic`` when open)."""
    suffix = Path(path).suffix.lower()
    if suffix in {".mzml", ".mzxml", ".mgf", ".msp", ".jdx", ".dx", ".xy", ".txt", ".csv"}:
        return "generic"
    if suffix in {".raw", ".arw", ".d", ".fid", ".ser", ".1r", ".1rr",
                  ".yep", ".qgd", ".lcd", ".spc"}:
        return "vendor"
    return "generic"


class DataSourceAdapter:
    """Base class of every data source adapter."""

    #: Human readable adapter name.
    name: str = "DataSourceAdapter"
    #: Canonical vendor key (``thermo``, ``waters``, ... or ``generic``).
    vendor: str = "generic"
    #: Extensions (lower case, with dot) this adapter claims.
    extensions: List[str] = []
    #: Container names this adapter claims.
    formats: List[str] = []
    #: Short description surfaced by the registry.
    description: str = ""

    # -- discovery ---------------------------------------------------------- #
    def can_handle(self, path: str | Path) -> bool:
        """True when this adapter recognises ``path``."""
        suffix = Path(path).suffix.lower()
        if self.extensions and suffix in self.extensions:
            return True
        return sniff_format(path) in self.formats

    def claims(self, path: str | Path) -> bool:
        """Alias of :meth:`can_handle` used by the registry."""
        return self.can_handle(path)

    # -- reading ------------------------------------------------------------ #
    def read(
        self, path: str | Path, **kwargs: Any
    ) -> List[ScientificDataObject]:
        """Read ``path`` and return zero or more data objects."""
        raise NotImplementedError(
            f"{self.name} must implement read(path, **kwargs)"
        )

    # -- helpers ------------------------------------------------------------ #
    def envelope(
        self,
        scientific_object: Any,
        *,
        path: str | Path = "",
        format_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        engine: str = "",
        notes: str = "",
    ) -> ScientificDataObject:
        """Build a :class:`ScientificDataObject` for ``scientific_object``."""
        merged: Dict[str, Any] = dict(metadata or {})
        if not merged.get("vendor"):
            merged["vendor"] = self.vendor
        if not merged.get("format"):
            merged["format"] = format_name or sniff_format(path)
        provenance = DataProvenance(
            engine=engine or self.name,
            instrument=merged.get("instrument", ""),
            notes=notes,
        )
        return ScientificDataObject.wrap(
            scientific_object,
            source=self.vendor,
            format=format_name or sniff_format(path),
            data_pointer=str(path),
            metadata=merged,
            provenance=provenance,
        )


class GenericSpectrumAdapter(DataSourceAdapter):
    """Reads every open spectral container through ``workflow_engine.parsers``.

    This adapter is the *generic* half of the compatibility system required by
    the specification: mzML, mzXML, MGF, MSP, JCAMP-DX and two column ASCII all
    funnel through here into a :class:`~workflow_engine.objects.Spectrum`.
    """

    name = "GenericSpectrumAdapter"
    vendor = "generic"
    extensions = [".mzml", ".mzxml", ".mgf", ".msp", ".jdx", ".dx", ".xy", ".txt", ".csv"]
    formats = ["mzML", "mzXML", "MGF", "MSP", "JCAMP-DX", "XY", "CSV"]
    description = "Open spectral containers: mzML / mzXML / MGF / MSP / JCAMP-DX / XY"

    def read(self, path: str | Path, **kwargs: Any) -> List[ScientificDataObject]:
        from workflow_engine.parsers import load_spectra

        target = Path(path)
        if not target.exists():
            return []
        try:
            spectra = load_spectra(target, **kwargs)
        except Exception:  # noqa: BLE001 - a bad file must not crash discovery
            return []
        objects: List[ScientificDataObject] = []
        for spectrum in spectra:
            spectrum.metadata.setdefault("source_format", sniff_format(target))
            objects.append(
                self.envelope(
                    spectrum,
                    path=target,
                    metadata={"instrument": spectrum.metadata.get("instrument", "")},
                    engine="workflow_engine.parsers",
                )
            )
        return objects
