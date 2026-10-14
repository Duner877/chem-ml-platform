"""Vibrational spectroscopy: IR and Raman."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.spectra import IR_BANDS, RAMAN_BANDS, predict_ir, predict_raman
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Peak, Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes._helpers import ensure_peaks
from nodes.instruments._base import (
    InstrumentNode,
    find_spectrum,
    resolve_smiles,
    sample_items,
)

__all__ = ["IRNode", "RamanNode"]


def _assign(spectrum: Spectrum, table: Dict[str, List], tolerance: float) -> Spectrum:
    """Assign the detected peaks to the closest known group frequency."""
    assigned: List[Peak] = []
    for peak in spectrum.peaks:
        best_label = ""
        best_distance = float("inf")
        for group, bands in table.items():
            for center, _intensity, label in bands:
                distance = abs(float(center) - float(peak.x))
                if distance < best_distance:
                    best_distance = distance
                    best_label = label
        peak.assignment = best_label if best_distance <= tolerance else "unassigned"
        assigned.append(peak)
    spectrum.peaks = assigned
    return spectrum


class _VibrationalNode(InstrumentNode):
    """Shared behaviour of IR and Raman."""

    parameters = [
        ParameterSpec("smiles", "string", "", "待测物 SMILES"),
        ParameterSpec("points", "integer", 1800, "谱图采样点数", min=400, max=20000, advanced=True),
        ParameterSpec("noise", "number", 0.004, "相对噪声水平", min=0.0, max=0.5, step=0.001),
        ParameterSpec("pick_peaks", "boolean", True, "自动峰检测"),
        ParameterSpec("prominence", "number", 0.03, "峰检测 prominence", min=0.0, max=1.0, step=0.001),
        ParameterSpec("tolerance", "number", 40.0, "谱带指认容差", unit="cm⁻¹", min=1.0, max=200.0),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode=self.technique)
        if existing is not None:
            spectrum = existing
        else:
            smiles = resolve_smiles(self, inputs)
            if not smiles:
                raise NodeInputError(
                    f"{self.node_type()}: connect a molecule or set the 'smiles' parameter"
            )
            spectrum = self._predict(smiles)
            spectrum.metadata["smiles"] = smiles
        if bool(self.get_param("pick_peaks", True)):
            ensure_peaks(spectrum, prominence=float(self.get_param("prominence", 0.03)))
        return _assign(spectrum, self._band_table, float(self.get_param("tolerance", 40.0)))

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        rows = [
            [
                round(float(peak.x), 1),
                round(float(peak.intensity or peak.y), 2),
                peak.assignment or peak.label,
            ]
            for peak in sorted(spectrum.peaks, key=lambda item: -float(item.x))
        ]
        table = Table(
            name=f"{self.technique} bands",
            columns=["wavenumber (cm⁻¹)", "intensity", "assignment"],
            rows=rows[:60],
        )
        lines = [f"{self.technique} spectrum: {len(rows)} diagnostic bands"]
        for row in rows[:12]:
            lines.append(f"  {row[0]:>7.1f} cm⁻¹  ({row[1]:>6.2f})  {row[2]}")
        return {"table": table, "text": Text(name=self.technique, text="\n".join(lines))}


@register_node
class IRNode(_VibrationalNode):
    """Fourier transform infrared spectrometer."""

    name = "FTIR"
    category = "Instruments/Vibrational"
    description = "傅里叶变换红外光谱仪：由官能团特征频率预测红外吸收谱并完成谱带指认。"
    tags = ["instrument", "ir", "ftir", "vibrational"]
    aliases = ["IR", "FTIR"]
    icon = "IR"

    technique = "IR"
    instrument = "virtual FTIR spectrometer"
    _band_table = IR_BANDS

    def _predict(self, smiles: str) -> Spectrum:
        return predict_ir(
            smiles,
            points=int(self.get_param("points", 1800)),
            noise=float(self.get_param("noise", 0.004)),
        )


@register_node
class RamanNode(_VibrationalNode):
    """Raman spectrometer."""

    name = "Raman"
    category = "Instruments/Vibrational"
    description = "拉曼光谱仪：预测拉曼位移谱（芳香环呼吸振动等强峰）并完成谱带指认。"
    tags = ["instrument", "raman", "vibrational"]
    aliases = ["Raman"]
    icon = "RA"

    technique = "Raman"
    instrument = "virtual Raman spectrometer"
    _band_table = RAMAN_BANDS

    def _predict(self, smiles: str) -> Spectrum:
        return predict_raman(
            smiles,
            points=int(self.get_param("points", 1800)),
            noise=float(self.get_param("noise", 0.004)),
        )
