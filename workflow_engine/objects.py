"""Scientific Object protocol.

Every piece of data travelling between two nodes is wrapped into a
:class:`ScientificObject`.  Nodes never exchange raw files: they exchange
self-describing objects that can be serialised to JSON and shipped to the
frontend, stored in a database or embedded into a report.

The five first class citizens described by the specification are implemented
here:

==============  ============================================================
Object          Content
==============  ============================================================
``Spectrum``    1-D/2-D spectral data (MS, NMR, IR, Raman, UV-Vis, XRD, ...)
``Molecule``    Molecular structure (SMILES) + embedding + properties
``Material``    Composition + crystal structure + properties
``Table``       Generic tabular data (reaction data, descriptor tables, ...)
``Report``      Structured scientific report
==============  ============================================================
"""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from .errors import ObjectParseError
from .utils import json_safe, new_id, to_array

__all__ = [
    "ScientificObject",
    "Peak",
    "Spectrum",
    "Atom",
    "Bond",
    "Molecule",
    "Component",
    "CrystalStructure",
    "Material",
    "Table",
    "Image",
    "SpectralMatch",
    "Reaction",
    "Text",
    "ScientificReport",
    "OBJECT_TYPES",
    "register_object",
    "deserialize_object",
    "serialize_object",
]

# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #


class ScientificObject(BaseModel):
    """Base class of every object exchanged on the workflow graph."""

    model_config = ConfigDict(extra="allow", protected_namespaces=())

    type: str = Field(default="ScientificObject", description="Discriminator")
    id: str = Field(default_factory=lambda: new_id("o_"))
    name: str = Field(default="", description="Human readable label")
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # -- serialisation ----------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dictionary representation."""
        return json_safe(self.model_dump())

    def to_json(self, **kwargs: Any) -> str:
        import json

        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScientificObject":
        payload = dict(data or {})
        payload.pop("type", None)
        return cls(**payload)

    # -- presentation ------------------------------------------------------ #
    def summary(self) -> str:
        """One line description used by logs / tooltips."""
        return f"{self.type}: {self.name or self.id}"

    def preview(self) -> Dict[str, Any]:
        """Payload consumed by the React Flow inspector to render a preview."""
        return {"kind": "text", "text": self.summary()}


# --------------------------------------------------------------------------- #
# Spectrum
# --------------------------------------------------------------------------- #


class Peak(BaseModel):
    """A single, (optionally) assigned spectral feature."""

    model_config = ConfigDict(protected_namespaces=())

    x: float
    y: float = 0.0
    intensity: float = 0.0
    width: float = 0.0
    area: float = 0.0
    label: str = ""
    assignment: str = ""

    def text(self) -> str:
        return self.assignment or self.label or ""


def _first_item(values: Any) -> Any:
    """First element of ``values``, or ``None`` when it is empty or scalar.

    Used to tell a 2-D trace matrix from a flat one without consuming an
    iterator that the caller still needs.
    """
    if values is None:
        return None
    if isinstance(values, np.ndarray):
        return values.reshape(-1)[0] if values.size else None
    if isinstance(values, (list, tuple)):
        return values[0] if values else None
    return None


