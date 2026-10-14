"""Surface / element specific techniques: XPS and XAS."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.materials import simulate_xps, simulate_xas
from models.spectra import XAS_K_EDGES
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes.instruments._base import (
    InstrumentNode,
    find_spectrum,
    resolve_composition,
    sample_items,
)

__all__ = ["XPSNode", "XASNode"]


@register_node
class XPSNode(InstrumentNode):
    """X-ray photoelectron spectrometer (survey scan)."""

    name = "XPS"
    category = "Instruments/Surface"
    description = "X 射线光电子能谱：按元素特征结合能生成 Survey 全谱，含 Shirley 型本底。"
    tags = ["instrument", "xps", "surface", "oxidation state"]
    aliases = ["XPS"]
    icon = "XP"

    technique = "XPS"
    instrument = "virtual XPS (Al Kα)"

    parameters = [
        ParameterSpec(
            "composition",
            "string",
            "",
            "元素组成，如 Fe:1, O:1.5（留空则取上游材料 / 分子）",
        ),
        ParameterSpec("energy_step", "number", 0.1, "能量步长", unit="eV", min=0.01, max=1.0, advanced=True),
        ParameterSpec("noise", "number", 0.01, "相对噪声水平", min=0.0, max=0.5, step=0.001),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="XPS")
        if existing is not None:
            return existing
        composition = resolve_composition(self, inputs)
        spectrum = simulate_xps(
            composition,
            energy_step=float(self.get_param("energy_step", 0.1)),
            noise=float(self.get_param("noise", 0.01)),
        )
        spectrum.technique = "XPS survey"
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        rows = []
        for peak in spectrum.peaks:
            rows.append([peak.assignment or peak.label, round(float(peak.x), 2), round(float(peak.y), 2)])
        table = Table(
            name="XPS peaks", columns=["level", "binding energy (eV)", "intensity"], rows=rows
        )
        total = sum(float(peak.y) for peak in spectrum.peaks) or 1.0
        per_element: Dict[str, float] = {}
        for peak in spectrum.peaks:
            label = peak.assignment or peak.label or "?"
            element = label.split()[0]
            per_element[element] = per_element.get(element, 0.0) + float(peak.y)
        lines = ["XPS surface composition (at.%):"]
        for element, value in sorted(per_element.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {element:<4} {value / total * 100:6.2f}%")
        return {"table": table, "text": Text(name="XPS", text="\n".join(lines))}


@register_node
class XASNode(InstrumentNode):
    """X-ray absorption spectrometer (XANES + EXAFS)."""

    name = "XAS"
    category = "Instruments/Surface"
    description = "X 射线吸收谱：吸收边 + 白线 + EXAFS 振荡，可用于价态与配位环境分析。"
    tags = ["instrument", "xas", "xanes", "exafs", "synchrotron"]
    aliases = ["XAS", "XANES"]
    icon = "XA"

    technique = "XAS"
    instrument = "virtual XAS beamline"

    parameters = [
        ParameterSpec("element", "string", "Fe", "吸收边元素"),
        ParameterSpec("edge", "enum", "K", "吸收边", options=["K", "L3", "L2"]),
        ParameterSpec(
            "oxidation_state", "number", 0.0, "氧化态（用于化学位移）", min=-4.0, max=8.0, step=0.5
        ),
        ParameterSpec("noise", "number", 0.004, "相对噪声水平", min=0.0, max=0.5, step=0.001),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="XAS")
        if existing is not None:
            return existing

        element = str(self.get_param("element", "Fe") or "").strip()
        if not element:
            # Fall back on the heaviest element of an upstream material.
            composition = resolve_composition(self, inputs)
            if composition:
                element = str(composition[-1]["element"])
        if not element:
            raise NodeInputError("XASNode: parameter 'element' is empty")

        spectrum = simulate_xas(
            element.capitalize(),
            edge=str(self.get_param("edge", "K")),
            oxidation_state=float(self.get_param("oxidation_state", 0.0)),
            noise=float(self.get_param("noise", 0.004)),
        )
        spectrum.technique = f"XAS ({self.get_param('edge', 'K')}-edge)"
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        energies = np.asarray(spectrum.x, dtype=float)
        mu = np.asarray(spectrum.y, dtype=float)
        edge_energy = float(energies[int(np.argmax(np.gradient(mu, energies)))]) if energies.size > 2 else 0.0
        table = Table(
            name="XAS metrics",
            columns=["metric", "value"],
            rows=[
                ["edge_energy_eV", round(edge_energy, 2)],
                ["max_mu", round(float(np.max(mu)) if mu.size else 0.0, 4)],
                ["points", int(energies.size)],
            ],
        )
        lines = [
            f"XAS {self.get_param('element', 'Fe')} {self.get_param('edge', 'K')}-edge",
            f"Edge position  : {edge_energy:.1f} eV",
            f"Oxidation state: {float(self.get_param('oxidation_state', 0.0)):+.1f}",
        ]
        return {"table": table, "text": Text(name="XAS", text="\n".join(lines))}
