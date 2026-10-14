"""The "what is this compound?" question node.

``UnknownCompoundIdentificationNode`` is the entry point of the flagship demo
workflow.  It fuses the evidence produced by the instrument nodes:

1. the **precursor / neutral mass** from LC-MS or GC-MS,
2. the **fragment peaks** of the MS spectrum matched against library entries,
3. the **IR / Raman bands** matched against group frequencies,
4. the **NMR signals** compared with the shifts predicted for each candidate.

Each available piece of evidence produces an independent score; the scores are
merged with fixed weights and normalised, which yields a calibrated
``confidence`` in ``[0, 1]``.  The node therefore degrades gracefully: a
workflow that only carries an MS spectrum still returns a ranked list.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from databases.local_library import search_by_mass, search_by_name
from models.descriptors import QED, compute_descriptors, lipinski_violations
from models.spectra import predict_ir, predict_nmr, predict_raman, predict_uvvis
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
from workflow_engine.processing import (
    adduct_mz,
    find_peaks,
    formula_mass,
    mass_error,
    neutral_mass,
    parse_formula,
)
from workflow_engine.registry import register_node

from nodes._helpers import build_molecule, collect, ensure_peaks, first_of, records_to_table

__all__ = ["UnknownCompoundIdentificationNode", "CANDIDATE_WEIGHTS"]


#: relative weight of each evidence channel
CANDIDATE_WEIGHTS: Dict[str, float] = {
    "mass": 0.25,
    "ms": 0.30,
    "ir": 0.15,
    "nmr": 0.25,
    "uv": 0.05,
}


def _safe_float(value: Any) -> Optional[float]:
    """Convert ``value`` to ``float`` when possible."""
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


#: columns of an external candidate table that carry a list of spectral values
_LIST_COLUMNS = ("fragments", "ir_bands", "raman_bands", "uv_max")


def _numeric_list(value: Any) -> List[float]:
    """Parse a spectral list from a table cell.

    Accepts an already numeric sequence or a delimited string such as
    ``"138.066; 110.071, 83.06"``.  This lets a user-supplied reference library
    stored as CSV drive the mass / IR / Raman / UV evidence channels of the
    node, which is the documented purpose of the ``candidates`` input port.
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        items: Sequence[Any] = value
    elif isinstance(value, str):
        cleaned = value.strip().strip("[]")
        if not cleaned:
            return []
        items = re.split(r"[;,|\s]+", cleaned)
    else:
        items = [value]
    parsed: List[float] = []
    for item in items:
        number = _safe_float(str(item).strip())
        if number is not None:
            parsed.append(number)
    return parsed


def _has_peak(spectrum: Optional[Spectrum], target: float, tolerance: float) -> bool:
    """Return ``True`` when ``spectrum`` shows a peak near ``target``."""
    if spectrum is None:
        return False
    for peak in spectrum.peaks:
        if abs(float(peak.x) - float(target)) <= tolerance:
            return True
    return False


def _match_fraction(
    spectrum: Optional[Spectrum], references: Sequence[float], tolerance: float
) -> Optional[float]:
    """Fraction of ``references`` explained by ``spectrum`` (``None`` if absent)."""
    if spectrum is None or not references:
        return None
    ensure_peaks(spectrum, prominence=0.02)
    hits = sum(1 for value in references if _has_peak(spectrum, float(value), tolerance))
    return hits / float(len(references))


def _mass_score(observed: Optional[float], theoretical: Optional[float], tolerance_ppm: float) -> Optional[float]:
    """Exponential decay score for the mass agreement."""
    if observed is None or theoretical is None:
        return None
    error = abs(mass_error(float(observed), float(theoretical), unit="ppm"))
    return float(math.exp(-error / max(1e-6, tolerance_ppm)))


def _nmr_score(
    observed: Optional[Spectrum], candidate_smiles: str, tolerance_ppm: float = 0.25
) -> Optional[float]:
    """Compare observed 1H signals with the shifts predicted for a candidate."""
    if observed is None or not candidate_smiles:
        return None
    ensure_peaks(observed, prominence=0.02)
    observed_peaks = sorted((float(peak.x) for peak in observed.peaks), reverse=True)
    if not observed_peaks:
        return None
    try:
        predicted = predict_nmr(candidate_smiles, nucleus="1H", points=4096)
    except Exception:  # noqa: BLE001 - a candidate may simply not be parsable
        return None
    predicted_peaks = [float(peak.x) for peak in predicted.peaks]
    if not predicted_peaks:
        return None
    matched = 0
    for shift in predicted_peaks:
        if any(abs(shift - value) <= tolerance_ppm for value in observed_peaks):
            matched += 1
    covered = sum(
        1
        for value in observed_peaks
        if any(abs(value - shift) <= tolerance_ppm for shift in predicted_peaks)
    )
    union = float(len(predicted_peaks) + len(observed_peaks)) or 1.0
    return float((matched + covered) / union)


