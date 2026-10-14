"""X-ray diffraction: powder XRD and single crystal structure solution."""

from __future__ import annotations

import itertools
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from models.materials import simulate_xrd
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Material, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.processing import find_peaks
from workflow_engine.registry import register_node

from nodes._helpers import build_material, ensure_peaks, peaks_to_table
from nodes.instruments._base import InstrumentNode, find_spectrum, sample_items, resolve_material

__all__ = ["XRDNode", "SingleCrystalXRDNode"]

_ANODES = {"Cu Kα": 1.5406, "Mo Kα": 0.7107, "Co Kα": 1.7903, "Cr Kα": 2.2910}


def _formula_of(material) -> str:
    """Rebuild a Hill formula from a material's composition components."""
    parts: List[str] = []
    for component in getattr(material, "composition", []) or []:
        count = float(component.fraction)
        parts.append(
            f"{component.formula}{int(count) if float(count).is_integer() else count:g}"
        )
    return "".join(parts)


def _default_sites(formula: str) -> List[Dict[str, Any]]:
    """Spread the elements of ``formula`` on plausible fractional positions."""
    from workflow_engine.processing import parse_formula

    counts = parse_formula(formula)
    anchors = [
        [0.0, 0.0, 0.0],
        [0.5, 0.5, 0.5],
        [0.5, 0.0, 0.0],
        [0.0, 0.5, 0.0],
        [0.0, 0.0, 0.5],
        [0.25, 0.25, 0.25],
        [0.75, 0.75, 0.75],
    ]
    sites: List[Dict[str, Any]] = []
    for index, (element, count) in enumerate(sorted(counts.items())):
        position = anchors[index % len(anchors)]
        sites.append({"element": element, "frac": position})
    return sites


@register_node
class XRDNode(InstrumentNode):
    """Powder X-ray diffractometer."""

    name = "XRD"
    category = "Instruments/Diffraction"
    description = "粉末 X 射线衍射仪：由晶胞与原子占位计算衍射峰位与强度（含 Scherrer 展宽）。"
    version = "0.7.1"
    tags = ["instrument", "xrd", "diffraction", "crystal"]
    aliases = ["XRD", "PXRD"]
    icon = "XR"

    technique = "XRD"
    instrument = "virtual powder diffractometer"

    parameters = [
        ParameterSpec("formula", "string", "LiFePO4", "化学式"),
        ParameterSpec("a", "number", 10.33, "晶胞参数 a", unit="Å", min=0.5),
        ParameterSpec("b", "number", 6.01, "晶胞参数 b", unit="Å", min=0.5),
        ParameterSpec("c", "number", 4.69, "晶胞参数 c", unit="Å", min=0.5),
        ParameterSpec("alpha", "number", 90.0, "晶胞角 α", unit="°"),
        ParameterSpec("beta", "number", 90.0, "晶胞角 β", unit="°"),
        ParameterSpec("gamma", "number", 90.0, "晶胞角 γ", unit="°"),
        ParameterSpec("spacegroup", "string", "Pnma", "空间群"),
        ParameterSpec("anode", "enum", "Cu Kα", "靶材", options=list(_ANODES)),
        ParameterSpec("two_theta_max", "number", 90.0, "最大 2θ", unit="°", min=5.0, max=160.0),
        ParameterSpec("crystallite_size_nm", "number", 40.0, "晶粒尺寸", unit="nm", min=1.0, max=1000.0),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="XRD")
        if existing is not None:
            return existing

        material = resolve_material(self, inputs)
        # The crystal *formula* is what the diffraction sites are built from;
        # ``material.name`` is a free-form label ("LFP", "LiFePO4 (LFP)") and is
        # only used for reporting.
        formula = _formula_of(material) or str(self.get_param("formula", "") or "")
        lattice = {
            "a": float(self.get_param("a", 10.33) or 10.33),
            "b": float(self.get_param("b", 6.01) or 6.01),
            "c": float(self.get_param("c", 4.69) or 4.69),
            "alpha": float(self.get_param("alpha", 90.0) or 90.0),
            "beta": float(self.get_param("beta", 90.0) or 90.0),
            "gamma": float(self.get_param("gamma", 90.0) or 90.0),
        }
        spectrum = simulate_xrd(
            lattice=lattice,
            sites=_default_sites(formula),
            wavelength=float(_ANODES.get(str(self.get_param("anode", "Cu Kα")), 1.5406)),
            two_theta_max=float(self.get_param("two_theta_max", 90.0)),
            points=1800,
            crystallite_size_nm=float(self.get_param("crystallite_size_nm", 40.0)),
        )
        spectrum.metadata["formula"] = formula
        spectrum.metadata["sample"] = material.name
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        table = peaks_to_table(spectrum, limit=30, name="XRD reflections")
        rows = table.rows
        lines = [f"XRD: {len(rows)} reflections up to {float(self.get_param('two_theta_max', 90.0)):.0f}° 2θ"]
        for row in rows[:8]:
            lines.append(f"  2θ = {float(row[0]):6.2f}°  I = {float(row[1]):6.2f}")
        return {"table": table, "text": Text(name="XRD", text="\n".join(lines))}


