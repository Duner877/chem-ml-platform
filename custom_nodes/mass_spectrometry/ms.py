"""Mass spectrometry instruments (LC-MS, GC-MS, MALDI, ICP-MS)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.spectra import predict_ms
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Material, Molecule, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.processing import (
    ISOTOPES,
    find_peaks,
    neutral_mass,
    parse_formula,
)
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import ensure_peaks, peaks_to_table, records_to_table
from custom_nodes._shared._base import (
    InstrumentNode,
    find_spectrum,
    resolve_smiles,
    sample_items,
)

__all__ = [
    "MassSpectrometryNode",
    "LCMSNode",
    "GCMSNode",
    "MALDINode",
    "ICPMSNode",
]

ADDUCT_OPTIONS = [
    "[M]+",
    "[M+H]+",
    "[M+Na]+",
    "[M+K]+",
    "[M+NH4]+",
    "[M+H-H2O]+",
    "[M+2H]2+",
    "[M]-",
    "[M-H]-",
    "[M+Cl]-",
    "[M+FA-H]-",
    "[M+Ac-H]-",
    "[M-2H]2-",
]

MS_PARAMETERS = [
    ParameterSpec(
        "smiles",
        "string",
        "",
        "待测物 SMILES（无上游分子时使用）",
    ),
    ParameterSpec("adduct", "enum", "[M+H]+", "加合离子", options=ADDUCT_OPTIONS),
    ParameterSpec(
        "polarity", "enum", "positive", "电离极性", options=["positive", "negative"]
    ),
    ParameterSpec("resolution", "number", 8000.0, "质量分辨率", min=500.0, max=500000.0),
    ParameterSpec("max_mz", "number", 1200.0, "最大 m/z", min=50.0, max=10000.0),
    ParameterSpec("points", "integer", 4000, "谱图采样点数", min=500, max=40000),
    ParameterSpec("noise", "number", 0.004, "相对噪声水平", min=0.0, max=0.5, step=0.001),
    ParameterSpec("pick_peaks", "boolean", True, "自动峰检测"),
    ParameterSpec("prominence", "number", 0.02, "峰检测 prominence", min=0.0, max=1.0, step=0.001),
]


# --------------------------------------------------------------------------- #
# Shared implementation
# --------------------------------------------------------------------------- #
class MassSpectrometryNode(InstrumentNode):
    """Common behaviour of the mass spectrometry family.

    When a spectrum is connected to ``sample`` it is reused (and re-centroided
    when requested); otherwise the internal fragmentation model of
    :func:`models.spectra.predict_ms` simulates the acquisition from a SMILES.
    """

    technique = "MS"
    instrument = "virtual mass spectrometer"
    ionization = "ESI"
    default_adduct = "[M+H]+"

    parameters = list(MS_PARAMETERS)

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="MS")
        if existing is not None:
            spectrum = existing
            spectrum.mode = "MS"
            spectrum.polarity = str(self.get_param("polarity", "positive"))
            spectrum.metadata.setdefault("origin", "upstream spectrum")
        else:
            smiles = resolve_smiles(self, inputs)
            if not smiles:
                raise NodeInputError(
                    f"{self.node_type()}: connect a molecule or set the 'smiles' parameter"
                )
            spectrum = predict_ms(
                smiles,
                adduct=str(self.get_param("adduct", self.default_adduct)),
                polarity=str(self.get_param("polarity", "positive")),
                resolution=float(self.get_param("resolution", 8000.0)),
                max_mz=float(self.get_param("max_mz", 1200.0)),
                points=int(self.get_param("points", 4000)),
                noise=float(self.get_param("noise", 0.004)),
            )
            spectrum.technique = f"{self.technique} ({self.ionization})"
            spectrum.metadata["ionization"] = self.ionization
            spectrum.metadata["smiles"] = smiles

        if bool(self.get_param("pick_peaks", True)):
            ensure_peaks(spectrum, prominence=float(self.get_param("prominence", 0.02)))
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        table = peaks_to_table(spectrum, limit=60, name=f"{self.technique} peaks")
        precursor = spectrum.precursor_mz
        neutral = neutral_mass(precursor, str(self.get_param("adduct", self.default_adduct))) if precursor else 0.0
        lines = [
            f"Technique      : {self.technique} ({self.ionization})",
            f"Polarity       : {self.get_param('polarity', 'positive')}",
            f"Adduct         : {self.get_param('adduct', self.default_adduct)}",
            f"Data points    : {spectrum.size}",
            f"Peaks detected : {len(spectrum.peaks)}",
        ]
        if precursor:
            lines.append(f"Precursor m/z  : {precursor:.4f}")
            lines.append(f"Neutral mass   : {neutral:.4f} Da")
        if spectrum.peaks:
            base = spectrum.max_peak()
            lines.append(f"Base peak      : m/z {base.x:.4f} ({base.assignment or 'unassigned'})")
        return {"table": table, "text": Text(name=self.technique, text="\n".join(lines))}


@register_node
class LCMSNode(MassSpectrometryNode):
    """Liquid chromatography – mass spectrometry."""

    name = "LC-MS"
    category = "Instruments/Mass Spectrometry"
    description = "液相色谱-质谱联用：电喷雾电离，适合极性 / 热不稳定化合物的一级与二级质谱。"
    tags = ["instrument", "ms", "lcms", "esi"]
    aliases = ["LCMS", "LC_MS"]
    icon = "LC"

    technique = "LC-MS"
    instrument = "virtual LC-MS (ESI-QTOF)"
    ionization = "ESI"
    default_adduct = "[M+H]+"

    parameters = MS_PARAMETERS + [
        ParameterSpec(
            "gradient", "string", "5-95% MeCN in 10 min", "色谱梯度描述", advanced=True
        ),
    ]


@register_node
class GCMSNode(MassSpectrometryNode):
    """Gas chromatography – mass spectrometry with EI fragmentation."""

    name = "GC-MS"
    category = "Instruments/Mass Spectrometry"
    description = "气相色谱-质谱联用：电子轰击电离 (70 eV)，适合挥发性 / 热稳定化合物。"
    tags = ["instrument", "ms", "gcms", "ei"]
    aliases = ["GCMS", "GC_MS"]
    icon = "GC"

    technique = "GC-MS"
    instrument = "virtual GC-MS (EI quadrupole)"
    ionization = "EI"
    default_adduct = "[M]+"


@register_node
class MALDINode(MassSpectrometryNode):
    """MALDI time-of-flight mass spectrometry."""

    name = "MALDI-TOF"
    category = "Instruments/Mass Spectrometry"
    description = "基质辅助激光解吸电离飞行时间质谱，适合多肽 / 聚合物 / 大分子。"
    tags = ["instrument", "ms", "maldi", "tof"]
    aliases = ["MALDI", "MALDITOF"]
    icon = "ML"

    technique = "MALDI-TOF"
    instrument = "virtual MALDI-TOF"
    ionization = "MALDI"
    default_adduct = "[M+H]+"


@register_node
class ICPMSNode(InstrumentNode):
    """Inductively coupled plasma – mass spectrometry (elemental analysis)."""

    name = "ICP-MS"
    category = "Instruments/Mass Spectrometry"
    description = "电感耦合等离子体质谱：元素定性定量分析，按天然同位素丰度给出同位素峰簇。"
    tags = ["instrument", "ms", "icpms", "elemental"]
    aliases = ["ICPMS", "ICP_MS"]
    icon = "IC"

    technique = "ICP-MS"
    instrument = "virtual ICP-MS"

    input_ports = [
        Port("sample", "Any", "上游材料（取其元素组成）", optional=True, multi=True)
    ]
    output_ports = [
        Port("spectrum", "Spectrum", "元素质谱图"),
        Port("table", "Table", "元素定量结果"),
        Port("text", "Text", "分析报告"),
    ]

    parameters = [
        ParameterSpec("elements", "string", "Fe, Cu, Zn", "待测元素列表，逗号分隔"),
        ParameterSpec(
            "concentrations",
            "string",
            "",
            "各元素浓度 (ppb)，逗号分隔；留空则按等浓度",
        ),
        ParameterSpec("resolution", "number", 3000.0, "质量分辨率", min=300.0, max=100000.0),
        ParameterSpec("max_mz", "number", 250.0, "最大 m/z", min=10.0, max=500.0),
        ParameterSpec("points", "integer", 3000, "谱图采样点数", min=500, max=20000),
        ParameterSpec("pick_peaks", "boolean", True, "自动峰检测"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        composition: List[Dict[str, Any]] = []
        for item in sample_items(inputs):
            if isinstance(item, Material):
                composition = [
                    {"element": component.formula, "fraction": float(component.fraction)}
                    for component in item.composition
                ]
                break
            if isinstance(item, Molecule) and item.formula and not composition:
                composition = [
                    {"element": element, "fraction": float(count)}
                    for element, count in sorted(parse_formula(item.formula).items())
                ]

        raw_elements = str(self.get_param("elements", "") or "").strip()
        if raw_elements and not composition:
            composition = [
                {"element": token.strip().capitalize(), "fraction": 1.0}
                for token in raw_elements.split(",")
                if token.strip()
            ]
        raw_concentrations = str(self.get_param("concentrations", "") or "").strip()
        if raw_concentrations:
            values = [float(token) for token in raw_concentrations.split(",") if token.strip()]
            for index, entry in enumerate(composition):
                entry["fraction"] = values[index] if index < len(values) else 1.0
        if not composition:
            raise NodeInputError("ICPMSNode: no element specified")

        max_mz = float(self.get_param("max_mz", 250.0))
        grid = np.linspace(1.0, max_mz, int(self.get_param("points", 3000)))
        signal = np.zeros_like(grid)
        peaks = []
        for entry in composition:
            element = str(entry.get("element", "")).capitalize()
            weight = float(entry.get("fraction", 1.0) or 1.0)
            isotopes = ISOTOPES.get(element)
            if not isotopes:
                continue
            for isotope_mass, abundance in isotopes:
                if isotope_mass > max_mz:
                    continue
                intensity = weight * abundance * 100.0
                width = max(0.08, isotope_mass / float(self.get_param("resolution", 3000.0)))
                signal += intensity * np.exp(-0.5 * ((grid - isotope_mass) / width) ** 2)
                peaks.append(
                    {
                        "x": round(float(isotope_mass), 4),
                        "y": round(float(intensity), 4),
                        "intensity": round(float(intensity), 4),
                        "width": round(float(width), 4),
                        "area": 0.0,
                        "label": element,
                        "assignment": f"{element}-{round(isotope_mass)}",
                    }
                )
        peaks.sort(key=lambda item: -float(item["y"]))
        spectrum = Spectrum(
            mode="MS",
            technique="ICP-MS",
            name="simulated ICP-MS spectrum",
            x=[float(value) for value in grid],
            y=[float(value) for value in signal],
            x_unit="m/z",
            y_unit="counts (a.u.)",
            peaks=[_peak_from_mapping(item) for item in peaks[:40]],
            metadata={
                "synthetic": True,
                "elements": [entry["element"] for entry in composition],
            },
        )
        if bool(self.get_param("pick_peaks", True)):
            spectrum.peaks = list(find_peaks(grid, signal, prominence=0.02))
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        rows = []
        for peak in spectrum.peaks[:30]:
            rows.append([round(float(peak.x), 4), round(float(peak.y), 3), peak.assignment or peak.label])
        table = Table(
            name="ICP-MS quantification",
            columns=["m/z", "intensity", "assignment"],
            rows=rows,
        )
        total = sum(float(peak.y) for peak in spectrum.peaks) or 1.0
        lines = [
            f"ICP-MS analysis of {len(rows)} isotope lines",
            "",
            "Isotope   Intensity   Relative",
        ]
        for peak in spectrum.peaks[:12]:
            lines.append(
                f"{peak.assignment or peak.label:>9} {float(peak.y):10.2f} {float(peak.y) / total * 100:9.2f}%"
            )
        return {"table": table, "text": Text(name="ICP-MS", text="\n".join(lines))}


def _peak_from_mapping(mapping: Dict[str, Any]):
    from workflow_engine.objects import Peak

    return Peak(**mapping)
