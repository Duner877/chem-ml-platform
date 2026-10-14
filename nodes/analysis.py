"""Spectral processing, molecular descriptors and similarity nodes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.descriptors import compute_descriptors, lipinski_violations
from models.fingerprints import morgan_bits, smiles_similarity, tanimoto
from models.spectra import IR_BANDS, RAMAN_BANDS
from models.substructure import count_substructure, detect_functional_groups, has_substructure
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, ScientificObject, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.processing import (
    als_baseline,
    find_peaks,
    moving_average,
    normalize,
    resample,
    savitzky_golay,
)
from workflow_engine.registry import register_node

from nodes._helpers import (
    build_molecule,
    collect,
    peaks_to_table,
    records_to_table,
    to_spectrum,
)

__all__ = [
    "BaselineCorrectionNode",
    "SmoothingNode",
    "PeakPickingNode",
    "NormalizeNode",
    "ResampleNode",
    "SpectrumMathNode",
    "MolecularDescriptorsNode",
    "SimilarityNode",
    "SubstructureSearchNode",
    "FunctionalGroupNode",
]


def _copy_spectrum(spectrum: Spectrum, y: Any, name: str = "") -> Spectrum:
    """Return a copy of ``spectrum`` with new intensities."""
    values = np.asarray(y, dtype=float)
    clone = Spectrum.from_arrays(
        spectrum.x,
        values,
        mode=spectrum.mode,
        x_unit=spectrum.x_unit,
        y_unit=spectrum.y_unit,
    )
    clone.technique = spectrum.technique
    clone.precursor_mz = spectrum.precursor_mz
    clone.ms_level = spectrum.ms_level
    clone.polarity = spectrum.polarity
    clone.collision_energy = spectrum.collision_energy
    clone.name = name or spectrum.name
    clone.metadata = dict(spectrum.metadata)
    clone.peaks = list(spectrum.peaks)
    return clone


# --------------------------------------------------------------------------- #
# 1-D signal processing
# --------------------------------------------------------------------------- #
@register_node
class BaselineCorrectionNode(ScientificNode):
    """Remove a slowly varying baseline from a spectrum."""

    name = "Baseline Correction"
    category = "Analysis"
    description = "使用不对称最小二乘 (ALS) 算法扣除谱图基线，适用于拉曼与红外光谱。"
    tags = ["analysis", "baseline", "raman", "ir"]
    icon = "BC"

    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [
        Port("spectrum", "Spectrum", "基线校正后的谱图"),
        Port("table", "Table", "校正统计信息"),
    ]
    parameters = [
        ParameterSpec(
            "method", "enum", "als", "基线算法", options=["als", "linear", "constant"]
        ),
        ParameterSpec("lam", "number", 1e5, "ALS 平滑因子 λ", min=1e1, max=1e9),
        ParameterSpec("p", "number", 0.01, "ALS 非对称因子 p", min=1e-4, max=0.5, step=0.001),
        ParameterSpec("niter", "integer", 10, "迭代次数", min=1, max=100),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = to_spectrum(inputs.get("spectrum"))
        if not spectrum.y:
            raise NodeInputError("BaselineCorrectionNode: spectrum has no intensities")

        y = np.asarray(spectrum.y, dtype=float)
        method = str(self.get_param("method", "als")).lower()
        if method == "als":
            baseline = als_baseline(
                y,
                lam=float(self.get_param("lam", 1e5)),
                p=float(self.get_param("p", 0.01)),
                niter=int(self.get_param("niter", 10)),
            )
        elif method == "linear":
            x = np.asarray(spectrum.x, dtype=float)
            slope, intercept = np.polyfit(x, y, 1)
            baseline = slope * x + intercept
        elif method == "constant":
            baseline = np.full_like(y, float(np.median(y)))
        else:
            baseline = np.zeros_like(y)

        corrected = _copy_spectrum(spectrum, y - baseline, name=f"{spectrum.name} (baseline)")
        corrected.metadata["baseline_method"] = method
        table = records_to_table(
            [
                {"item": "baseline_method", "value": method},
                {"item": "baseline_mean", "value": round(float(np.mean(baseline)), 6)},
                {"item": "corrected_min", "value": round(float(np.min(corrected.y)), 6)},
                {"item": "corrected_max", "value": round(float(np.max(corrected.y)), 6)},
            ],
            name="baseline correction",
        )
        self.log(f"baseline removed ({method})")
        return {"spectrum": corrected, "table": table}


@register_node
class SmoothingNode(ScientificNode):
    """Smooth a spectrum with a moving average or a Savitzky-Golay filter."""

    name = "Smoothing"
    category = "Analysis"
    description = "移动平均或 Savitzky-Golay 平滑滤波，降低高频噪声。"
    tags = ["analysis", "smooth", "denoise"]
    icon = "SM"
    # v0.7.2 P0-05: analytically verified -- a symmetric kernel reproduces
    # a linear ramp exactly (see validation_evidence).
    capability_status = "verified"
    execution_mode = "internal_approximation"
    validation_evidence = ["tests/test_v07_2_node_known_answers.py::TestSmoothingKnownAnswer::test_linear_ramp_is_invariant"]
    limitations = ["仅对一维等间距谱实现；非均匀采样需先重采样。"]
    reproducibility_level = "deterministic"

    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [Port("spectrum", "Spectrum", "平滑后的谱图")]
    parameters = [
        ParameterSpec(
            "method",
            "enum",
            "savitzky_golay",
            "滤波器",
            options=["savitzky_golay", "moving_average", "none"],
        ),
        ParameterSpec("window", "integer", 11, "窗口长度（奇数）", min=3, max=101),
        ParameterSpec("polyorder", "integer", 3, "多项式阶数", min=1, max=5),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = to_spectrum(inputs.get("spectrum"))
        method = str(self.get_param("method", "savitzky_golay")).lower()
        window = int(self.get_param("window", 11) or 11)
        if window % 2 == 0:
            window += 1

        y = np.asarray(spectrum.y, dtype=float)
        if method == "savitzky_golay":
            polyorder = int(self.get_param("polyorder", 3) or 3)
            polyorder = max(1, min(polyorder, window - 2))
            smoothed = savitzky_golay(y, window_length=window, polyorder=polyorder)
        elif method == "moving_average":
            smoothed = moving_average(y, window=window)
        else:
            smoothed = y

        result = _copy_spectrum(spectrum, smoothed, name=f"{spectrum.name} (smoothed)")
        result.metadata["smoothing"] = method
        self.log(f"smoothed with {method} (window={window})")
        return {"spectrum": result}


@register_node
class PeakPickingNode(ScientificNode):
    """Detect peaks in a spectrum and export them as a table."""

    name = "Peak Picking"
    category = "Analysis"
    description = "基于局部极大值与峰 prominence 的峰检测，输出峰表与带峰标注的谱图。"
    tags = ["analysis", "peaks", "centroid"]
    icon = "PP"
    # v0.7.2 P0-05: known-answer verified -- injected Gaussian peaks are
    # recovered to within 0.05 in x, and a flat baseline yields none.
    capability_status = "verified"
    execution_mode = "internal_approximation"
    validation_evidence = [
        "tests/test_v07_2_node_known_answers.py::TestPeakPickingKnownAnswer::test_recovers_injected_peak_positions",
        "tests/test_v07_2_node_known_answers.py::TestPeakPickingKnownAnswer::test_peak_count_is_exact",
    ]
    limitations = [
        "重叠峰需先做分峰或提高分辨率；prominence 阈值对噪声敏感。",
        "峰位精度受采样步长限制（步长 0.01 时优于 0.05）。",
    ]
    reproducibility_level = "deterministic"

    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [
        Port("spectrum", "Spectrum", "带峰列表的谱图"),
        Port("table", "Table", "峰表"),
        Port("text", "Text", "峰检测摘要"),
    ]
    parameters = [
        ParameterSpec("prominence", "number", 0.03, "相对峰 prominence", min=0.0, max=1.0, step=0.001),
        ParameterSpec("distance", "number", 0.0, "相邻峰最小间距", min=0.0),
        ParameterSpec("max_peaks", "integer", 100, "最多保留峰数", min=1, max=1000),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = to_spectrum(inputs.get("spectrum"))
        detection = find_peaks(
            spectrum.x,
            spectrum.y,
            height=None,
            prominence=float(self.get_param("prominence", 0.03)),
            distance=float(self.get_param("distance", 0.0)),
            max_peaks=int(self.get_param("max_peaks", 100)),
        )
        clone = Spectrum.from_arrays(
            spectrum.x,
            spectrum.y,
            mode=spectrum.mode,
            x_unit=spectrum.x_unit,
            y_unit=spectrum.y_unit,
        )
        for field in ("technique", "precursor_mz", "ms_level", "polarity", "collision_energy", "name", "peaks"):
            setattr(clone, field, getattr(spectrum, field))
        clone.metadata = dict(spectrum.metadata)
        clone.peaks = list(detection)

        table = peaks_to_table(clone, limit=int(self.get_param("max_peaks", 100)))
        summary = (
            f"{spectrum.mode} spectrum: {len(detection)} peaks detected "
            f"within {spectrum.x[0]:.3f}–{spectrum.x[-1]:.3f} {spectrum.x_unit or ''}"
        )
        self.log(summary)
        return {
            "spectrum": clone,
            "table": table,
            "text": Text(name="peak picking", text=summary),
        }


@register_node
class NormalizeNode(ScientificNode):
    """Normalise the intensity axis of a spectrum."""

    name = "Normalize"
    category = "Analysis"
    description = "按最大值、面积、min-max 或 SNV 归一化谱图强度。"
    tags = ["analysis", "normalize"]
    icon = "NM"
    # v0.7.2 P0-05: exact known answer -- max-normalisation maps the
    # maximum to exactly 1.0 and preserves the arg-max position.
    capability_status = "verified"
    execution_mode = "internal_approximation"
    validation_evidence = [
        "tests/test_v07_2_node_known_answers.py::TestNormalizeKnownAnswer::test_max_normalisation_is_exact",
        "tests/test_v07_2_node_known_answers.py::TestNormalizeKnownAnswer::test_none_is_identity",
    ]
    limitations = ["归一化只改变强度尺度，不改变峰位；跨样本比较仍需一致的预处理链。"]
    reproducibility_level = "deterministic"

    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [Port("spectrum", "Spectrum", "归一化后的谱图")]
    parameters = [
        ParameterSpec(
            "method",
            "enum",
            "max",
            "归一化方法",
            options=["max", "area", "minmax", "snv", "none"],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = to_spectrum(inputs.get("spectrum"))
        method = str(self.get_param("method", "max")).lower()
        values = normalize(spectrum.y, method=method, x=spectrum.x)
        result = _copy_spectrum(spectrum, values, name=f"{spectrum.name} (norm)")
        result.metadata["normalization"] = method
        self.log(f"normalized with {method}")
        return {"spectrum": result}


@register_node
class ResampleNode(ScientificNode):
    """Resample a spectrum on a uniform grid."""

    name = "Resample"
    category = "Analysis"
    description = "将谱图重采样到等间距网格，便于多谱图对齐与融合。"
    tags = ["analysis", "resample", "interpolate"]
    icon = "RS"

    input_ports = [Port("spectrum", "Spectrum", "输入谱图")]
    output_ports = [Port("spectrum", "Spectrum", "重采样后的谱图")]
    parameters = [
        ParameterSpec("step", "number", 1.0, "网格步长", min=1e-6),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectrum = to_spectrum(inputs.get("spectrum"))
        grid, values = resample(spectrum.x, spectrum.y, float(self.get_param("step", 1.0)))
        result = Spectrum.from_arrays(
            grid,
            values,
            mode=spectrum.mode,
            x_unit=spectrum.x_unit,
            y_unit=spectrum.y_unit,
            name=f"{spectrum.name} (resampled)",
            technique=spectrum.technique,
        )
        result.metadata = dict(spectrum.metadata)
        result.metadata["resample_step"] = float(self.get_param("step", 1.0))
        self.log(f"resampled to {len(grid)} points")
        return {"spectrum": result}


@register_node
class SpectrumMathNode(ScientificNode):
    """Combine two spectra with an arithmetic operator."""

    name = "Spectrum Math"
    category = "Analysis"
    description = "两个谱图之间的加 / 减 / 乘 / 除运算（按 x 轴线性插值对齐）。"
    tags = ["analysis", "math", "difference"]
    icon = "MA"

    input_ports = [
        Port("a", "Spectrum", "谱图 A"),
        Port("b", "Spectrum", "谱图 B"),
    ]
    output_ports = [
        Port("spectrum", "Spectrum", "运算结果"),
        Port("text", "Text", "运算摘要"),
    ]
    parameters = [
        ParameterSpec(
            "operation",
            "enum",
            "subtract",
            "运算符",
            options=["subtract", "add", "multiply", "divide"],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        first = to_spectrum(inputs.get("a"), what="input 'a'")
        second = to_spectrum(inputs.get("b"), what="input 'b'")
        operation = str(self.get_param("operation", "subtract")).lower()

        x_first = np.asarray(first.x, dtype=float)
        x_second = np.asarray(second.x, dtype=float)
        y_second = np.asarray(second.y, dtype=float)
        if x_second.size < 2 or x_first.size < 2:
            raise NodeInputError("SpectrumMathNode: both spectra need at least 2 points")

        order = np.argsort(x_second)
        aligned = np.interp(x_first, x_second[order], y_second[order])
        y_first = np.asarray(first.y, dtype=float)

        if operation == "subtract":
            values = y_first - aligned
        elif operation == "add":
            values = y_first + aligned
        elif operation == "multiply":
            values = y_first * aligned
        elif operation == "divide":
            denominator = np.where(np.abs(aligned) < 1e-12, 1e-12, aligned)
            values = y_first / denominator
        else:
            raise NodeInputError(f"SpectrumMathNode: unknown operation {operation!r}")

        result = Spectrum.from_arrays(
            x_first,
            values,
            mode=first.mode,
            x_unit=first.x_unit,
            y_unit=first.y_unit,
            name=f"{first.name} {operation} {second.name}",
        )
        result.metadata = dict(first.metadata)
        result.metadata["operation"] = operation
        summary = f"{first.name} {operation} {second.name}: {len(values)} points"
        self.log(summary)
        return {"spectrum": result, "text": Text(name="spectrum math", text=summary)}


# --------------------------------------------------------------------------- #
# Cheminformatics
# --------------------------------------------------------------------------- #
@register_node
class MolecularDescriptorsNode(ScientificNode):
    """Compute physicochemical descriptors for a molecule."""

    name = "Molecular Descriptors"
    category = "Analysis"
    description = "计算分子量、LogP、TPSA、氢键供受体、可旋转键、Lipinski 违背数与 QED。"
    tags = ["analysis", "descriptors", "qed", "lipinski"]
    icon = "MD"

    input_ports = [Port("molecule", "Molecule", "输入分子")]
    output_ports = [
        Port("molecule", "Molecule", "带描述符的分子"),
        Port("table", "Table", "描述符表"),
        Port("text", "Text", "描述符摘要"),
    ]
    parameters = [
        ParameterSpec("with_3d", "boolean", False, "同时生成三维坐标"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        from nodes._helpers import first_of

        incoming = first_of(inputs.get("molecule"), Molecule, what="input 'molecule'")
        smiles = incoming.smiles or incoming.name
        if not smiles:
            raise NodeInputError("MolecularDescriptorsNode: molecule has no SMILES")

        descriptors = compute_descriptors(smiles)
        violations = lipinski_violations(descriptors)
        descriptors["LipinskiViolations"] = int(violations)

        molecule = build_molecule(
            smiles,
            name=incoming.name if incoming.name != incoming.smiles else smiles,
            confidence=incoming.confidence,
            with_coords=bool(self.get_param("with_3d", False)),
            properties=descriptors,
            source=incoming.source or "MolecularDescriptorsNode",
        )
        from models.descriptors import QED

        molecule.properties["QED"] = float(QED(descriptors))

        table = Table(
            name="descriptors",
            columns=["descriptor", "value"],
            rows=[[key, value] for key, value in molecule.properties.items()],
        )
        summary = (
            f"{smiles}: {molecule.formula}, MW {molecule.properties.get('MolWt', 0):.2f}, "
            f"LogP {molecule.properties.get('MolLogP', 0):.2f}, "
            f"TPSA {molecule.properties.get('TPSA', 0):.2f}, "
            f"Lipinski violations {violations}"
        )
        self.log(summary)
        return {
            "molecule": molecule,
            "table": table,
            "text": Text(name="descriptors", text=summary),
        }


@register_node
class SimilarityNode(ScientificNode):
    """Compare two molecules with Morgan (ECFP-like) fingerprints."""

    name = "Molecular Similarity"
    category = "Analysis"
    description = "计算两个分子的 Morgan 指纹 Tanimoto / Dice 相似度。"
    tags = ["analysis", "similarity", "tanimoto", "fingerprint"]
    icon = "SI"

    input_ports = [
        Port("a", "Molecule", "分子 A"),
        Port("b", "Molecule", "分子 B"),
    ]
    output_ports = [
        Port("table", "Table", "相似度表"),
        Port("text", "Text", "相似度摘要"),
    ]
    parameters = [
        ParameterSpec("radius", "integer", 2, "Morgan 半径", min=1, max=4),
        ParameterSpec("n_bits", "integer", 2048, "指纹位数", min=256, max=8192),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        from nodes._helpers import first_of

        first = first_of(inputs.get("a"), Molecule, what="input 'a'")
        second = first_of(inputs.get("b"), Molecule, what="input 'b'")
        radius = int(self.get_param("radius", 2) or 2)
        n_bits = int(self.get_param("n_bits", 2048) or 2048)

        bits_first = morgan_bits(first.smiles or first.name, radius=radius, n_bits=n_bits)
        bits_second = morgan_bits(second.smiles or second.name, radius=radius, n_bits=n_bits)
        jaccard = tanimoto(bits_first, bits_second)
        from models.fingerprints import dice

        dice_score = dice(bits_first, bits_second)

        table = Table(
            name="similarity",
            columns=["metric", "value"],
            rows=[
                ["tanimoto", round(float(jaccard), 6)],
                ["dice", round(float(dice_score), 6)],
                ["bits_a", len(bits_first)],
                ["bits_b", len(bits_second)],
                ["common_bits", len(bits_first & bits_second)],
            ],
        )
        summary = (
            f"Tanimoto({first.name}, {second.name}) = {jaccard:.4f}, "
            f"Dice = {dice_score:.4f}"
        )
        self.log(summary)
        return {"table": table, "text": Text(name="similarity", text=summary)}


@register_node
class SubstructureSearchNode(ScientificNode):
    """Search a substructure (SMARTS-like plain SMILES) inside a molecule."""

    name = "Substructure Search"
    category = "Analysis"
    description = "使用 VF2 子图同构在分子中检索指定子结构（SMILES 片段）。"
    tags = ["analysis", "substructure", "vf2"]
    icon = "SS"

    input_ports = [Port("molecule", "Molecule", "输入分子")]
    output_ports = [
        Port("table", "Table", "检索结果"),
        Port("text", "Text", "检索摘要"),
    ]
    parameters = [
        ParameterSpec("pattern", "string", "c1ccccc1", "子结构 SMILES（如 c1ccccc1）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        from nodes._helpers import first_of

        molecule = first_of(inputs.get("molecule"), Molecule, what="input 'molecule'")
        pattern = str(self.get_param("pattern", "") or "").strip()
        if not pattern:
            raise NodeInputError("SubstructureSearchNode: parameter 'pattern' is empty")

        count = count_substructure(molecule.smiles or molecule.name, pattern)
        found = has_substructure(molecule.smiles or molecule.name, pattern)
        table = Table(
            name="substructure",
            columns=["pattern", "matches", "found"],
            rows=[[pattern, int(count), bool(found)]],
        )
        summary = f"{pattern}: {count} match(es) in {molecule.name}"
        self.log(summary)
        return {"table": table, "text": Text(name="substructure", text=summary)}


@register_node
class FunctionalGroupNode(ScientificNode):
    """Assign functional groups from a structure or from IR / Raman bands."""

    name = "Functional Groups"
    category = "Analysis"
    description = "从分子结构或红外 / 拉曼谱带指认官能团，输出统计表与文字说明。"
    tags = ["analysis", "functional group", "ir", "raman"]
    icon = "FG"

    input_ports = [Port("data", "Any", "分子或红外 / 拉曼谱图", optional=True, multi=True)]
    output_ports = [
        Port("table", "Table", "官能团统计"),
        Port("text", "Text", "官能团指认说明"),
    ]
    parameters = [
        ParameterSpec("smiles", "string", "", "备用 SMILES（无输入时使用）"),
        ParameterSpec("tolerance", "number", 25.0, "谱带匹配容差", unit="cm⁻¹", min=1.0, max=200.0),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        from nodes._helpers import first_of

        items = collect(inputs.get("data"))
        smiles = str(self.get_param("smiles", "") or "").strip()
        bands_source = None

        for item in items:
            if isinstance(item, Molecule) and item.smiles:
                smiles = smiles or item.smiles
            elif isinstance(item, Spectrum) and item.mode in {"IR", "Raman"}:
                bands_source = item
        if not smiles and bands_source is None:
            raise NodeInputError("FunctionalGroupNode: provide a molecule, an IR/Raman spectrum or a SMILES")

        if smiles:
            groups = detect_functional_groups(smiles)
        else:
            groups = _assign_bands(bands_source, float(self.get_param("tolerance", 25.0)))

        rows = [[name, int(count)] for name, count in sorted(groups.items(), key=lambda kv: (-kv[1], kv[0]))]
        table = Table(name="functional groups", columns=["group", "count"], rows=rows)
        pretty = ", ".join(f"{name}×{count}" for name, count in rows) or "none detected"
        summary = f"Functional groups ({smiles or bands_source.mode}): {pretty}"
        self.log(summary)
        return {"table": table, "text": Text(name="functional groups", text=summary)}


def _assign_bands(spectrum: Spectrum, tolerance: float) -> Dict[str, int]:
    """Assign the peaks of an IR / Raman spectrum to known group frequencies."""
    table = IR_BANDS if spectrum.mode == "IR" else RAMAN_BANDS
    detected: Dict[str, int] = {}
    peaks = spectrum.peaks or find_peaks(spectrum.x, spectrum.y, prominence=0.05)
    for peak in peaks:
        best_group = ""
        best_distance = float("inf")
        for group, bands in table.items():
            for center, _intensity, _label in bands:
                distance = abs(float(center) - float(peak.x))
                if distance < best_distance:
                    best_distance = distance
                    best_group = group
        if best_group and best_distance <= tolerance:
            detected[best_group] = detected.get(best_group, 0) + 1
    return detected
