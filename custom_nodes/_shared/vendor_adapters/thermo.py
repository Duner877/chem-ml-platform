"""Thermo Fisher vendor adapter (Xcalibur ``.raw`` folders).

A modern Thermo ``.raw`` is a **directory**: ``<n>/FileInfo.bin``,
``<n>/Method.txml``, ``ExternalCalibration.xml`` and friends.  The XML and
``.tm`` text companions are parsed for real acquisition metadata; the binary
acquisition payload is left to ``msconvert`` or to the generic adapter, which
is the documented escape hatch for proprietary containers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Text

from custom_nodes._shared.vendor_adapters.base import (
    VendorAdapter,
    register_vendor_adapter,
)

__all__ = ["ThermoAdapter"]


@register_vendor_adapter
class ThermoAdapter(VendorAdapter):
    """Reads Thermo Xcalibur / FreeStyle acquisition folders."""

    name = "ThermoAdapter"
    vendor = "thermo"
    extensions = [".raw", ".rawlf"]
    formats = ["Thermo RAW / Waters RAW"]
    description = "Thermo Xcalibur .raw folder: method/calibration metadata"
    directory_markers = ["method.txml", "fileinfo.bin", "externalcalibration.xml"]
    sidecar_files = ["method.txml", "fileinfo.bin", "title.txt"]

    # -- reading ------------------------------------------------------------- #
    def read_vendor(
        self,
        target: Path,
        sidecar: Dict[str, Any],
        **kwargs: Any,
    ) -> List[ScientificDataObject]:
        if target.is_dir():
            metadata = self._read_folder(target)
        else:
            metadata = self._read_file(target)
        if not metadata:
            return []
        metadata.update({k: v for k, v in sidecar.items() if k not in metadata})
        note = Text(
            name=f"Thermo acquisition {target.name}",
            text=_describe(target, metadata),
            metadata=metadata,
        )
        return [self.envelope(note, path=target, format_name="Thermo RAW")]

    # -- folder / file ------------------------------------------------------- #
    def _read_folder(self, target: Path) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {"source_format": "Thermo RAW folder"}
        methods = sorted(target.glob("*/Method.txml")) + sorted(target.glob("Method.txml"))
        if methods:
            metadata["method"] = _parse_txml(methods[0])
        calibrations = sorted(target.glob("*/ExternalCalibration.xml")) + sorted(
            target.glob("ExternalCalibration.xml")
        )
        if calibrations:
            metadata["calibration"] = _parse_xml(calibrations[0])
        injections = sorted(
            path for path in target.glob("*/") if path.is_dir() and path.name.isdigit()
        )
        if injections:
            metadata["injections"] = [path.name for path in injections]
            first = injections[0]
            metadata["acquired_at"] = _timestamp_of(first / "FileInfo.bin")
        return metadata

    def _read_file(self, target: Path) -> Dict[str, Any]:
        """A single file ``.raw``: only the signature can be read safely."""
        try:
            head = target.read_bytes()[:16]
        except OSError:
            return {}
        if head[:4] not in {b"OLE2", b"\xd0\xcf\x11\xe0", b"\x01\x0e\x84\x91"}:
            # Xcalibur RAW is an OLE2 compound document; anything else is not.
            if head[:2] != b"\x0e\x84":
                return {}
        return {
            "source_format": "Thermo RAW (compound document)",
            "signature": head[:4].hex(),
            "fallback": "RAW is an OLE2 container; export to mzML to load spectra",
        }


def _parse_xml(path: Path) -> Dict[str, Any]:
    """Flatten an XML sidecar into a flat metadata dictionary."""
    try:
        tree = ElementTree.parse(path)
    except (ElementTree.ParseError, OSError):
        return {}
    flat: Dict[str, Any] = {}
    for element in tree.getroot().iter():
        text = (element.text or "").strip()
        if text and not list(element):
            flat[element.tag.split("}")[-1]] = text
    return flat


def _parse_txml(path: Path) -> Dict[str, Any]:
    """Parse the interesting nodes of a Thermo ``Method.txml``."""
    flat = _parse_xml(path)
    keep = ("InstrumentMethod", "ChromatogramMethod", "MassSpectrometerMethod",
            "Analyzer", "Detector", "IonSource", "SprayVoltage", "IonMode",
            "MassRange", "Resolution", "ScanType", "Polarity")
    return {key: value for key, value in flat.items() if key in keep}


def _timestamp_of(path: Path) -> str:
    """Modification time of a sidecar as an ISO string."""
    from workflow_engine.utils import now_iso

    try:
        return now_iso(path.stat().st_mtime)
    except OSError:
        return ""


def _describe(target: Path, metadata: Dict[str, Any]) -> str:
    lines = [
        f"{target} is a Thermo Fisher acquisition container.",
        f"Method nodes : {len(metadata.get('method', {}) or {})}",
        f"Injections   : {', '.join(metadata.get('injections', []) or []) or 'none'}",
    ]
    if metadata.get("fallback"):
        lines.append(f"Fallback     : {metadata['fallback']}")
    lines.append("Export with msconvert (ProteoWizard) to mzML to load spectra.")
    return "\n".join(lines)