class Spectrum(ScientificObject):
    """Generic 1-D spectrum (and simple 2-D spectra via ``z``).

    A band structure is not a 1-D spectrum: it is ``n_bands`` traces that all
    share one x axis (the k path).  Feeding the 2-D ``[k][band]`` matrix to
    :meth:`from_arrays` used to end in :func:`to_array`, which ``ravel()``s
    everything into a single flat run of ``n_k * n_bands`` numbers.  The object
    then carried 71 x values against 284 y values, and every consumer
    downstream made a locally reasonable decision about that mismatch:

      * the frontend truncated to ``min(len(x), len(y))`` -- so a 4-band
        structure drew as 71 points of a 284-value run, i.e. band 1 followed by
        the first 55 values of band 2, with nothing joining them;
      * matplotlib raised on the length mismatch and the ``except`` returned
        ``None``, so the export quietly wrote a placeholder ``.txt`` instead of
        a PNG.

    Neither complained.  ``curves`` holds the per-band traces properly, and
    :meth:`is_multicurve` lets a renderer ask for them instead of guessing.
    """

    type: str = "Spectrum"
    mode: str = Field(default="Generic", description="MS / NMR / IR / Raman / ...")
    technique: str = ""
    x: List[float] = Field(default_factory=list)
    y: List[float] = Field(default_factory=list)
    z: List[List[float]] = Field(default_factory=list, description="Optional 2-D data")
    #: One entry per trace, each the same length as ``x``.  Used by band
    #: structures; empty for an ordinary single-trace spectrum.
    curves: List[List[float]] = Field(default_factory=list)
    #: Optional legend entries matching ``curves``.
    curve_labels: List[str] = Field(default_factory=list)
    x_unit: str = ""
    y_unit: str = ""
    peaks: List[Peak] = Field(default_factory=list)
    precursor_mz: Optional[float] = None
    ms_level: int = 1
    polarity: str = "positive"
    collision_energy: Optional[float] = None

    # -- constructors ------------------------------------------------------ #
    @classmethod
    def from_arrays(
        cls,
        x: Any,
        y: Any,
        mode: str = "Generic",
        x_unit: str = "",
        y_unit: str = "",
        **kwargs: Any,
    ) -> "Spectrum":
        """Build a spectrum from ``x`` and ``y``.

        ``y`` may be a 1-D sequence, or a sequence of equal-length sequences
        when several traces share one x axis (a band structure).  The 2-D form
        lands in :attr:`curves`; it is **not** flattened into :attr:`y`, because
        a flat run of ``n_k * n_bands`` values paired against ``n_k`` x values
        is not a spectrum and every reader of it would invent its own way to
        cope.
        """
        rows = cls._as_trace_rows(y)
        if len(rows) > 1 or (rows and isinstance(_first_item(y), (list, tuple, np.ndarray))):
            labels = list(kwargs.pop("curve_labels", []) or [])
            # ``y`` stays empty on purpose: with ``curves`` populated, a
            # consumer that reads only ``y`` would otherwise plot one of the
            # bands as if it were the whole spectrum.
            return cls(
                mode=mode,
                x=[float(v) for v in to_array(x)],
                y=[],
                curves=[[float(v) for v in row] for row in rows],
                curve_labels=[str(item) for item in labels][: len(rows)],
                x_unit=x_unit,
                y_unit=y_unit,
                **kwargs,
            )
        xs = to_array(x)
        ys = to_array(y)
        return cls(
            mode=mode,
            x=[float(v) for v in xs],
            y=[float(v) for v in ys],
            x_unit=x_unit,
            y_unit=y_unit,
            **kwargs,
        )

    @staticmethod
    def _as_trace_rows(y: Any) -> List[List[float]]:
        """Normalise ``y`` into a list of equal-length 1-D traces."""
        if y is None:
            return []
        if isinstance(y, np.ndarray):
            if y.ndim == 2:
                return [[float(v) for v in row] for row in y]
            if y.ndim == 1:
                return [[float(v) for v in y]]
            return []
        if isinstance(y, (list, tuple)):
            if not y:
                return []
            if all(isinstance(item, (list, tuple, np.ndarray)) for item in y):
                return [[float(v) for v in row] for row in y]
            return [[float(v) for v in y]]
        return [float(y)]

    def is_multicurve(self) -> bool:
        """True when the spectrum carries per-band traces in :attr:`curves`."""
        return len(self.curves) > 1

    def traces(self) -> List[List[float]]:
        """The traces to plot: :attr:`curves` when present, else ``[y]``."""
        if self.curves:
            return [list(row) for row in self.curves]
        return [list(self.y)] if self.y else []

    # -- numeric helpers --------------------------------------------------- #
    def x_array(self) -> np.ndarray:
        return to_array(self.x)

    def y_array(self) -> np.ndarray:
        return to_array(self.y)

    def curves_array(self) -> np.ndarray:
        """The per-trace values as an ``(n_traces, n_x)`` array."""
        rows = self.traces()
        if not rows:
            return np.zeros((0, 0), dtype=float)
        width = min(len(row) for row in rows)
        return np.asarray([row[:width] for row in rows], dtype=float)

    @property
    def size(self) -> int:
        return len(self.x)

    def tic(self) -> float:
        # A band structure has no total ion current: summing its energies would
        # report a meaningless number rather than a wrong-looking right one.
        if self.curves:
            return 0.0
        return float(np.sum(self.y_array())) if self.y else 0.0

    def max_peak(self) -> Optional[Peak]:
        if not self.peaks:
            return None
        return max(self.peaks, key=lambda p: p.intensity or p.y)

    def clip(self, x_min: float, x_max: float) -> "Spectrum":
        xs = self.x_array()
        mask = (xs >= x_min) & (xs <= x_max)
        if self.curves:
            clipped = [
                [float(v) for v, keep in zip(row, mask.tolist()) if keep]
                for row in self.curves
            ]
            return Spectrum(
                mode=self.mode,
                x=[float(v) for v, keep in zip(self.x, mask.tolist()) if keep],
                curves=clipped,
                curve_labels=list(self.curve_labels),
                x_unit=self.x_unit,
                y_unit=self.y_unit,
                technique=self.technique,
                name=self.name,
            )
        ys = self.y_array()
        return Spectrum.from_arrays(
            xs[mask],
            ys[mask],
            mode=self.mode,
            x_unit=self.x_unit,
            y_unit=self.y_unit,
            technique=self.technique,
            name=self.name,
        )

    # -- presentation ------------------------------------------------------ #
    def summary(self) -> str:
        if self.is_multicurve():
            base = (
                f"{self.mode} spectrum ({self.size} points, "
                f"{len(self.curves)} traces, {len(self.peaks)} peaks)"
            )
        else:
            base = f"{self.mode} spectrum ({self.size} points, {len(self.peaks)} peaks)"
        if self.precursor_mz:
            base += f", precursor m/z {self.precursor_mz:.4f}"
        return base

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "spectrum",
            "mode": self.mode,
            "title": self.name or self.technique or self.mode,
            "x_unit": self.x_unit,
            "y_unit": self.y_unit,
            "x": list(self.x),
            "y": list(self.y),
            "curves": [list(row) for row in self.curves],
            "curve_labels": list(self.curve_labels),
            "peaks": [
                {
                    "x": p.x,
                    "y": p.y,
                    "label": p.assignment or p.label,
                }
                for p in self.peaks[:40]
            ],
        }


