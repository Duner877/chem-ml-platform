"""Thermal analysis: DSC, TGA, DMA."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.materials import simulate_dma, simulate_dsc, simulate_tga
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes._helpers import ensure_peaks
from nodes.instruments._base import InstrumentNode, find_spectrum, sample_items

__all__ = ["DSCNode", "TGANode", "DMANode"]


@register_node
class DSCNode(InstrumentNode):
    """Differential scanning calorimeter."""

    name = "DSC"
    category = "Instruments/Thermal"
    description = "差示扫描量热仪：玻璃化转变、熔融与结晶热分析。"
    version = "0.7.1"
    tags = ["instrument", "dsc", "thermal", "glass transition", "melting"]
    aliases = ["DSC"]
    icon = "DS"

    technique = "DSC"
    instrument = "virtual DSC"

    parameters = [
        ParameterSpec("mass_mg", "number", 5.0, "样品质量", unit="mg", min=0.01, max=200.0),
        ParameterSpec("heat_capacity", "number", 1.2, "比热容", unit="J/(g·K)", min=0.05),
        ParameterSpec("glass_transition_c", "number", 120.0, "玻璃化温度 Tg", unit="°C"),
        ParameterSpec("melting_point_c", "number", 220.0, "熔点 Tm", unit="°C"),
        ParameterSpec("melting_enthalpy", "number", 90.0, "熔融焓", unit="J/g", min=0.0),
        ParameterSpec("rate_c_per_min", "number", 10.0, "升温速率", unit="°C/min", min=0.1),
        ParameterSpec("t_min", "number", 25.0, "起始温度", unit="°C"),
        ParameterSpec("t_max", "number", 350.0, "终止温度", unit="°C"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="DSC")
        if existing is not None:
            return existing
        return simulate_dsc(
            mass_mg=float(self.get_param("mass_mg", 5.0)),
            heat_capacity=float(self.get_param("heat_capacity", 1.2)),
            glass_transition_c=float(self.get_param("glass_transition_c", 120.0)),
            melting_point_c=float(self.get_param("melting_point_c", 220.0)),
            melting_enthalpy=float(self.get_param("melting_enthalpy", 90.0)),
            rate_c_per_min=float(self.get_param("rate_c_per_min", 10.0)),
            t_min=float(self.get_param("t_min", 25.0)),
            t_max=float(self.get_param("t_max", 350.0)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        ensure_peaks(spectrum, prominence=0.05)
        rows = [[round(float(peak.x), 2), round(float(peak.y), 4), peak.assignment or "transition"] for peak in spectrum.peaks]
        table = Table(name="DSC transitions", columns=["temperature (°C)", "heat flow (mW)", "assignment"], rows=rows[:20])
        lines = [
            f"DSC at {float(self.get_param('rate_c_per_min', 10.0)):.1f} °C/min",
            f"  Tg (set) : {float(self.get_param('glass_transition_c', 120.0)):.1f} °C",
            f"  Tm (set) : {float(self.get_param('melting_point_c', 220.0)):.1f} °C",
            f"  ΔHm      : {float(self.get_param('melting_enthalpy', 90.0)):.1f} J/g",
            f"  Detected : {len(rows)} transition(s)",
        ]
        return {"table": table, "text": Text(name="DSC", text="\n".join(lines))}


@register_node
class TGANode(InstrumentNode):
    """Thermogravimetric analyser."""

    name = "TGA"
    category = "Instruments/Thermal"
    description = "热重分析仪：多步失重过程模拟，输出各步起始温度与残余质量。"
    version = "0.7.1"
    tags = ["instrument", "tga", "thermal", "decomposition"]
    aliases = ["TGA"]
    icon = "TG"

    technique = "TGA"
    instrument = "virtual TGA"

    parameters = [
        ParameterSpec(
            "steps",
            "text",
            "120,0.05\n320,0.35\n520,0.25",
            "失重步骤，每行「峰值温度°C,失重分数」",
        ),
        ParameterSpec("rate_c_per_min", "number", 10.0, "升温速率", unit="°C/min", min=0.1),
        ParameterSpec("t_min", "number", 25.0, "起始温度", unit="°C"),
        ParameterSpec("t_max", "number", 800.0, "终止温度", unit="°C"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="TGA")
        if existing is not None:
            return existing

        steps: List[Dict[str, float]] = []
        for line in str(self.get_param("steps", "") or "").splitlines():
            line = line.strip()
            if not line or "," not in line:
                continue
            left, right = line.split(",", 1)
            try:
                steps.append({"center": float(left), "fraction": float(right)})
            except ValueError:
                continue
        if not steps:
            steps = [{"center": 320.0, "fraction": 0.35}]
        return simulate_tga(
            steps=steps,
            rate_c_per_min=float(self.get_param("rate_c_per_min", 10.0)),
            t_min=float(self.get_param("t_min", 25.0)),
            t_max=float(self.get_param("t_max", 800.0)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        mass = np.asarray(spectrum.y, dtype=float)
        initial = float(mass[0]) if mass.size else 0.0
        final = float(mass[-1]) if mass.size else 0.0
        if initial > 0:
            loss = (initial - final) / initial * 100.0
        else:
            loss = 0.0
        table = Table(
            name="TGA summary",
            columns=["metric", "value"],
            rows=[
                ["initial_mass_pct", round(initial, 3)],
                ["final_mass_pct", round(final, 3)],
                ["total_loss_pct", round(loss, 3)],
            ],
        )
        lines = [
            f"TGA up to {float(self.get_param('t_max', 800.0)):.0f} °C",
            f"  Residual mass : {final:.2f}%",
            f"  Total loss    : {loss:.2f}%",
        ]
        return {"table": table, "text": Text(name="TGA", text="\n".join(lines))}


@register_node
class DMANode(InstrumentNode):
    """Dynamic mechanical analyser."""

    name = "DMA"
    category = "Instruments/Thermal"
    description = "动态力学分析仪：储能 / 损耗模量与 tan δ 随温度变化曲线。"
    version = "0.7.1"
    tags = ["instrument", "dma", "mechanical", "tan delta"]
    aliases = ["DMA"]
    icon = "DM"

    technique = "DMA"
    instrument = "virtual DMA"

    parameters = [
        ParameterSpec("glassy_modulus_mpa", "number", 2500.0, "玻璃态模量", unit="MPa", min=1.0),
        ParameterSpec("rubbery_modulus_mpa", "number", 20.0, "橡胶态模量", unit="MPa", min=0.01),
        ParameterSpec("glass_transition_c", "number", 110.0, "玻璃化温度", unit="°C"),
        ParameterSpec("width_c", "number", 18.0, "转变宽度", unit="°C", min=1.0),
        ParameterSpec("t_min", "number", 0.0, "起始温度", unit="°C"),
        ParameterSpec("t_max", "number", 220.0, "终止温度", unit="°C"),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="DMA")
        if existing is not None:
            return existing
        return simulate_dma(
            glassy_modulus_mpa=float(self.get_param("glassy_modulus_mpa", 2500.0)),
            rubbery_modulus_mpa=float(self.get_param("rubbery_modulus_mpa", 20.0)),
            glass_transition_c=float(self.get_param("glass_transition_c", 110.0)),
            width_c=float(self.get_param("width_c", 18.0)),
            t_min=float(self.get_param("t_min", 0.0)),
            t_max=float(self.get_param("t_max", 220.0)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        modulus = np.asarray(spectrum.y, dtype=float)
        table = Table(
            name="DMA summary",
            columns=["metric", "value"],
            rows=[
                ["E_glassy_MPa", round(float(np.max(modulus)) if modulus.size else 0.0, 3)],
                ["E_rubbery_MPa", round(float(np.min(modulus)) if modulus.size else 0.0, 3)],
                ["Tg_C", float(self.get_param("glass_transition_c", 110.0))],
            ],
        )
        lines = [
            "DMA temperature sweep",
            f"  Glassy modulus  : {float(np.max(modulus)) if modulus.size else 0.0:.1f} MPa",
            f"  Rubbery modulus : {float(np.min(modulus)) if modulus.size else 0.0:.1f} MPa",
            f"  Tg (set)        : {float(self.get_param('glass_transition_c', 110.0)):.1f} °C",
        ]
        return {"table": table, "text": Text(name="DMA", text="\n".join(lines))}
