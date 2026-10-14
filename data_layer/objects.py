"""Universal Scientific Data Layer -- the data envelope.

Every experimental datum that enters the platform is wrapped in a
:class:`ScientificDataObject`.  The envelope is deliberately small and stable::

    {
      "id":           "data_9f2c...",
      "type":         "MassSpectrum",
      "source":       "Thermo",
      "format":       "RAW",
      "metadata":     {...},
      "data_pointer": "datasets/mass_spectrometry/thermo_lcms/sample_01.raw"
    }

``payload`` (not serialised as JSON) holds the actual scientific object
(:class:`workflow_engine.objects.Spectrum`, ``Molecule``, ...), so downstream
nodes keep working with the typed objects they already know.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from data_layer.metadata import (
    DataProvenance,
    infer_data_type,
    new_data_id,
    normalise_metadata,
)
from workflow_engine.utils import json_safe

__all__ = ["ScientificDataObject", "wrap", "unwrap"]


def _posix(path: Any) -> str:
    """Normalise a path to forward slashes (portable ``data_pointer``)."""
    if not path:
        return ""
    return str(path).replace("\\", "/")


class ScientificDataObject(BaseModel):
    """Universal envelope for scientific data.

    Parameters
    ----------
    id:
        Stable identifier of the datum.
    type:
        Data-layer type, e.g. ``MassSpectrum`` / ``NMRSpectrum`` / ``Molecule``.
    source:
        Where the data came from: a vendor (``Thermo``), a database
        (``PubChem``) or ``synthetic`` for simulator output.
    format:
        Container / serialisation, e.g. ``mzML``, ``RAW``, ``JCAMP-DX``.
    metadata:
        Canonical + vendor specific metadata (see ``data_layer.metadata``).
    data_pointer:
        Path, URI or cache key locating the raw bytes.
    payload:
        The wrapped scientific object (not part of the JSON contract).
    provenance:
        How the object was produced -- the audit trail.
    """

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    id: str = Field(default_factory=new_data_id)
    type: str = Field(default="ScientificObject")
    source: str = Field(default="", description="vendor / database / synthetic")
    format: str = Field(default="", description="container or serialisation")
    metadata: Dict[str, Any] = Field(default_factory=dict)
    data_pointer: str = Field(default="", description="path, URI or cache key")
    payload: Any = Field(default=None, exclude=True)
    provenance: Any = Field(default=None, exclude=True)

    # -- construction ------------------------------------------------------- #
    @classmethod
    def wrap(
        cls,
        scientific_object: Any,
        *,
        source: str = "",
        format: str = "",
        data_pointer: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        provenance: Optional[DataProvenance] = None,
        type_name: str = "",
        data_id: str = "",
    ) -> "ScientificDataObject":
        """Wrap an existing scientific object into the universal envelope."""
        merged = normalise_metadata(metadata)
        payload_meta = getattr(scientific_object, "metadata", None)
        if isinstance(payload_meta, dict):
            for key, value in payload_meta.items():
                merged.setdefault(key, value)
        if not merged.get("sample"):
            merged["sample"] = str(getattr(scientific_object, "name", "") or "")
        if not merged.get("instrument") and provenance is not None:
            merged["instrument"] = provenance.instrument
        return cls(
            id=data_id or new_data_id(),
            type=type_name or infer_data_type(scientific_object),
            source=source,
            format=format,
            metadata=merged,
            data_pointer=_posix(data_pointer),
            payload=scientific_object,
            provenance=provenance or DataProvenance(),
        )

    # -- access ------------------------------------------------------------- #
    @property
    def data_type(self) -> str:
        """Alias of :attr:`type` used by some callers."""
        return self.type

    def to_scientific_object(self) -> Any:
        """Return the wrapped scientific object."""
        return self.payload

    def engine(self) -> str:
        """Engine that produced the payload (``''`` when unknown)."""
        if self.provenance is not None:
            return str(getattr(self.provenance, "engine", "") or "")
        return str(self.metadata.get("engine", "") or "")

    def summary(self) -> str:
        pointer = f" @ {self.data_pointer}" if self.data_pointer else ""
        engine = f" [{self.engine()}]" if self.engine() else ""
        return f"{self.type} from {self.source or 'unknown'}{engine}{pointer}"

    # -- serialisation ------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        """JSON contract of the envelope (``payload`` excluded)."""
        payload: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "source": self.source,
            "format": self.format,
            "metadata": json_safe(self.metadata),
            "data_pointer": self.data_pointer,
        }
        if self.provenance is not None:
            payload["provenance"] = self.provenance.to_dict()
        return payload

    def to_json(self, **kwargs: Any) -> str:
        import json

        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScientificDataObject":
        """Rebuild an envelope from its JSON contract (payload restored)."""
        payload = dict(data or {})
        provenance = payload.pop("provenance", None)
        return cls(
            id=str(payload.get("id") or new_data_id()),
            type=str(payload.get("type") or "ScientificObject"),
            source=str(payload.get("source", "") or ""),
            format=str(payload.get("format", "") or ""),
            metadata=normalise_metadata(payload.get("metadata")),
            data_pointer=str(payload.get("data_pointer", "") or ""),
            payload=payload.get("payload"),
            provenance=DataProvenance.from_dict(provenance),
        )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ScientificDataObject {self.summary()}>"


def wrap(scientific_object: Any, **kwargs: Any) -> ScientificDataObject:
    """Shorthand for :meth:`ScientificDataObject.wrap`."""
    return ScientificDataObject.wrap(scientific_object, **kwargs)


def unwrap(data_object: Any) -> Any:
    """Return the payload of ``data_object``, or the argument itself."""
    if isinstance(data_object, ScientificDataObject):
        return data_object.payload
    if isinstance(data_object, list):
        return [unwrap(item) for item in data_object]
    return data_object