# --------------------------------------------------------------------------- #
# Molecule
# --------------------------------------------------------------------------- #


class Atom(BaseModel):
    """Atom of a molecular graph."""

    model_config = ConfigDict(protected_namespaces=())

    index: int
    element: str
    aromatic: bool = False
    charge: int = 0
    hydrogens: int = 0
    coords: List[float] = Field(default_factory=list)


class Bond(BaseModel):
    """Bond of a molecular graph."""

    model_config = ConfigDict(protected_namespaces=())

    a: int
    b: int
    order: float = 1.0
    aromatic: bool = False


class Molecule(ScientificObject):
    """Molecular structure with optional learned embedding."""

    type: str = "Molecule"
    smiles: str = ""
    inchi: str = ""
    formula: str = ""
    exact_mass: Optional[float] = None
    average_mass: Optional[float] = None
    embedding: List[float] = Field(default_factory=list)
    properties: Dict[str, float] = Field(default_factory=dict)
    atoms: List[Atom] = Field(default_factory=list)
    bonds: List[Bond] = Field(default_factory=list)
    confidence: float = 0.0
    source: str = ""

    def graph(self) -> Dict[str, Any]:
        """Molecular graph as plain dictionaries (used by the GNN encoder)."""
        return {
            "atoms": [a.model_dump() for a in self.atoms],
            "bonds": [b.model_dump() for b in self.bonds],
        }

    def summary(self) -> str:
        parts = [self.name or self.smiles or "unknown molecule"]
        if self.formula:
            parts.append(self.formula)
        if self.exact_mass is not None:
            parts.append(f"exact mass {self.exact_mass:.4f}")
        return " | ".join(parts)

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "molecule",
            "smiles": self.smiles,
            "formula": self.formula,
            "exact_mass": self.exact_mass,
            "properties": self.properties,
            "confidence": self.confidence,
            "atom_count": len(self.atoms),
            "bond_count": len(self.bonds),
            "embedding_dim": len(self.embedding),
        }


