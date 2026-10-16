"""Input/output ports and type compatibility rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

# Canonical data types carried by the ports.  ``Any`` acts as a wildcard.
DATA_TYPES = (
    "Any",
    "Spectrum",
    "Molecule",
    "Material",
    "Table",
    "Image",
    "SpectralMatch",
    "Reaction",
    "Text",
    "ScientificReport",
    # Opaque acquisition bundles: arrays of traces and geometry that the
    # inspector cannot render.  They travel through the graph unchanged and the
    # nodes publish human-readable views of them on ordinary ports.
    "Survey",
)

# Compatibility matrix.  A key maps the *source* type to the set of accepted
# target types.  Anything not listed falls back to the identity rule.
_IMPLICIT_CASTS: Dict[str, tuple] = {
    "ScientificReport": ("Text",),
    "Molecule": ("Text",),
    "Material": ("Text",),
}


@dataclass(frozen=True)
class Port:
    """A named connection point of a node."""

    name: str
    data_type: str = "Any"
    description: str = ""
    optional: bool = False
    multi: bool = field(
        default=False,
        metadata={"doc": "Accept several incoming connections", },
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "data_type": self.data_type,
            "description": self.description,
            "optional": self.optional,
            "multi": self.multi,
        }

    def __str__(self) -> str:  # pragma: no cover - debug helper
        return f"{self.name}:{self.data_type}"


def types_compatible(source: Optional[str], target: Optional[str]) -> bool:
    """Return ``True`` when a ``source`` output may feed a ``target`` input."""
    src = source or "Any"
    dst = target or "Any"
    if src == "Any" or dst == "Any":
        return True
    if src == dst:
        return True
    return dst in _IMPLICIT_CASTS.get(src, ())


def port_by_name(ports: Iterable[Port], name: Optional[str]) -> Optional[Port]:
    """Look up a port by name (case-insensitive, ``None`` -> first port)."""
    ports = list(ports)
    if not ports:
        return None
    if name is None:
        return ports[0]
    lowered = str(name).lower()
    for port in ports:
        if port.name.lower() == lowered:
            return port
    return None