@register_node
class SingleCrystalXRDNode(InstrumentNode):
    """Single crystal X-ray diffraction: indexing, cell refinement, structure."""

    name = "Single Crystal XRD"
    category = "Instruments/Diffraction"
    description = "单晶 X 射线衍射：衍射峰指标化、晶胞参数精修并输出晶体结构对象。"
    version = "0.7.1"
    tags = ["instrument", "xrd", "single crystal", "indexing"]
    aliases = ["SCXRD"]
    icon = "SC"

    technique = "SC-XRD"
    instrument = "virtual single crystal diffractometer"

    output_ports = [
        Port("material", "Material", "解析得到的晶体结构"),
        Port("table", "Table", "指标化结果"),
        Port("text", "Text", "精修报告"),
    ]

    parameters = [
        ParameterSpec("formula", "string", "LiFePO4", "化学式"),
        ParameterSpec("wavelength", "number", 0.7107, "X 射线波长", unit="Å", min=0.3, max=3.0),
        ParameterSpec("max_hkl", "integer", 6, "指标化时最大 hkl 指数", min=1, max=10, advanced=True),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="XRD")
        if existing is not None:
            return existing
        material = resolve_material(self, inputs)
        spectrum = simulate_xrd(
            lattice={
                "a": float(self.get_param("a", 10.33) or 10.33),
                "b": float(self.get_param("b", 6.01) or 6.01),
                "c": float(self.get_param("c", 4.69) or 4.69),
                "alpha": float(self.get_param("alpha", 90.0) or 90.0),
                "beta": float(self.get_param("beta", 90.0) or 90.0),
                "gamma": float(self.get_param("gamma", 90.0) or 90.0),
            },
            sites=_default_sites(material.name),
            wavelength=float(self.get_param("wavelength", 0.7107)),
            two_theta_max=60.0,
            points=1200,
            crystallite_size_nm=100.0,
        )
        spectrum.technique = "single crystal XRD"
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        two_theta = [float(peak.x) for peak in spectrum.peaks]
        wavelength = float(self.get_param("wavelength", 0.7107))
        max_hkl = int(self.get_param("max_hkl", 6))
        refined = index_cubic(two_theta, wavelength, max_hkl=max_hkl)

        rows: List[List[Any]] = []
        for observed, reflection in zip(two_theta, refined["assignments"]):
            h, k, l = reflection["hkl"]
            rows.append(
                [
                    round(observed, 3),
                    f"{h}{k}{l}",
                    int(reflection["n"]),
                    round(float(reflection["d_calculated"]), 4),
                    round(float(reflection["d_observed"]), 4),
                    round(float(reflection["error"]), 5),
                ]
            )
        table = Table(
            name="indexing",
            columns=["2θ obs", "hkl", "h²+k²+l²", "d calc (Å)", "d obs (Å)", "Δd (Å)"],
            rows=rows,
        )

        material = build_material(
            str(self.get_param("formula", "LiFePO4")),
            name=str(self.get_param("formula", "LiFePO4")),
            lattice={
                "a": refined["a"],
                "b": refined["a"],
                "c": refined["a"],
                "alpha": 90.0,
                "beta": 90.0,
                "gamma": 90.0,
            },
            spacegroup="Pnma",
            crystal_system="cubic",
            properties={"refined_a_angstrom": refined["a"], "reflections": len(rows)},
            phase="single crystal",
        )

        lines = [
            "Single crystal XRD refinement",
            f"  Reflections used : {len(rows)}",
            f"  Refined a        : {refined['a']:.4f} Å (cubic approximation)",
            f"  Mean |Δd|        : {refined['mean_error']:.5f} Å",
            f"  Wavelength       : {wavelength:.4f} Å",
        ]
        return {"material": material, "table": table, "text": Text(name="SC-XRD", text="\n".join(lines))}


# --------------------------------------------------------------------------- #
# indexing helpers
# --------------------------------------------------------------------------- #
def _hkl_for(n: int) -> Tuple[int, int, int]:
    """Return a representative ``(h, k, l)`` triple for ``n = h²+k²+l²``."""
    limit = int(math.isqrt(n)) + 1
    for h, k, l in itertools.product(range(limit + 1), repeat=3):
        if h * h + k * k + l * l == n:
            return (h, k, l)
    return (0, 0, 1)


def index_cubic(
    two_theta: Sequence[float], wavelength: float = 0.7107, max_hkl: int = 6
) -> Dict[str, Any]:
    """Index a powder pattern with a cubic lattice.

    Every observed reflection is converted to a d-spacing through Bragg's law
    and the cubic cell parameter ``a`` is scanned over the integer sums
    ``N = h² + k² + l²``.  The ``a`` minimising the mean ``|Δd|`` is kept.
    """
    if not two_theta:
        return {"a": 0.0, "assignments": [], "mean_error": 0.0}

    max_n = 3 * int(max_hkl) ** 2
    observed = [
        wavelength / (2.0 * math.sin(math.radians(max(1e-3, value) / 2.0)))
        for value in two_theta
    ]
    best: Optional[Dict[str, Any]] = None
    for first_n in range(1, max_n + 1):
        a = observed[0] * math.sqrt(first_n)
        if a <= 0:
            continue
        assignments: List[Dict[str, Any]] = []
        errors: List[float] = []
        for d_observed in observed:
            n_float = (a / d_observed) ** 2 if d_observed > 0 else 0.0
            n = max(1, int(round(n_float)))
            if n > max_n:
                continue
            d_calculated = a / math.sqrt(n)
            error = abs(d_calculated - d_observed)
            errors.append(error)
            h, k, l = _hkl_for(n)
            assignments.append(
                {
                    "hkl": (h, k, l),
                    "n": n,
                    "d_calculated": d_calculated,
                    "d_observed": d_observed,
                    "error": error,
                }
            )
        if not errors:
            continue
        mean_error = sum(errors) / len(errors)
        if best is None or mean_error < best["mean_error"]:
            best = {"a": a, "assignments": assignments, "mean_error": mean_error}

    if best is None:
        return {"a": 0.0, "assignments": [], "mean_error": 0.0}
    return best
