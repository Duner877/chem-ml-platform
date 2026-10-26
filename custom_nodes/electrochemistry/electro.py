"""Electrochemistry: cyclic voltammetry and electrochemical impedance."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.materials import simulate_cv, simulate_eis
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import ensure_peaks
from custom_nodes._shared._base import InstrumentNode, find_spectrum, sample_items

__all__ = ["CVNode", "EISNode"]


@register_node
class CVNode(InstrumentNode):
    """Cyclic voltammetry workstation."""

    name = "Cyclic Voltammetry"
    category = "Instruments/Electrochemistry"
    description = "循环伏安工作站：有限差分扩散 + Butler-Volmer 动力学，输出峰电位与峰电流。"
    tags = ["instrument", "cv", "electrochemistry", "butler-volmer"]
    aliases = ["CV"]
    icon = "CV"

    technique = "CV"
    instrument = "virtual potentiostat"

    parameters = [
        ParameterSpec("scan_rate_v_per_s", "number", 0.1, "扫描速率", unit="V/s", min=1e-4),
        ParameterSpec("area_cm2", "number", 0.07, "电极面积", unit="cm²", min=1e-4),
        ParameterSpec(
            "concentration_mol_per_cm3",
            "number",
            1.0e-5,
            "本体浓度",
            unit="mol/cm³",
            min=1e-12,
            advanced=True,
        ),
        ParameterSpec(
            "diffusion_cm2_per_s",
            "number",
            1.0e-5,
            "扩散系数",
            unit="cm²/s",
            min=1e-12,
            advanced=True,
        ),
        ParameterSpec("e0", "number", 0.3, "标准电位 E°", unit="V", advanced=True),
        ParameterSpec("e_upper", "number", 0.8, "上限电位", unit="V"),
        ParameterSpec("e_lower", "number", -0.2, "下限电位", unit="V"),
        ParameterSpec("steps", "integer", 1200, "采样步数", min=100, max=20000, advanced=True),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="CV")
        if existing is not None:
            return existing
        return simulate_cv(
            e_start=float(self.get_param("e_lower", -0.2)),
            e_upper=float(self.get_param("e_upper", 0.8)),
            e_lower=float(self.get_param("e_lower", -0.2)),
            scan_rate_v_per_s=float(self.get_param("scan_rate_v_per_s", 0.1)),
            area_cm2=float(self.get_param("area_cm2", 0.07)),
            concentration_mol_per_cm3=float(
                self.get_param("concentration_mol_per_cm3", 1.0e-5)
            ),
            diffusion_cm2_per_s=float(self.get_param("diffusion_cm2_per_s", 1.0e-5)),
            e0=float(self.get_param("e0", 0.3)),
            steps=int(self.get_param("steps", 1200)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        ensure_peaks(spectrum, prominence=0.05)
        currents = np.asarray(spectrum.y, dtype=float)
        anodic = float(np.max(currents)) if currents.size else 0.0
        cathodic = float(np.min(currents)) if currents.size else 0.0
        table = Table(
            name="CV summary",
            columns=["metric", "value"],
            rows=[
                ["anodic_peak_current_A", round(anodic, 9)],
                ["cathodic_peak_current_A", round(cathodic, 9)],
                ["scan_rate_V_per_s", float(self.get_param("scan_rate_v_per_s", 0.1))],
            ],
        )
        lines = [
            f"Cyclic voltammetry at {float(self.get_param('scan_rate_v_per_s', 0.1)):.3f} V/s",
            f"  Anodic peak   : {anodic * 1e6:.3f} µA",
            f"  Cathodic peak : {cathodic * 1e6:.3f} µA",
            f"  |Ia/Ic|       : {abs(anodic / cathodic) if cathodic else float('nan'):.3f}",
        ]
        return {"table": table, "text": Text(name="CV", text="\n".join(lines))}


@register_node
class EISNode(InstrumentNode):
    """Electrochemical impedance spectrometer (Randles + Warburg)."""

    name = "EIS"
    category = "Instruments/Electrochemistry"
    description = "电化学阻抗谱：Randles 等效电路 + Warburg 扩散阻抗，输出 Nyquist / Bode 数据。"
    tags = ["instrument", "eis", "impedance", "nyquist"]
    aliases = ["EIS"]
    icon = "EI"

    technique = "EIS"
    instrument = "virtual impedance analyser"

    parameters = [
        ParameterSpec("solution_resistance", "number", 20.0, "溶液电阻 Rs", unit="Ω", min=0.0),
        ParameterSpec("charge_transfer", "number", 500.0, "电荷转移电阻 Rct", unit="Ω", min=0.01),
        ParameterSpec("double_layer", "number", 2.0e-5, "双电层电容 Cdl", unit="F", min=1e-12),
        ParameterSpec("warburg", "number", 150.0, "Warburg 系数", unit="Ω·s^-1/2", min=0.0),
        ParameterSpec("f_min", "number", 1.0e-2, "最低频率", unit="Hz", min=1e-6),
        ParameterSpec("f_max", "number", 1.0e6, "最高频率", unit="Hz", min=1.0),
        ParameterSpec("points", "integer", 90, "频点数量", min=10, max=500),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="EIS")
        if existing is not None:
            return existing
        return simulate_eis(
            solution_resistance=float(self.get_param("solution_resistance", 20.0)),
            charge_transfer=float(self.get_param("charge_transfer", 500.0)),
            double_layer=float(self.get_param("double_layer", 2.0e-5)),
            warburg=float(self.get_param("warburg", 150.0)),
            f_min=float(self.get_param("f_min", 1.0e-2)),
            f_max=float(self.get_param("f_max", 1.0e6)),
            points=int(self.get_param("points", 90)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        real = np.asarray(spectrum.x, dtype=float)
        imag = np.asarray(spectrum.y, dtype=float)
        magnitude = np.sqrt(real**2 + imag**2)
        table = Table(
            name="EIS summary",
            columns=["metric", "value"],
            rows=[
                ["Rs_ohm", float(self.get_param("solution_resistance", 20.0))],
                ["Rct_ohm", float(self.get_param("charge_transfer", 500.0))],
                ["|Z|_max_ohm", round(float(np.max(magnitude)) if magnitude.size else 0.0, 3)],
                ["|Z|_min_ohm", round(float(np.min(magnitude)) if magnitude.size else 0.0, 3)],
                ["points", int(real.size)],
            ],
        )
        lines = [
            "Electrochemical impedance spectrum",
            f"  Rs  : {float(self.get_param('solution_resistance', 20.0)):.1f} Ω",
            f"  Rct : {float(self.get_param('charge_transfer', 500.0)):.1f} Ω",
            f"  |Z| : {float(np.min(magnitude)) if magnitude.size else 0.0:.1f} – "
            f"{float(np.max(magnitude)) if magnitude.size else 0.0:.1f} Ω",
        ]
        return {"table": table, "text": Text(name="EIS", text="\n".join(lines))}
