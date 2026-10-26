"""Waters vendor adapter (MassLynx ``.raw`` folders, ``.arw`` injections).

MassLynx stores an acquisition as a directory: ``_HEADER.TXT``,
``_INLET.INF``, ``_FUNC001.DAT`` (profile data) and the ``.raw`` index.  The
header and ``.INF`` files are plain text and are parsed for real; the profile
payload stays in the proprietary container and is left to ``msconvert``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from data_layer.objects import ScientificDataObject
from workflow_engine.objects import Text

from custom_nodes._shared.vendor_adapters.base import (
    VendorAdapter,
    register_vendor_adapter,
)

__all__ = ["WatersAdapter", "parse_waters_header"]


@register_vendor_adapter
class WatersAdapter(VendorAdapter):
    """Reads Waters MassLynx acquisition folders."""

    name = "WatersAdapter"
    vendor = "waters"
    extensions = [".raw", ".arw", ".mwd"]
    formats = ["Waters ARW"]
    description = "Waters MassLynx .raw folder: header/INF metadata + function list"
    directory_markers = ["_header.txt", "_inlet.inf", ".raw"]
    sidecar_files = ["_header.txt", "_inlet.inf", "sample.info"]

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
            name=f"Waters acquisition {target.name}",
            text=_describe(target, metadata),
            metadata=metadata,
        )
        return [self.envelope(note, path=target, format_name="Waters RAW")]

    def _read_folder(self, target: Path) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {"source_format": "Waters MassLynx folder"}
        header = target / "_HEADER.TXT"
        if header.exists():
            metadata["header"] = parse_waters_header(header)
        functions = sorted(target.glob("_FUNC*.DAT"))
        if functions:
            metadata["functions"] = [path.stem for path in functions]
        inlet = target / "_INLET.INF"
        if inlet.exists():
            metadata["inlet"] = _parse_inf(inlet)
        metadata["acquired_at"] = _timestamp_of(target)
        return metadata

    def _read_file(self, target: Path) -> Dict[str, Any]:
        suffix = target.suffix.lower()
        if suffix == ".arw":
            return {
                "source_format": "Waters ARW (single injection)",
                "fallback": "ARW is a proprietary profile container",
            }
        return {}


def parse_waters_header(path: str | Path) -> Dict[str, Any]:
    """Parse the ``key: value`` pairs of a MassLynx ``_HEADER.TXT``."""
    found: Dict[str, Any] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return found
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key:
            found.setdefault(key, value)
    return found


def _parse_inf(path: Path) -> Dict[str, Any]:
    """Parse the ``key = value`` pairs of a MassLynx ``.INF`` file."""
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


def _timestamp_of(target: Path) -> str:
    from workflow_engine.utils import now_iso

    try:
        return now_iso(target.stat().st_mtime)
    except OSError:
        return ""


def _describe(target: Path, metadata: Dict[str, Any]) -> str:
    header = metadata.get("header", {}) or {}
    lines = [
        f"{target} is a Waters MassLynx acquisition container.",
        f"Sample       : {header.get('Sample Description', header.get('Sample', 'unknown'))}",
        f"Functions    : {', '.join(metadata.get('functions', []) or []) or 'none'}",
    ]
    if metadata.get("fallback"):
        lines.append(f"Fallback     : {metadata['fallback']}")
    lines.append("Export with msconvert (ProteoWizard) to mzML to load spectra.")
    return "\n".join(lines)
