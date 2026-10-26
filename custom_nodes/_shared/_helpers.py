"""Small helpers shared by every node implementation.

The helpers keep the node bodies short and guarantee that all nodes behave the
same way when they receive a single object, a merged list of objects, or a
serialised dictionary coming from the REST API.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Type

import numpy as np

from models.descriptors import compute_descriptors, descriptor_vector, molecular_weight
from models.geometry import guess_coordinates
from models.smiles import MolecularGraph, parse_smiles
from models.substructure import detect_functional_groups
from workflow_engine.errors import NodeInputError
from workflow_engine.objects import (
    Atom,
    Bond,
    Image,
    Material,
    Molecule,
    ScientificObject,
    ScientificReport,
    Spectrum,
    Table,
    Text,
    deserialize_object,
)
from workflow_engine.processing import find_peaks

#: Repository root -- used when a node is executed outside of a workflow run
#: (``ctx is None``) and artefacts still have to be written somewhere.
#:
#: This used to be ``Path(__file__).resolve().parents[1]`` back when the
#: helpers lived in ``nodes/_helpers.py`` -- one level below the root.  The
#: migration into ``custom_nodes/_shared/`` added a level, and the naive
#: ``parents[1]`` silently started pointing at ``custom_nodes/`` instead.
#: The visible symptom was runtime artefacts landing in
#: ``custom_nodes/output/artifacts/`` rather than ``output/artifacts/``:
#: the write still succeeded, the file was still produced, and the only
#: symptom was that the publisher's leak scanner refused the archive.
#:
#: Deriving the root from the package (``custom_nodes``) rather than from
#: the depth of this file means the next relocation cannot break it the
#: same way.
from custom_nodes import ROOT

__all__ = [
    "ROOT",
    "materialise",
    "collect",
    "first_of",
    "to_spectrum",
    "to_molecule",
    "to_material",
    "to_table",
    "to_text",
    "build_molecule",
    "default_embedding",
    "peaks_to_table",
    "records_to_table",
    "write_artifact",
]

_MODEL_CACHE: Dict[str, Any] = {}


def _seed_vector(text: str, dimension: int, seed: int) -> np.ndarray:
    """Deterministic pseudo random projection of ``text`` into ``dimension``."""
    digest = hashlib.sha1(f"{seed}:{text}".encode("utf-8")).digest()
    values = np.frombuffer(digest * (dimension // 20 + 1), dtype=np.uint8)[:dimension]
    return (values.astype(float) / 127.5) - 1.0


def _unit(vector: np.ndarray) -> np.ndarray:
    """Return ``vector`` scaled to unit length (zero vector stays zero)."""
    norm = float(np.linalg.norm(vector))
    return vector / norm if norm > 0 else vector


# --------------------------------------------------------------------------- #
# Port value normalisation
# --------------------------------------------------------------------------- #
def materialise(value: Any) -> Any:
    """Return ``value`` as a live :class:`ScientificObject` when possible."""
    if isinstance(value, ScientificObject):
        return value
    if isinstance(value, dict):
        return deserialize_object(value)
    if isinstance(value, (list, tuple)):
        return [materialise(item) for item in value]
    return value


def collect(value: Any) -> List[Any]:
    """Normalise a port value into a list of materialised objects."""
    if value is None:
        return []
    items = list(value) if isinstance(value, (list, tuple)) else [value]
    return [materialise(item) for item in items if item is not None]


def first_of(
    value: Any,
    cls: Type[ScientificObject],
    what: str = "value",
    required: bool = True,
    default: Any = None,
) -> Any:
    """Return the first item of ``value`` that is an instance of ``cls``.

    ``required=False`` makes the lookup tolerant: missing (or wrongly typed)
    data simply yields ``default`` instead of raising.
    """
    items = collect(value)
    for item in items:
        if isinstance(item, cls):
            return item
    if not items:
        if required:
            raise NodeInputError(f"{what}: no input provided")
        return default
    if required:
        raise NodeInputError(
            f"{what}: expected {cls.__name__}, received {type(items[0]).__name__}"
        )
    return default


def to_spectrum(value: Any, what: str = "spectrum") -> Spectrum:
    return first_of(value, Spectrum, what)


def to_table(value: Any, what: str = "table") -> Table:
    return first_of(value, Table, what)


def to_text(value: Any, default: str = "") -> str:
    """Render any incoming object as human readable text."""
    items = collect(value)
    for item in items:
        if isinstance(item, Text):
            return item.text
        if isinstance(item, ScientificReport):
            return render_report_markdown(item)
        if isinstance(item, Molecule):
            return item.smiles or item.name
        if isinstance(item, Material):
            text = " ".join(component.formula for component in item.composition)
            return text or item.name
        if isinstance(item, Table):
            return item.to_csv()
        if isinstance(item, Spectrum):
            return item.summary()
        if isinstance(item, str):
            return item
    return default


def to_molecule(value: Any, default_smiles: str = "", what: str = "molecule") -> Molecule:
    """Coerce an incoming value into a :class:`Molecule`.

    ``default_smiles`` is used when ``value`` carries no structure (a plain
    text node for instance) so that a node can always keep working.
    """
    items = collect(value)
    for item in items:
        if isinstance(item, Molecule) and item.smiles:
            return item
    smiles = default_smiles
    for item in items:
        if isinstance(item, Molecule):
            smiles = default_smiles or item.name
        elif isinstance(item, Text):
            candidate = default_smiles or item.text.strip().splitlines()[0].strip()
            smiles = candidate
        elif isinstance(item, str):
            smiles = default_smiles or item.strip()
        elif isinstance(item, Table):
            for column in item.columns:
                if column.lower() in {"smiles", "structure", "canonical_smiles"}:
                    column_values = [r for r in item.column(column) if r]
                    if column_values:
                        smiles = str(column_values[0])
                        break
        if smiles:
            break
    if not smiles:
        raise NodeInputError(f"{what}: no SMILES available")
    return build_molecule(smiles)


def to_material(value: Any, what: str = "material") -> Material:
    items = collect(value)
    for item in items:
        if isinstance(item, Material):
            return item
    for item in items:
        if isinstance(item, Molecule) and item.formula:
            return build_material(item.formula, name=item.name or item.formula)
        if isinstance(item, Text):
            text = item.text.strip().splitlines()[0].strip()
            if text:
                return build_material(text)
    raise NodeInputError(f"{what}: no material composition available")


# --------------------------------------------------------------------------- #
# Object construction
# --------------------------------------------------------------------------- #
def default_embedding(smiles: str, path: str = "") -> List[float]:
    """Return a numeric molecular embedding.

    A trained :class:`models.mpnn.RidgeMPNN` checkpoint is used when one is
    supplied through ``path`` or ``CHEMML_MODEL_PATH``.  Otherwise the
    deterministic descriptor vector is returned: it is a genuine molecular
    feature vector (physicochemical descriptors) so downstream nodes can
    consume it without any network access or trained weights.
    """
    from models.mpnn import RidgeMPNN

    resolved = path or os.environ.get("CHEMML_MODEL_PATH", "")
    if resolved and Path(resolved).exists():
        key = str(Path(resolved).resolve())
        if key not in _MODEL_CACHE:
            _MODEL_CACHE[key] = RidgeMPNN.load(key)
        return [float(value) for value in _MODEL_CACHE[key].encode(smiles)]
    return [float(value) for value in descriptor_vector(smiles)]


def build_molecule(
    smiles: str,
    name: str = "",
    confidence: float = 0.0,
    with_coords: bool = False,
    with_embedding: bool = True,
    properties: Optional[Dict[str, Any]] = None,
    embedding: Optional[Sequence[float]] = None,
    source: str = "",
) -> Molecule:
    """Parse ``smiles`` and return a fully populated :class:`Molecule`."""
    text = str(smiles or "").strip()
    if not text:
        raise NodeInputError("SMILES string is empty")
    graph: MolecularGraph = parse_smiles(text)
    counts = graph.formula()
    descriptors = compute_descriptors(text)

    atoms = [
        Atom(
            index=int(atom.get("index", position)),
            element=str(atom.get("element", "C")),
            aromatic=bool(atom.get("aromatic", False)),
            charge=int(atom.get("charge", 0) or 0),
            hydrogens=int(atom.get("hydrogens", 0) or 0),
        )
        for position, atom in enumerate(graph.atoms)
    ]
    bonds = [
        Bond(
            a=int(bond["a"]),
            b=int(bond["b"]),
            order=float(bond.get("order", 1.0)),
            aromatic=bool(bond.get("aromatic", False)),
        )
        for bond in graph.bonds
    ]

    if with_coords and graph.num_atoms:
        coordinates = guess_coordinates(text, iterations=80)
        for index, atom in enumerate(atoms):
            if index < len(coordinates):
                atom.coords = [float(value) for value in coordinates[index]]

    numeric = {
        str(key): float(value)
        for key, value in descriptors.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    for key, value in (properties or {}).items():
        try:
            numeric[str(key)] = float(value)
        except (TypeError, ValueError):
            continue

    if embedding is None:
        embedding = default_embedding(text) if with_embedding else []

    return Molecule(
        smiles=text,
        name=name or text,
        formula=graph.formula_string(),
        exact_mass=float(molecular_weight(counts, "monoisotopic")),
        average_mass=float(molecular_weight(counts, "average")),
        embedding=[float(value) for value in embedding],
        properties=numeric,
        atoms=atoms,
        bonds=bonds,
        confidence=float(confidence),
        source=source,
    )


def build_material(
    formula: str,
    name: str = "",
    lattice: Optional[Dict[str, float]] = None,
    spacegroup: str = "P1",
    crystal_system: str = "",
    properties: Optional[Dict[str, Any]] = None,
    phase: str = "",
    synthesis: str = "",
    source: str = "",
) -> Material:
    """Build a :class:`Material` from a formula and optional cell parameters.

    ``source`` is recorded in ``metadata["source"]`` so that downstream report
    nodes can cite where a candidate came from.
    """
    from workflow_engine.objects import Component, CrystalStructure
    from workflow_engine.processing import parse_formula

    text = str(formula or "").strip()
    if not text:
        raise NodeInputError("Material formula is empty")
    counts = parse_formula(text)
    components = [
        Component(formula=element, fraction=float(count))
        for element, count in sorted(counts.items())
    ]
    cell = dict(lattice or {})

    def _cell_value(key: str, fallback: float) -> float:
        """Read a lattice parameter, tolerating ``None`` and numeric strings."""
        raw = cell.get(key, fallback)
        if raw is None or raw == "":
            return float(fallback)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return float(fallback)

    structure = CrystalStructure(
        a=_cell_value("a", 0.0),
        b=_cell_value("b", 0.0),
        c=_cell_value("c", 0.0),
        alpha=_cell_value("alpha", 90.0),
        beta=_cell_value("beta", 90.0),
        gamma=_cell_value("gamma", 90.0),
        spacegroup=spacegroup,
        crystal_system=crystal_system,
    )
    numeric: Dict[str, float] = {}
    for key, value in (properties or {}).items():
        try:
            numeric[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return Material(
        name=name or text,
        composition=components,
        structure=structure,
        properties=numeric,
        phase=phase,
        synthesis=synthesis,
    )
    if source:
        material.metadata["source"] = source
    return material


# --------------------------------------------------------------------------- #
# Tables / artefacts
# --------------------------------------------------------------------------- #
def find_image(values: Any) -> Optional["Image"]:
    """Return the first :class:`Image` found in a port value."""
    for item in collect(values):
        if isinstance(item, Image):
            return item
    return None


def peaks_to_table(spectrum: Spectrum, limit: int = 200, name: str = "") -> Table:
    """Convert the peak list of ``spectrum`` into a :class:`Table`."""
    peaks = sorted(
        spectrum.peaks,
        key=lambda peak: float(peak.intensity or peak.y),
        reverse=True,
    )[:limit]
    highest = spectrum.max_peak()
    reference = float(highest.intensity or highest.y) if highest is not None else 0.0
    if reference <= 0:
        reference = 1.0
    return Table(
        name=name or f"{spectrum.mode} peaks",
        columns=["position", "intensity", "relative", "width", "area", "assignment"],
        rows=[
            [
                float(peak.x),
                float(peak.intensity or peak.y),
                round(float(peak.intensity or peak.y) / reference, 6),
                float(peak.width),
                float(peak.area),
                peak.assignment or peak.label,
            ]
            for peak in peaks
        ],
    )


def records_to_table(records: Sequence[Dict[str, Any]], name: str = "") -> Table:
    """Convert a list of flat dictionaries into a :class:`Table`."""
    columns: List[str] = []
    for record in records:
        for key in record:
            if key not in columns:
                columns.append(str(key))
    rows = [[record.get(column) for column in columns] for record in records]
    return Table(name=name, columns=columns, rows=rows)


def ensure_peaks(
    spectrum: Spectrum, prominence: float = 0.03, height: Optional[float] = None
) -> Spectrum:
    """Return ``spectrum`` with a populated peak list."""
    if spectrum.peaks or not spectrum.x or not spectrum.y:
        return spectrum
    peaks = find_peaks(
        spectrum.x, spectrum.y, height=height, prominence=prominence
    )
    spectrum.peaks = list(peaks)
    return spectrum


def render_report_markdown(report: ScientificReport) -> str:
    """Render a :class:`ScientificReport` as Markdown text."""
    lines: List[str] = [f"# {report.title}", ""]
    if report.abstract:
        lines += [report.abstract, ""]
    for section in report.sections:
        heading = str(section.get("heading", "Section"))
        lines.append(f"## {heading}")
        lines.append("")
        text = str(section.get("text", "")).strip()
        if text:
            lines += [text, ""]
        for figure in section.get("figures", []) or []:
            lines.append(f"![figure]({figure})")
            lines.append("")
        for table in section.get("tables", []) or []:
            columns = list(table.get("columns", []) or [])
            rows = list(table.get("rows", []) or [])
            if columns:
                lines.append("| " + " | ".join(str(c) for c in columns) + " |")
                lines.append("|" + "|".join(["---"] * len(columns)) + "|")
                for row in rows:
                    lines.append(
                        "| " + " | ".join("" if v is None else str(v) for v in row) + " |"
                    )
                lines.append("")
    if report.references:
        lines.append("## References")
        lines.append("")
        for reference in report.references:
            lines.append(f"- {reference}")
        lines.append("")
    # v0.7.1 (task J): a report must state its own limitations explicitly.
    limitations = list(getattr(report, "limitations", []) or [])
    if limitations:
        lines.append("## 结果局限 / Scientific limitations")
        lines.append("")
        for item in limitations:
            lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_artifact(
    ctx: Any,
    filename: str,
    content: str | bytes,
    subdir: str = "",
    encoding: str = "utf-8",
) -> str:
    """Write ``content`` into the run artefact folder and return its path."""
    if ctx is not None and hasattr(ctx, "artifact_path"):
        path = Path(ctx.artifact_path(filename, subdir=subdir))
    else:
        from workflow_engine.utils import ensure_dir

        directory = ensure_dir(ROOT / "output" / "artifacts")
        path = directory / filename
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding=encoding)
    return str(path)
