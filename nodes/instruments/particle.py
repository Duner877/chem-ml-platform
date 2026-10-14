"""Particle and porosity characterisation: DLS and BET."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.materials import fit_bet, simulate_bet, simulate_dls
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes._helpers import ensure_peaks
from nodes.instruments._base import InstrumentNode, find_spectrum, sample_items

__all__ = ["DLSNode", "BETNode"]


@register_node
class DLSNode(InstrumentNode):
    """Dynamic light scattering particle sizer."""

    name = "DLS"
    category = "Instruments/Particle"
    description = "动态光散射粒度仪：基于累积量法输出粒径分布、Z-average 与 PDI。"
    tags = ["instrument", "dls", "particle size", "pdi"]
    aliases = ["DLS"]
    icon = "DL"

    technique = "DLS"
    instrument = "virtual DLS analyser"

    parameters = [
        ParameterSpec("mean_diameter_nm", "number", 120.0, "平均粒径", unit="nm", min=1.0),
        ParameterSpec("polydispersity", "number", 0.15, "多分散指数 PDI", min=0.0, max=1.0, step=0.01),
        ParameterSpec("temperature_c", "number", 25.0, "温度", unit="°C"),
        ParameterSpec("viscosity_cp", "number", 0.89, "粘度", unit="cP", min=0.1),
        ParameterSpec("refractive_index", "number", 1.33, "折射率", min=1.0),
        ParameterSpec("wavelength_nm", "number", 633.0, "激光波长", unit="nm"),
        ParameterSpec("points", "integer", 160, "分布采样点数", min=20, max=1000, advanced=True),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="DLS")
        if existing is not None:
            return existing
        return simulate_dls(
            mean_diameter_nm=float(self.get_param("mean_diameter_nm", 120.0)),
            polydispersity=float(self.get_param("polydispersity", 0.15)),
            temperature_c=float(self.get_param("temperature_c", 25.0)),
            viscosity_cp=float(self.get_param("viscosity_cp", 0.89)),
            refractive_index=float(self.get_param("refractive_index", 1.33)),
            wavelength_nm=float(self.get_param("wavelength_nm", 633.0)),
            points=int(self.get_param("points", 160)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        tau = np.asarray(spectrum.x, dtype=float)
        g1 = np.asarray(spectrum.y, dtype=float)
        gamma_bar = float(spectrum.metadata.get("gamma_bar_per_s", 0.0))
        z_average = float(spectrum.metadata.get("z_average_nm", 0.0))
        pdi = float(spectrum.metadata.get("pdi", 0.0))

        # half decay time of the autocorrelation function
        half = float(np.interp(0.5, g1[::-1], tau[::-1])) if g1.size > 2 else 0.0

        table = Table(
            name="DLS summary",
            columns=["metric", "value"],
            rows=[
                ["Z-average_nm", round(z_average, 3)],
                ["PDI", round(pdi, 4)],
                ["Gamma_bar_1_per_s", round(gamma_bar, 3)],
                ["tau_half_s", round(half, 8)],
                ["temperature_C", float(self.get_param("temperature_c", 25.0))],
                ["points", int(tau.size)],
            ],
        )
        lines = [
            f"DLS at {float(self.get_param('temperature_c', 25.0)):.1f} °C, "
            f"λ = {float(self.get_param('wavelength_nm', 633.0)):.0f} nm",
            f"  Z-average (cumulant) : {z_average:.1f} nm",
            f"  PDI                  : {pdi:.3f}",
            f"  Γ̄                    : {gamma_bar:.2f} s⁻¹",
            f"  τ½                    : {half:.2e} s",
        ]
        return {"table": table, "text": Text(name="DLS", text="\n".join(lines))}


@register_node
class BETNode(InstrumentNode):
    """Nitrogen adsorption porosimeter with BET surface area analysis."""

    name = "BET Surface Area"
    category = "Instruments/Particle"
    description = "氮气吸附-脱附仪：BET 比表面积与孔容分析，输出 BET 线性拟合结果。"
    tags = ["instrument", "bet", "surface area", "porosity"]
    aliases = ["BET"]
    icon = "BT"

    technique = "BET"
    instrument = "virtual gas sorption analyser"

    parameters = [
        ParameterSpec(
            "specific_surface_area", "number", 120.0, "理论比表面积", unit="m²/g", min=0.01
        ),
        ParameterSpec(
            "monolayer_capacity", "number", 25.0, "单层吸附量", unit="cm³/g STP", min=0.01
        ),
        ParameterSpec("c_constant", "number", 120.0, "BET C 常数", min=1.0),
        ParameterSpec("points", "integer", 60, "等温线采样点数", min=10, max=300),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="BET")
        if existing is not None:
            return existing
        return simulate_bet(
            specific_surface_area=float(self.get_param("specific_surface_area", 120.0)),
            monolayer_capacity=float(self.get_param("monolayer_capacity", 25.0)),
            c_constant=float(self.get_param("c_constant", 120.0)),
            points=int(self.get_param("points", 60)),
        )

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        pressure = np.asarray(spectrum.x, dtype=float)
        volume = np.asarray(spectrum.y, dtype=float)
        fit = fit_bet(pressure, volume)
        table = Table(
            name="BET fit",
            columns=["metric", "value"],
            rows=[[key, value] for key, value in fit.items()],
        )
        lines = [
            "BET surface area analysis",
            f"  Slope    : {fit.get('slope', 0.0):.5f}",
            f"  Intercept: {fit.get('intercept', 0.0):.5f}",
            f"  Vm       : {fit.get('monolayer_capacity', 0.0):.3f} cm³/g",
            f"  C        : {fit.get('c_constant', 0.0):.2f}",
            f"  R²       : {fit.get('r_squared', 0.0):.4f}",
        ]
        return {"table": table, "text": Text(name="BET", text="\n".join(lines))}