# --------------------------------------------------------------------------- #
# Material
# --------------------------------------------------------------------------- #


class Component(BaseModel):
    """A component of a material with its molar / mass fraction."""

    model_config = ConfigDict(protected_namespaces=())

    formula: str
    fraction: float = 1.0
    role: str = ""


class CrystalStructure(BaseModel):
    """Crystallographic description (reduced but physically meaningful)."""

    model_config = ConfigDict(protected_namespaces=())

    a: float = 0.0
    b: float = 0.0
    c: float = 0.0
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    spacegroup: str = "P1"
    crystal_system: str = ""
    sites: List[Dict[str, Any]] = Field(default_factory=list)


class Material(ScientificObject):
    """Composition + structure + measured / predicted properties."""

    type: str = "Material"
    composition: List[Component] = Field(default_factory=list)
    structure: CrystalStructure = Field(default_factory=CrystalStructure)
    properties: Dict[str, float] = Field(default_factory=dict)
    phase: str = ""
    synthesis: str = ""

    def summary(self) -> str:
        formula = " ".join(f"{c.formula}" for c in self.composition) or "unknown"
        # ``properties`` is annotated ``Dict[str, float]`` but is not enforced at
        # runtime, and a summary must never be the thing that raises: this runs
        # inside report building, where a formatting failure surfaces as a failed
        # workflow with no clue which node produced the bad value.  Formatting a
        # non-float as-is is the honest fallback -- it shows the value instead of
        # hiding it, and it cannot crash.
        parts: List[str] = []
        for key, value in list(self.properties.items())[:3]:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                parts.append(f"{key}={value}")
            else:
                try:
                    parts.append(f"{key}={value:.3g}")
                except (TypeError, ValueError):
                    parts.append(f"{key}={value!r}")
        extra = ", ".join(parts)
        return f"{self.name or formula} [{formula}]" + (f" ({extra})" if extra else "")

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "material",
            "name": self.name,
            "composition": [c.model_dump() for c in self.composition],
            "structure": self.structure.model_dump(),
            "properties": self.properties,
            "phase": self.phase,
        }


# --------------------------------------------------------------------------- #
# Table / Image / Match / Reaction / Text / Report
# --------------------------------------------------------------------------- #


class Table(ScientificObject):
    """Tabular data (reaction screening results, descriptor tables, ...)."""

    type: str = "Table"
    columns: List[str] = Field(default_factory=list)
    rows: List[List[Any]] = Field(default_factory=list)

    @classmethod
    def from_records(cls, records: List[Dict[str, Any]], **kwargs: Any) -> "Table":
        columns: List[str] = []
        for record in records:
            for key in record:
                if key not in columns:
                    columns.append(key)
        rows = [[record.get(c) for c in columns] for record in records]
        return cls(columns=columns, rows=rows, **kwargs)

    def records(self) -> List[Dict[str, Any]]:
        return [dict(zip(self.columns, row)) for row in self.rows]

    def column(self, name: str) -> List[Any]:
        if name not in self.columns:
            raise KeyError(f"Column {name!r} not in table {self.columns}")
        idx = self.columns.index(name)
        return [row[idx] for row in self.rows]

    def to_csv(self, path: str | None = None) -> str:
        import csv
        import io

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(self.columns)
        writer.writerows(self.rows)
        text = buffer.getvalue()
        if path:
            Path(path).write_text(text, encoding="utf-8")
        return text

    def summary(self) -> str:
        return f"Table {self.name}: {len(self.rows)} rows x {len(self.columns)} cols"

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "table",
            "columns": self.columns,
            "rows": self.rows[:200],
            "total_rows": len(self.rows),
        }


