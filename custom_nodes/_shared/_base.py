"""Common machinery shared by the virtual instrument nodes.

A virtual instrument behaves like its physical counterpart: it accepts a
sample (a molecule, a material, or a spectrum produced by another instrument),
acquires a spectrum, and attaches an interpretation to it.  Concrete
instruments only implement :meth:`InstrumentNode.measure` and, when a richer
report is wanted, :meth:`InstrumentNode.summarize`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from workflow_engine.errors import NodeExecutionError, NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import (
    Image,
    Material,
    Molecule,
    ScientificReport,
    Spectrum,
    Table,
    Text,
)
from workflow_engine.ports import Port
from workflow_engine.processing import parse_formula

from custom_nodes._shared._helpers import (
    build_material,
    collect,
    ensure_peaks,
    peaks_to_table,
    records_to_table,
)

__all__ = [
    "InstrumentNode",
    "sample_items",
    "resolve_smiles",
    "resolve_material",
    "resolve_composition",
    "find_spectrum",
    "find_image",
]


def sample_items(inputs: Dict[str, Any], key: str = "sample") -> List[Any]:
    """Return every object connected to the ``sample`` input port."""
    return collect(inputs.get(key))


def find_spectrum(values: Sequence[Any], mode: str = "") -> Optional[Spectrum]:
    """Return the first spectrum of ``values``, optionally filtered by mode."""
    for item in collect(values):
        if isinstance(item, Spectrum):
            if mode and str(item.mode).upper() != mode.upper():
                continue
            return item
    return None


def find_image(values: Sequence[Any]) -> Optional[Image]:
    """Return the first image of ``values``."""
    for item in collect(values):
        if isinstance(item, Image):
            return item
    return None


def resolve_smiles(node: ScientificNode, inputs: Dict[str, Any]) -> str:
    """Prefer an upstream molecule, fall back on the ``smiles`` parameter."""
    for item in sample_items(inputs):
        if isinstance(item, Molecule) and item.smiles:
            return item.smiles
        if isinstance(item, ScientificReport):
            for section in item.sections:
                text = str(section.get("text", ""))
                if "SMILES" in text:
                    return _extract_smiles(text)
    text = str(node.get_param("smiles", "") or "").strip()
    return text


def _extract_smiles(text: str) -> str:
    """Pull the first token that looks like a SMILES from ``text``."""
    import re

    match = re.search(r"([A-Za-z0-9@+\-\[\]\(\)=#%/\\\.]{3,})", text)
    return match.group(1) if match else ""


def resolve_material(node: ScientificNode, inputs: Dict[str, Any]) -> Material:
    """Prefer an upstream material, fall back on the ``formula`` parameter."""
    for item in sample_items(inputs):
        if isinstance(item, Material):
            return item
    for item in sample_items(inputs):
        if isinstance(item, Molecule) and item.formula:
            return build_material(item.formula, name=item.name)
    formula = str(node.get_param("formula", "") or "").strip()
    if not formula:
        raise NodeInputError(f"{node.node_type()}: no material available")
    lattice = {
        "a": float(node.get_param("a", 0.0) or 0.0),
        "b": float(node.get_param("b", 0.0) or 0.0),
        "c": float(node.get_param("c", 0.0) or 0.0),
    }
    return build_material(formula, lattice=lattice)


def resolve_composition(
    node: ScientificNode, inputs: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Return ``[{"element": ..., "fraction": ...}]`` for surface techniques."""
    material = None
    for item in sample_items(inputs):
        if isinstance(item, Material):
            material = item
            break
    if material is not None:
        return [
            {"element": component.formula, "fraction": float(component.fraction)}
            for component in material.composition
        ]
    for item in sample_items(inputs):
        if isinstance(item, Molecule) and item.formula:
            counts = parse_formula(item.formula)
            return [
                {"element": element, "fraction": float(count)}
                for element, count in sorted(counts.items())
            ]
    raw = str(node.get_param("composition", "") or "").strip()
    if not raw:
        raise NodeInputError(f"{node.node_type()}: no composition available")
    entries: List[Dict[str, Any]] = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip()
        if not token:
            continue
        if ":" in token:
            element, fraction = token.split(":", 1)
        elif "=" in token:
            element, fraction = token.split("=", 1)
        else:
            element, fraction = token, "1"
        entries.append({"element": element.strip().capitalize(), "fraction": float(fraction) or 1.0})
    return entries


# --------------------------------------------------------------------------- #
# Base class
# --------------------------------------------------------------------------- #
class InstrumentNode(ScientificNode):
    """Base class of every virtual instrument."""

    category = "Instruments"
    technique: str = "Generic"
    instrument: str = "virtual instrument"

    input_ports = [
        Port("sample", "Any", "上游样品（分子 / 材料 / 谱图）", optional=True, multi=True)
    ]
    output_ports = [
        Port("spectrum", "Spectrum", "采集得到的谱图"),
        Port("table", "Table", "处理结果表"),
        Port("text", "Text", "仪器日志与结论"),
    ]

    # -- to be overridden ---------------------------------------------------- #
    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        """Acquire (or simulate) the raw spectrum."""
        raise NotImplementedError(
            f"{self.node_type()} must implement measure(inputs, ctx)"
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        """Turn the acquired spectrum into a table and a textual conclusion."""
        return {
            "table": peaks_to_table(spectrum),
            "text": Text(name=self.technique, text=spectrum.summary()),
        }

    # -- execution ----------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = self.measure(inputs, ctx)
        if spectrum is None:
            raise NodeExecutionError(
                self.node_id, self.node_type(), "instrument produced no spectrum"
            )
        if not spectrum.technique:
            spectrum.technique = self.technique
        spectrum.metadata.setdefault("instrument", self.instrument)
        spectrum.metadata.setdefault("acquired_at", _timestamp())
        self.log(f"{self.technique}: {spectrum.summary()}")

        declared = {port.name for port in self.output_ports}
        outputs: Dict[str, Any] = {}
        if "spectrum" in declared:
            outputs["spectrum"] = spectrum
        for key, value in self.summarize(spectrum).items():
            if key in declared:
                outputs[key] = value
        return outputs


def _timestamp() -> str:
    from workflow_engine.utils import now_iso

    return now_iso()
