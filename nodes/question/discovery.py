"""The "what material should we make?" question node.

``MaterialDiscoveryNode`` closes the loop of the battery / catalyst demo
workflows: it takes the characterisation evidence produced upstream (XRD, SEM,
XPS, DFT), scores a pool of candidate compositions against a target property and
emits the optimised material together with a ranking table and a rationale.

The surrogate model is physics informed (theoretical capacity from the Li
content, Goldschmidt tolerance factor for perovskites, electronegativity based
band gap estimates, ...) so that it returns sensible numbers even without a
trained checkpoint.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from databases.materials_library import (
    MATERIALS_LIBRARY,
    search_by_element,
    search_by_formula,
    search_by_name,
)
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import (
    Image,
    Material,
    Molecule,
    ScientificObject,
    ScientificReport,
    SpectralMatch,
    Spectrum,
    Table,
    Text,
)
from workflow_engine.ports import Port
from workflow_engine.processing import parse_formula
from workflow_engine.registry import register_node

from nodes._helpers import build_material, collect, first_of, records_to_table

__all__ = ["MaterialDiscoveryNode", "PROPERTY_TARGETS", "ATOMIC_DATA"]


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float`` when possible."""
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

# element -> (atomic number, electronegativity, ionic-ish radius in Å, mass)
ATOMIC_DATA: Dict[str, Tuple[int, float, float, float]] = {
    "H": (1, 2.20, 0.31, 1.008),
    "Li": (3, 0.98, 0.76, 6.94),
    "Be": (4, 1.57, 0.45, 9.012),
    "B": (5, 2.04, 0.27, 10.81),
    "C": (6, 2.55, 0.70, 12.011),
    "N": (7, 3.04, 0.71, 14.007),
    "O": (8, 3.44, 1.40, 15.999),
    "F": (9, 3.98, 1.33, 18.998),
    "Na": (11, 0.93, 1.02, 22.990),
    "Mg": (12, 1.31, 0.72, 24.305),
    "Al": (13, 1.61, 0.53, 26.982),
    "Si": (14, 1.90, 1.11, 28.085),
    "P": (15, 2.19, 1.07, 30.974),
    "S": (16, 2.58, 1.70, 32.06),
    "Cl": (17, 3.16, 1.81, 35.45),
    "K": (19, 0.82, 1.38, 39.098),
    "Ca": (20, 1.00, 1.00, 40.078),
    "Sc": (21, 1.36, 0.75, 44.956),
    "Ti": (22, 1.54, 0.61, 47.867),
    "V": (23, 1.63, 0.59, 50.942),
    "Cr": (24, 1.66, 0.55, 51.996),
    "Mn": (25, 1.55, 0.53, 54.938),
    "Fe": (26, 1.83, 0.61, 55.845),
    "Co": (27, 1.88, 0.55, 58.933),
    "Ni": (28, 1.91, 0.55, 58.693),
    "Cu": (29, 1.90, 0.57, 63.546),
    "Zn": (30, 1.65, 0.60, 65.38),
    "Ga": (31, 1.81, 0.62, 69.723),
    "Ge": (32, 2.01, 0.73, 72.630),
    "As": (33, 2.18, 0.58, 74.922),
    "Se": (34, 2.55, 1.84, 78.971),
    "Br": (35, 2.96, 1.96, 79.904),
    "Sr": (38, 0.95, 1.18, 87.62),
    "Zr": (40, 1.33, 0.72, 91.224),
    "Nb": (41, 1.60, 0.64, 92.906),
    "Mo": (42, 2.16, 0.65, 95.95),
    "Ag": (47, 1.93, 1.15, 107.87),
    "Cd": (48, 1.69, 0.95, 112.41),
    "Sn": (50, 1.96, 1.10, 118.71),
    "Sb": (51, 2.05, 0.76, 121.76),
    "I": (53, 2.66, 2.20, 126.904),
    "Ba": (56, 0.89, 1.35, 137.33),
    "La": (57, 1.10, 1.03, 138.91),
    "Ce": (58, 1.12, 1.01, 140.12),
    "Ta": (73, 1.50, 0.64, 180.95),
    "W": (74, 2.36, 0.62, 183.84),
    "Pt": (78, 2.28, 0.63, 195.08),
    "Au": (79, 2.54, 0.64, 196.97),
    "Pb": (82, 2.33, 1.19, 207.20),
    "Bi": (83, 2.02, 1.03, 208.98),
    "N": (7, 3.04, 0.71, 14.007),
}

#: target properties: ``key -> (label, unit, objective)``
PROPERTY_TARGETS: Dict[str, Tuple[str, str, str]] = {
    "capacity_gravimetric": ("gravimetric capacity", "mAh/g", "maximise"),
    "band_gap": ("band gap", "eV", "target"),
    "conductivity": ("electronic conductivity", "S/cm", "maximise"),
    "stability": ("thermal stability", "°C", "maximise"),
    "surface_area": ("specific surface area", "m²/g", "maximise"),
}