class Image(ScientificObject):
    """2-D grayscale image with a physical pixel size (microscopy, maps)."""

    type: str = "Image"
    width: int = 0
    height: int = 0
    pixel_size: float = 1.0
    pixel_unit: str = "nm"
    data: List[List[float]] = Field(default_factory=list)
    cmap: str = "gray"

    @classmethod
    def from_array(
        cls,
        array: Any,
        pixel_size: float = 1.0,
        pixel_unit: str = "nm",
        **kwargs: Any,
    ) -> "Image":
        arr = np.asarray(array, dtype=float)
        if arr.ndim != 2:
            raise ValueError("Image.from_array expects a 2-D array")
        return cls(
            width=int(arr.shape[1]),
            height=int(arr.shape[0]),
            pixel_size=float(pixel_size),
            pixel_unit=pixel_unit,
            data=[[float(v) for v in row] for row in arr],
            **kwargs,
        )

    def array(self) -> np.ndarray:
        if not self.data:
            return np.zeros((0, 0), dtype=float)
        return np.asarray(self.data, dtype=float)

    def to_png_bytes(self) -> bytes:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig = plt.figure(frameon=False)
        ax = fig.add_axes([0, 0, 1, 1])
        ax.set_axis_off()
        ax.imshow(self.array(), cmap=self.cmap, aspect="equal")
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=110)
        plt.close(fig)
        return buffer.getvalue()

    def summary(self) -> str:
        return (
            f"Image {self.name or self.id}: {self.width}x{self.height} px, "
            f"{self.pixel_size:g} {self.pixel_unit}/px"
        )

    def preview(self) -> Dict[str, Any]:
        png = b""
        if self.data:
            try:
                png = self.to_png_bytes()
            except Exception:  # pragma: no cover - matplotlib optional at runtime
                png = b""
        return {
            "kind": "image",
            "width": self.width,
            "height": self.height,
            "pixel_size": self.pixel_size,
            "pixel_unit": self.pixel_unit,
            "png": base64.b64encode(png).decode("ascii"),
        }


class SpectralMatch(ScientificObject):
    """Result of a spectral library search."""

    type: str = "SpectralMatch"
    query: str = ""
    library: str = ""
    matches: List[Dict[str, Any]] = Field(default_factory=list)

    def best(self) -> Optional[Dict[str, Any]]:
        if not self.matches:
            return None
        return max(self.matches, key=lambda m: float(m.get("score", 0.0)))

    def summary(self) -> str:
        best = self.best()
        if not best:
            return f"{self.library} search: no match"
        return (
            f"{self.library} search: {best.get('name', '?')} "
            f"(score {float(best.get('score', 0.0)):.3f})"
        )

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "matches",
            "library": self.library,
            "query": self.query,
            "matches": self.matches[:25],
        }