@register_node
class UnknownCompoundIdentificationNode(ScientificNode):
    """Identify an unknown compound from MS / NMR / IR / Raman / UV-Vis evidence."""

    name = "Unknown Compound Identification"
    category = "Questions"
    description = (
        "未知物结构鉴定：融合质谱分子离子与碎片、核磁化学位移、红外拉曼谱带，"
        "输出候选结构、置信度与解释。"
    )
    version = "0.7.1"
    tags = ["question", "identification", "structure elucidation", "fusion"]
    aliases = ["UnknownID", "CompoundID"]
    icon = "ID"

    # -- v0.7.2 task P0-05 / P0-06: execution provenance ----------------- #
    # Deterministic internal computation over a curated local library.  The
    # *retrieval pipeline* has a known-answer benchmark (task I); the node is
    # therefore ``executable`` -- NOT ``verified``, because no real instrument
    # data has been validated yet (see docs/V07_2_REAL_DATA_VALIDATION_PLAN.md).
    capability_status = "executable"
    execution_mode = "internal_approximation"
    required_dependencies = []
    input_constraints = (
        "至少需要一路证据（MS / NMR / IR / Raman / UV-Vis）或一个外部候选库；"
        "质谱通道要求候选条目提供碎片 m/z，仅给 SMILES 的候选库无法参与 MS 打分。"
        "单通道配置下置信度只在通道内归一化，不具备跨候选概率意义。"
    )
    validation_evidence = [
        "docs/V07_1_BENCHMARK.md",
        "scripts/benchmark_lcms.py",
        "tests/test_v07_1_benchmark.py",
    ]
    limitations = [
        "基准基于平台正向模型生成的合成数据，验证的是检索/排序流水线，不构成真实仪器数据的准确率声明。",
        "跨来源参考库（经验碎片）下 24 例中 2 例 Top-1 失败（nicotine、histidine）。",
        "单通道置信度不可解读为概率。",
    ]
    reproducibility_level = "deterministic"

    input_ports = [
        Port("ms", "Spectrum", "质谱（LC-MS / GC-MS / MALDI）", optional=True, multi=True),
        Port("nmr", "Spectrum", "核磁共振谱", optional=True, multi=True),
        Port("ir", "Spectrum", "红外光谱", optional=True, multi=True),
        Port("raman", "Spectrum", "拉曼光谱", optional=True, multi=True),
        Port("uvvis", "Spectrum", "紫外可见光谱", optional=True, multi=True),
        Port("candidates", "Any", "外部候选库（可选）", optional=True, multi=True),
    ]
    output_ports = [
        Port("molecule", "Molecule", "最佳候选结构"),
        Port("table", "Table", "排序后的候选与置信度"),
        Port("text", "Text", "证据解释"),
    ]

    parameters = [
        ParameterSpec("query", "string", "", "已知名称 / 分子式（可选，用于直接检索）"),
        ParameterSpec("adduct", "enum", "[M+H]+", "加合离子", options=[
            "[M]+", "[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+", "[M-H]-", "[M+Cl]-",
        ]),
        ParameterSpec(
            "mass_tolerance_ppm", "number", 10.0, "质量容差", unit="ppm", min=0.01, max=1000.0
        ),
        ParameterSpec("top_k", "integer", 5, "候选数量", min=1, max=50),
        ParameterSpec("use_ai", "boolean", True, "生成 AI 解释文本"),
        ParameterSpec("language", "enum", "zh", "报告语言", options=["zh", "en"]),
    ]

    # -- evidence extraction -------------------------------------------------- #
    def _neutral_mass(self, inputs: Dict[str, Any]) -> Optional[float]:
        """Estimate the neutral monoisotopic mass from the connected evidence."""
        adduct = str(self.get_param("adduct", "[M+H]+"))
        spectrum = first_of(inputs.get("ms"), Spectrum, required=False)
        if spectrum is not None and spectrum.precursor_mz:
            return float(neutral_mass(float(spectrum.precursor_mz), adduct))

        molecule = first_of(inputs.get("candidates"), Molecule, required=False)
        if molecule is not None and molecule.exact_mass is not None:
            return float(molecule.exact_mass)

        raw = str(self.get_param("query", "") or "").strip()
        try:
            return float(raw)
        except ValueError:
            pass
        hits = search_by_name(raw, limit=1) if raw else []
        if hits:
            return _safe_float(hits[0].get("mass"))
        return None

    def _candidate_pool(self, inputs: Dict[str, Any], mass: Optional[float]) -> List[Dict[str, Any]]:
        """Collect candidate structures from the graph, the parameters and the library."""
        pool: List[Dict[str, Any]] = []
        by_smiles: Dict[str, Dict[str, Any]] = {}

        def add(record: Dict[str, Any]) -> None:
            smiles = str(record.get("smiles", "") or "")
            if not smiles:
                return
            existing = by_smiles.get(smiles)
            if existing is None:
                by_smiles[smiles] = record
                pool.append(record)
                return
            # enrich an existing candidate with any evidence it is still missing
            for key, value in record.items():
                if not existing.get(key):
                    existing[key] = value

        for item in collect(inputs.get("candidates")):
            if isinstance(item, Molecule):
                add({"name": item.name or item.smiles, "smiles": item.smiles,
                     "formula": item.formula, "mass": item.exact_mass, "source": "graph"})
            elif isinstance(item, SpectralMatch):
                add({"name": item.name or item.smiles, "smiles": item.smiles,
                     "formula": item.formula, "mass": item.exact_mass, "source": "graph"})
            elif isinstance(item, Table):
                for record in item.records():
                    smiles = str(record.get("smiles") or record.get("SMILES") or "")
                    if not smiles:
                        continue
                    candidate: Dict[str, Any] = {
                        "name": record.get("name", smiles),
                        "smiles": smiles,
                        "formula": record.get("formula", ""),
                        "mass": _safe_float(record.get("mass")),
                        "source": "table",
                    }
                    for column in _LIST_COLUMNS:
                        values = _numeric_list(record.get(column))
                        if values:
                            candidate[column] = values
                    add(candidate)

        raw = str(self.get_param("query", "") or "").strip()
        if raw:
            for hit in search_by_name(raw, limit=int(self.get_param("top_k", 5))):
                add(dict(hit, source="library"))

        if mass is not None:
            tolerance = abs(mass) * float(self.get_param("mass_tolerance_ppm", 10.0)) / 1e6
            for hit in search_by_mass(mass, tolerance=max(tolerance, 1e-6), limit=10):
                add(dict(hit, source="library"))
        return pool

    def _score(
        self,
        candidate: Dict[str, Any],
        observed_mass: Optional[float],
        spectra: Dict[str, Optional[Spectrum]],
    ) -> Tuple[float, Dict[str, Optional[float]]]:
        """Score one candidate against every available evidence channel."""
        smiles = str(candidate.get("smiles", "") or "")
        parts: Dict[str, Optional[float]] = {}

        parts["mass"] = _mass_score(
            observed_mass, _safe_float(candidate.get("mass")),
            float(self.get_param("mass_tolerance_ppm", 10.0)),
        )

        parts["ms"] = _match_fraction(
            spectra.get("ms"),
            [float(value) for value in (candidate.get("fragments") or [])],
            0.02,
        )
        parts["ir"] = _match_fraction(
            spectra.get("ir"),
            [float(value) for value in (candidate.get("ir_bands") or [])],
            30.0,
        )
        parts["raman"] = _match_fraction(
            spectra.get("raman"),
            [float(value) for value in (candidate.get("raman_bands") or [])],
            30.0,
        )
        parts["uv"] = _match_fraction(
            spectra.get("uvvis"),
            [float(value) for value in (candidate.get("uv_max") or [])],
            12.0,
        )
        parts["nmr"] = _nmr_score(spectra.get("nmr"), smiles)

        total_weight = 0.0
        total_score = 0.0
        for channel, weight in CANDIDATE_WEIGHTS.items():
            score = parts.get(channel)
            if score is None:
                continue
            total_weight += weight
            total_score += weight * float(score)
        if total_weight <= 0:
            return 0.0, parts
        return total_score / total_weight, parts

    # -- execution ------------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectra = {
            "ms": first_of(inputs.get("ms"), Spectrum, required=False),
            "nmr": first_of(inputs.get("nmr"), Spectrum, required=False),
            "ir": first_of(inputs.get("ir"), Spectrum, required=False),
            "raman": first_of(inputs.get("raman"), Spectrum, required=False),
            "uvvis": first_of(inputs.get("uvvis"), Spectrum, required=False),
        }
        mass = self._neutral_mass(inputs)
        pool = self._candidate_pool(inputs, mass)
        if not pool:
            raise NodeInputError(
                "UnknownCompoundIdentificationNode: no candidate structures available "
                "(connect a database node, a table of SMILES, or set 'query')"
            )

        top_k = int(self.get_param("top_k", 5) or 5)
        scored: List[Dict[str, Any]] = []
        for record in pool:
            confidence, parts = self._score(record, mass, spectra)
            enriched = dict(record)
            enriched["confidence"] = round(float(confidence), 6)
            enriched["evidence"] = {
                key: (round(float(value), 6) if value is not None else None)
                for key, value in parts.items()
            }
            scored.append(enriched)
        scored.sort(key=lambda item: -float(item.get("confidence", 0.0)))
        ranked = scored[:top_k]

        best = ranked[0]
        molecule = build_molecule(
            str(best.get("smiles")),
            name=str(best.get("name") or best.get("smiles")),
            confidence=float(best.get("confidence", 0.0)),
            source="UnknownCompoundIdentificationNode",
        )

        columns = ["rank", "name", "smiles", "formula", "confidence", "source"]
        rows = [
            [index + 1, item.get("name", ""), item.get("smiles", ""),
             item.get("formula", ""), item.get("confidence", 0.0), item.get("source", "")]
            for index, item in enumerate(ranked)
        ]
        table = Table(name="identification ranking", columns=columns, rows=rows)

        language = str(self.get_param("language", "zh"))
        explanation = self._explain(molecule, ranked, mass, language)

        text = Text(
            name="identification report",
            text=explanation,
            data={
                "candidates": ranked,
                "neutral_mass": mass,
                "language": language,
                "ai": bool(self.get_param("use_ai", True)),
            },
        )
        self.log(f"identified {molecule.smiles} (confidence {molecule.confidence:.3f})")
        return {"molecule": molecule, "table": table, "text": text}

    # -- reporting -------------------------------------------------------------- #
    def _explain(
        self,
        molecule: Molecule,
        ranked: List[Dict[str, Any]],
        mass: Optional[float],
        language: str,
    ) -> str:
        """Build the human readable explanation of the ranking."""
        available = [key for key, value in ranked[0].get("evidence", {}).items() if value is not None]
        if language == "zh":
            head = (
                f"未知物鉴定结果：{molecule.smiles}"
                f"（{molecule.formula}，精确质量 {molecule.exact_mass:.4f} Da）"
            )
            lines = [
                head,
                f"置信度：{molecule.confidence:.3f}",
                f"候选数量：{len(ranked)}",
                f"参与评分的证据通道：{', '.join(available) if available else '无（使用先验排序）'}",
            ]
            if mass is not None:
                lines.append(f"推定中性质量：{mass:.4f} Da")
            lines.append("")
            lines.append("候选排名：")
            for index, item in enumerate(ranked[:10]):
                evidence = item.get("evidence", {})
                detail = ", ".join(
                    f"{key}={value:.2f}"
                    for key, value in evidence.items()
                    if value is not None
                )
                lines.append(
                    f"  {index + 1}. {item.get('name', '?')} "
                    f"[{item.get('smiles', '')}] 置信度 {float(item.get('confidence', 0.0)):.3f}"
                    + (f" ({detail})" if detail else "")
                )
            return "\n".join(lines)

        head = f"Unknown compound identification: {molecule.smiles} ({molecule.formula})"
        lines = [
            head,
            f"Confidence: {molecule.confidence:.3f}",
            f"Candidates: {len(ranked)}",
            f"Evidence channels: {', '.join(available) if available else 'none'}",
        ]
        if mass is not None:
            lines.append(f"Estimated neutral mass: {mass:.4f} Da")
        lines.append("")
        lines.append("Ranking:")
        for index, item in enumerate(ranked[:10]):
            evidence = item.get("evidence", {})
            detail = ", ".join(
                f"{key}={value:.2f}"
                for key, value in evidence.items()
                if value is not None
            )
            lines.append(
                f"  {index + 1}. {item.get('name', '?')} "
                f"[{item.get('smiles', '')}] confidence "
                f"{float(item.get('confidence', 0.0)):.3f}"
                + (f" ({detail})" if detail else "")
            )
        return "\n".join(lines)