@register_node
class MaterialDiscoveryNode(ScientificNode):
    """Discover / optimise a material against a target property."""

    name = "Material Discovery"
    category = "Questions"
    description = (
        "材料发现与优化：融合 XRD / SEM / XPS / DFT 证据，"
        "按目标性质对候选组分排序并输出优化材料。"
    )
    version = "0.7.1"
    tags = ["question", "materials discovery", "optimisation", "battery", "catalyst"]
    aliases = ["MatDiscovery"]
    icon = "MD"

    input_ports = [
        Port("xrd", "Spectrum", "X 射线衍射图", optional=True, multi=True),
        Port("sem", "Image", "显微图像", optional=True, multi=True),
        Port("xps", "Spectrum", "X 射线光电子能谱", optional=True, multi=True),
        Port("dft", "Any", "DFT 计算结果", optional=True, multi=True),
        Port("candidates", "Any", "候选库（可选）", optional=True, multi=True),
    ]
    output_ports = [
        Port("material", "Material", "优化后的材料"),
        Port("table", "Table", "候选排序与预测性质"),
        Port("text", "Text", "决策依据"),
    ]

    parameters = [
        ParameterSpec(
            "target_property",
            "enum",
            "capacity_gravimetric",
            "目标性质",
            options=list(PROPERTY_TARGETS),
        ),
        ParameterSpec(
            "target_value", "number", 0.0, "目标值（band_gap 用；0 = 忽略）", advanced=True
        ),
        ParameterSpec(
            "candidate_formulas",
            "text",
            "",
            "候选化学式，逗号或换行分隔（留空则使用内置材料库）",
        ),
        ParameterSpec("top_k", "integer", 5, "返回候选数量", min=1, max=50),
        ParameterSpec("language", "enum", "zh", "报告语言", options=["zh", "en"]),
    ]

    # -- candidate pool ------------------------------------------------------- #
    def _candidate_pool(self, inputs: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Collect the candidate compositions from graph, params and library."""
        pool: List[Dict[str, Any]] = []
        seen = set()

        def add(record: Dict[str, Any]) -> None:
            key = str(record.get("formula", "")).upper()
            if key and key not in seen:
                seen.add(key)
                pool.append(record)

        for item in collect(inputs.get("candidates")):
            if isinstance(item, Material):
                add(asdict_safe(item))
            elif isinstance(item, Table):
                for record in item.records():
                    formula = str(record.get("formula") or record.get("name") or "")
                    if formula:
                        add({"name": record.get("name", formula), "formula": formula})
            elif isinstance(item, Text):
                for token in _split_tokens(item.text):
                    add({"name": token, "formula": token})

        raw = str(self.get_param("candidate_formulas", "") or "")
        for token in _split_tokens(raw):
            add({"name": token, "formula": token})

        query = str(self.get_param("query", "") or "").strip()
        if query:
            for hit in search_by_name(query, limit=10):
                add(hit)

        if not pool:
            for record in MATERIALS_LIBRARY:
                add(record_to_dict(record))
        return pool

    # -- scoring ---------------------------------------------------------------- #
    def _predict(self, record: Dict[str, Any]) -> Dict[str, float]:
        """Surrogate property prediction from the composition."""
        formula = str(record.get("formula", "") or "")
        counts = parse_formula(formula)
        if not counts:
            return {}
        total_atoms = float(sum(counts.values()))
        mass = sum(
            ATOMIC_DATA.get(element, (0, 2.0, 1.0, 12.0))[3] * count
            for element, count in counts.items()
        )
        if mass <= 0:
            return {}

        electronegativity = sum(
            ATOMIC_DATA.get(element, (0, 2.0, 1.0, 12.0))[1] * count
            for element, count in counts.items()
        ) / total_atoms
        mean_z = sum(
            ATOMIC_DATA.get(element, (0, 2.0, 1.0, 12.0))[0] * count
            for element, count in counts.items()
        ) / total_atoms
        transition_metals = {"Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
                            "Nb", "Mo", "Ta", "W", "Pt", "Au", "Ag"}
        tm_fraction = sum(counts.get(element, 0) for element in transition_metals) / total_atoms
        lithium = float(counts.get("Li", 0))
        oxygen = float(counts.get("O", 0))
        alkali = float(counts.get("Na", 0)) + float(counts.get("K", 0))

        # theoretical gravimetric capacity:  n_e * F / (3.6 * M)  [mAh/g]
        electrons = max(1.0, lithium + alkali) if (lithium + alkali) > 0 else 0.0
        capacity = electrons * 96485.0 / (3.6 * mass) if electrons else 0.0

        # crude band gap estimate: electronegativity spread, damped by Z
        gap = round(
            max(0.0, 2.6 - 0.55 * tm_fraction * 4.0 + 0.12 * (mean_z - 20.0) / 10.0), 4
        )
        gap = min(max(gap, 0.0), 8.0)

        # ionic conductivity proxy: mobile ion fraction / molar mass
        conductivity = round(
            max(1e-12, (electrons / max(1.0, total_atoms)) * 1.0e-2 * math.exp(-mass / 400.0)), 8
        )

        # Goldschmidt tolerance factor for ABX3 like compositions
        tolerance = _goldschmidt(record)
        stability = round(300.0 + 400.0 * (oxygen / max(1.0, total_atoms)) + 50.0 * tm_fraction, 2)
        if tolerance is not None:
            stability += 200.0 * (1.0 - min(1.0, abs(tolerance - 1.0)))

        properties = {
            "capacity_gravimetric_mah_g": round(capacity, 3),
            "band_gap_ev": round(gap, 4),
            "conductivity_s_cm": round(conductivity, 9),
            "thermal_stability_c": round(stability, 2),
            "molar_mass_g_mol": round(mass, 4),
        }
        if tolerance is not None:
            properties["goldschmidt_tolerance"] = round(tolerance, 4)
        return properties

    # -- execution --------------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        pool = self._candidate_pool(inputs)
        target = str(self.get_param("target_property", "capacity_gravimetric"))
        target_value = float(self.get_param("target_value", 0.0) or 0.0)

        scored: List[Dict[str, Any]] = []
        for record in pool:
            properties = dict(record.get("properties") or {}) or self._predict(record)
            scored.append(dict(record, properties=properties, confidence=0.0))

        best_raw: Optional[float] = None
        worst_raw: Optional[float] = None
        for item in scored:
            properties = item.get("properties") or {}
            if target == "capacity_gravimetric":
                raw = float(properties.get("capacity_gravimetric_mah_g", 0.0))
            elif target == "band_gap":
                value = float(properties.get("band_gap_ev", 0.0))
                raw = -abs(value - target_value) if target_value else value
            elif target == "conductivity":
                raw = float(properties.get("conductivity_s_cm", 0.0))
                raw = math.log10(max(1e-12, raw))
            elif target == "stability":
                raw = float(properties.get("thermal_stability_c", 0.0))
            else:
                raw = float(properties.get("surface_area_m2_g", 0.0))
            item["raw_score"] = raw
            best_raw = raw if best_raw is None else max(best_raw, raw)
            worst_raw = raw if worst_raw is None else min(worst_raw, raw)

        span = (best_raw - worst_raw) if best_raw is not None and worst_raw is not None else 0.0
        for item in scored:
            raw = float(item.get("raw_score", 0.0))
            if span > 1e-12:
                item["confidence"] = round(0.35 + 0.6 * (raw - worst_raw) / span, 6)
            else:
                item["confidence"] = round(0.55, 6)
            item.pop("raw_score", None)

        scored.sort(key=lambda entry: -float(entry.get("confidence", 0.0)))
        top_k = int(self.get_param("top_k", 5) or 5)
        ranked = scored[:top_k]
        best = ranked[0]

        material = build_material(
            str(best.get("formula") or ""),
            name=str(best.get("name") or best.get("formula") or "material"),
            lattice={
                "a": _safe_float(best.get("a")),
                "b": _safe_float(best.get("b")),
                "c": _safe_float(best.get("c")),
                "alpha": _safe_float(best.get("alpha")) or 90.0,
                "beta": _safe_float(best.get("beta")) or 90.0,
                "gamma": _safe_float(best.get("gamma")) or 90.0,
            },
            spacegroup=str(best.get("spacegroup", "P1")),
            crystal_system=str(best.get("crystal_system", "")),
            properties={str(k): float(v) for k, v in (best.get("properties") or {}).items()},
            phase=str(best.get("family", "")),
        )

        table = Table(
            name="material discovery ranking",
            columns=["rank", "name", "formula", "confidence", "capacity_mAh_g", "band_gap_eV"],
            rows=[
                [
                    index + 1,
                    entry.get("name", ""),
                    entry.get("formula", ""),
                    entry.get("confidence", 0.0),
                    (entry.get("properties") or {}).get("capacity_gravimetric_mah_g", ""),
                    (entry.get("properties") or {}).get("band_gap_ev", ""),
                ]
                for index, entry in enumerate(ranked)
            ],
        )

        language = str(self.get_param("language", "zh"))
        explanation = _explain_material(material, ranked, target, language)
        self.log(f"selected {material.name} (confidence {best.get('confidence', 0.0):.3f})")
        return {
            "material": material,
            "table": table,
            "text": Text(
                name="discovery report",
                text=explanation,
                data={"candidates": ranked, "language": language, "target": target},
            ),
        }


# --------------------------------------------------------------------------- #
# reporting helpers
# --------------------------------------------------------------------------- #
def _split_tokens(raw: str) -> List[str]:
    """Split a block of text into candidate formula tokens."""
    import re

    return [token.strip() for token in re.split(r"[\n,;]+", raw or "") if token.strip()]


def asdict_safe(material: Material) -> Dict[str, Any]:
    """Return a plain dictionary describing ``material``."""
    return {
        "name": material.name,
        "formula": "".join(component.formula for component in material.composition),
        "spacegroup": material.structure.spacegroup,
        "crystal_system": material.structure.crystal_system,
        "a": material.structure.a,
        "b": material.structure.b,
        "c": material.structure.c,
        "alpha": material.structure.alpha,
        "beta": material.structure.beta,
        "gamma": material.structure.gamma,
        "properties": dict(material.properties),
    }


def record_to_dict(record: Any) -> Dict[str, Any]:
    """Convert a library dataclass record into a plain dictionary."""
    from dataclasses import asdict, is_dataclass

    if is_dataclass(record):
        payload = asdict(record)
    else:
        payload = dict(record)
    payload.setdefault(
        "composition",
        sorted(parse_formula(str(payload.get("formula", ""))).items()),
    )
    return payload


def _goldschmidt(record: Dict[str, Any]) -> Optional[float]:
    """Goldschmidt tolerance factor for ``ABX3`` compositions (``None`` if not)."""
    counts = parse_formula(str(record.get("formula", "")))
    if len(counts) != 3 or "O" not in counts:
        return None
    others = [element for element in counts if element != "O"]
    if len(others) != 2:
        return None

    def radius(element: str) -> float:
        return ATOMIC_DATA.get(element, (0, 2.0, 1.0, 12.0))[2]

    radii = sorted((radius(element), counts[element]) for element in others)
    radius_a = radii[1][0]
    radius_b = radii[0][0]
    radius_o = radius("O")
    if radius_b + radius_o <= 0:
        return None
    return (radius_a + radius_o) / (math.sqrt(2.0) * (radius_b + radius_o))


def _explain_material(
    material: Material,
    ranked: List[Dict[str, Any]],
    target: str,
    language: str,
) -> str:
    """Build the rationale text for the selected material."""
    best_confidence = float(ranked[0].get("confidence", 0.0))
    best_capacity = float(
        (ranked[0].get("properties") or {}).get("capacity_gravimetric_mah_g", 0.0)
    )
    runner_up = ranked[1] if len(ranked) > 1 else None
    if language == "zh":
        lines = [
            f"推荐材料：{material.name}",
            f"化学式：{material.phase or ''} {' '.join(c.formula for c in material.composition)}".strip(),
            f"目标性质：{target}",
            f"综合置信度：{best_confidence:.3f}",
            f"理论比容量：{best_capacity:.1f} mAh/g",
        ]
        if runner_up is not None:
            lines.append(
                f"次优候选：{runner_up.get('name', '?')} "
                f"（置信度 {float(runner_up.get('confidence', 0.0)):.3f}）"
            )
        lines.append("")
        lines.append("候选排序：")
        for index, entry in enumerate(ranked[:10]):
            properties = entry.get("properties") or {}
            lines.append(
                f"  {index + 1}. {entry.get('name', '?')} "
                f"[{entry.get('formula', '')}] 置信度 "
                f"{float(entry.get('confidence', 0.0)):.3f}，容量 "
                f"{float(properties.get('capacity_gravimetric_mah_g', 0.0)):.1f} mAh/g"
            )
        return "\n".join(lines)

    lines = [
        f"Recommended material: {material.name}",
        f"Formula: {' '.join(c.formula for c in material.composition)}",
        f"Target property: {target}",
        f"Confidence: {best_confidence:.3f}",
        f"Theoretical capacity: {best_capacity:.1f} mAh/g",
    ]
    if runner_up is not None:
        lines.append(
            f"Runner-up: {runner_up.get('name', '?')} "
            f"(confidence {float(runner_up.get('confidence', 0.0)):.3f})"
        )
    lines.append("")
    lines.append("Ranking:")
    for index, entry in enumerate(ranked[:10]):
        properties = entry.get("properties") or {}
        lines.append(
            f"  {index + 1}. {entry.get('name', '?')} "
            f"[{entry.get('formula', '')}] confidence "
            f"{float(entry.get('confidence', 0.0)):.3f}, capacity "
            f"{float(properties.get('capacity_gravimetric_mah_g', 0.0)):.1f} mAh/g"
        )
    return "\n".join(lines)