class Reaction(ScientificObject):
    """A chemical reaction with conditions and outcome."""

    type: str = "Reaction"
    reactants: List[str] = Field(default_factory=list)
    products: List[str] = Field(default_factory=list)
    catalysts: List[str] = Field(default_factory=list)
    conditions: Dict[str, Any] = Field(default_factory=dict)
    yield_percent: Optional[float] = None
    selectivity: Optional[float] = None

    def summary(self) -> str:
        left = " + ".join(self.reactants)
        right = " + ".join(self.products)
        text = f"{left} -> {right}" if right else left
        if self.yield_percent is not None:
            text += f" (yield {self.yield_percent:.1f}%)"
        return text

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "reaction",
            "reactants": self.reactants,
            "products": self.products,
            "catalysts": self.catalysts,
            "conditions": self.conditions,
            "yield_percent": self.yield_percent,
            "selectivity": self.selectivity,
        }


class Text(ScientificObject):
    """Free text or JSON payload (LLM output, notes, logs)."""

    type: str = "Text"
    text: str = ""
    language: str = "en"
    data: Dict[str, Any] = Field(default_factory=dict)

    def summary(self) -> str:
        snippet = self.text.strip().splitlines()[0] if self.text.strip() else ""
        return snippet[:120] if snippet else f"Text {self.id}"

    def preview(self) -> Dict[str, Any]:
        return {"kind": "text", "text": self.text, "data": self.data}


class ScientificReport(ScientificObject):
    """Structured, renderable scientific report."""

    type: str = "ScientificReport"
    report_id: str = Field(default_factory=lambda: new_id("rpt_"))
    title: str = "Scientific Report"
    abstract: str = ""
    sections: List[Dict[str, Any]] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    provenance: Dict[str, Any] = Field(default_factory=dict)
    markdown_path: str = ""
    html_path: str = ""
    figures: List[str] = Field(default_factory=list)

    def add_section(
        self,
        heading: str,
        text: str = "",
        figures: List[str] | None = None,
        tables: List[Dict[str, Any]] | None = None,
    ) -> None:
        self.sections.append(
            {
                "heading": heading,
                "text": text,
                "figures": list(figures or []),
                "tables": list(tables or []),
            }
        )

    def summary(self) -> str:
        return f"Report {self.title!r} with {len(self.sections)} sections"

    def preview(self) -> Dict[str, Any]:
        return {
            "kind": "report",
            "title": self.title,
            "abstract": self.abstract,
            "sections": self.sections,
            "references": self.references,
            "limitations": self.limitations,
            "provenance": self.provenance,
            "markdown_path": self.markdown_path,
            "html_path": self.html_path,
        }


# --------------------------------------------------------------------------- #
# Registry / (de)serialisation
# --------------------------------------------------------------------------- #

OBJECT_TYPES: Dict[str, type] = {
    "ScientificObject": ScientificObject,
    "Spectrum": Spectrum,
    "Molecule": Molecule,
    "Material": Material,
    "Table": Table,
    "Image": Image,
    "SpectralMatch": SpectralMatch,
    "Reaction": Reaction,
    "Text": Text,
    "ScientificReport": ScientificReport,
}


def register_object(type_name: str, cls: type) -> None:
    """Register a new scientific object type (used by plugins)."""
    if not issubclass(cls, ScientificObject):
        raise TypeError("Scientific objects must inherit from ScientificObject")
    OBJECT_TYPES[type_name] = cls


def deserialize_object(data: Any) -> Any:
    """Rebuild a :class:`ScientificObject` from its dictionary payload."""
    if isinstance(data, ScientificObject):
        return data
    if isinstance(data, dict) and data.get("type") in OBJECT_TYPES:
        cls = OBJECT_TYPES[data["type"]]
        payload = {k: v for k, v in data.items() if k != "type"}
        try:
            return cls(**payload)
        except Exception as exc:  # pragma: no cover - defensive
            raise ObjectParseError(f"Cannot rebuild {data['type']}: {exc}") from exc
    return data


def serialize_object(obj: Any) -> Any:
    """Convert an object (or nested structure) to JSON-safe data."""
    if isinstance(obj, ScientificObject):
        return obj.to_dict()
    if isinstance(obj, dict):
        return {k: serialize_object(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize_object(v) for v in obj]
    return json_safe(obj)
