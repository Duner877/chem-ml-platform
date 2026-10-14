"""Agilent vendor adapter (ChemStation / MassHunter ``.d`` data folders).

An Agilent ``.d`` folder holds ``data.bin`` (the chromatogram), the MS
acquisition block and text companions (``*.M`` method, ``AcqData/MSTable``).
Only the text companions are parsed here; the binary payload is exported to
mzML / JCAMP-DX before it can enter the universal data layer.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Text

from nodes.instruments.vendor_adapters.base import (
    VendorAdapter,
    register_vendor_adapter,
)

__all__ = ["AgilentAdapter", "parse_agilent_method"]


@register_vendor_adapter
class AgilentAdapter(VendorAdapter):
    """Reads Agilent ChemStation / MassHunter data folders."""

    name = "AgilentAdapter"
    vendor = "agilent"
    extensions = [".d", ".yep", ".ses"]
    formats = ["Agilent YEP"]
    description = "Agilent ChemStation/MassHunter .d folder: method + AcqData metadata"
    directory_markers = ["data.bin", "msd.bin", "acqdata"]
    sidecar_files = ["samplename", "sample.info"]

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
        note = Text(
            name=f"Agilent acquisition {target.name}",
            text=_describe(target, metadata),
            metadata=metadata,
        )
        return [self.envelope(note, path=target, format_name="Agilent .d")]

    def _read_folder(self, target: Path) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {"source_format": "Agilent .d folder"}
        methods = sorted(target.glob("*.M")) + sorted(target.glob("*.m"))
        if methods:
            metadata["method"] = parse_agilent_method(methods[0])
        ms_tables = sorted(target.glob("AcqData/MSTable")) + sorted(
            target.glob("**/MSTable")
        )
        if ms_tables:
            metadata["ms_table"] = _parse_inf(ms_tables[0])
        for marker in ("data.bin", "MSD.bin", "MSD.bin.bin"):
            if (target / marker).exists():
                metadata.setdefault("payload", marker)
        return metadata

    def _read_file(self, target: Path) -> Dict[str, Any]:
        suffix = target.suffix.lower()
        if suffix == ".yep":
            return {
                "source_format": "Agilent YEP (single injection)",
                "fallback": "YEP is a proprietary profile container",
            }
        return {}


def parse_agilent_method(path: str | Path) -> Dict[str, Any]:
    """Parse the flat ``key = value`` pairs of an Agilent ``.M`` method file."""
    found: Dict[str, Any] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        found.setdefault(key.strip(), value.strip())
    return found


def _parse_inf(path: Path) -> Dict[str, Any]:
    found: Dict[str, Any] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        found.setdefault(key.strip(), value.strip())
    return found


def _describe(target: Path, metadata: Dict[str, Any]) -> str:
    lines = [
        f"{target} is an Agilent ChemStation/MassHunter data folder.",
        f"Method nodes : {len(metadata.get('method', {}) or {})}",
        f"Payload      : {metadata.get('payload', 'not found')}",
    ]
    if metadata.get("fallback"):
        lines.append(f"Fallback     : {metadata['fallback']}")
    lines.append("Export with ProteoWizard or MassHunter to mzML to load spectra.")
    return "\n".join(lines)
