"""Nuclear magnetic resonance instrument."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from models.spectra import predict_nmr
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes._helpers import ensure_peaks, records_to_table
from nodes.instruments._base import (
    InstrumentNode,
    find_spectrum,
    resolve_smiles,
    sample_items,
)

__all__ = ["NMRNode"]

NUCLEI = ["1H", "13C", "19F", "31P"]


@register_node
class NMRNode(InstrumentNode):
    """Nuclear magnetic resonance spectrometer.

    Accepts Bruker directories, JCAMP-DX files or FID data through the generic
    :func:`~workflow_engine.parsers.load_spectra` entry point; when no spectrum
    is connected the chemical shift table of :func:`models.spectra.predict_nmr`
    simulates the experiment from a SMILES.
    """

    name = "NMR Spectrometer"
    category = "Instruments/NMR"
    description = (
        "核磁共振波谱仪：支持 FID / JCAMP-DX / Bruker 数据读取，"
        "输出化学位移、峰列表、积分与二维谱。"
    )
    tags = ["instrument", "nmr", "fid", "bruker", "jcamp"]
    aliases = ["NMR"]
    icon = "NM"

    technique = "NMR"
    instrument = "virtual NMR spectrometer"

    parameters = [
        ParameterSpec("smiles", "string", "", "待测物 SMILES"),
        ParameterSpec("nucleus", "enum", "1H", "观测核", options=NUCLEI),
        ParameterSpec(
            "frequency_mhz", "number", 400.13, "谱仪频率", unit="MHz", min=30.0, max=1200.0
        ),
        ParameterSpec("solvent", "enum", "CDCl3", "氘代溶剂", options=["CDCl3", "DMSO-d6", "D2O", "CD3OD", "C6D6"]),
        ParameterSpec("points", "integer", 16384, "FID 采样点数", min=1024, max=131072, advanced=True),
        ParameterSpec(
            "line_broadening", "number", 1.0, "线宽因子", unit="Hz", min=0.0, max=20.0, step=0.1
        ),
        ParameterSpec("pick_peaks", "boolean", True, "自动峰检测"),
        ParameterSpec("prominence", "number", 0.02, "峰检测 prominence", min=0.0, max=1.0, step=0.001),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        existing = find_spectrum(sample_items(inputs), mode="NMR")
        if existing is not None:
            spectrum = existing
            spectrum.metadata.setdefault("origin", "upstream spectrum")
        else:
            smiles = resolve_smiles(self, inputs)
            if not smiles:
                raise NodeInputError(
                    "NMRNode: connect a molecule or set the 'smiles' parameter"
                )
            nucleus = str(self.get_param("nucleus", "1H"))
            spectrum = predict_nmr(
                smiles,
                nucleus=nucleus,
                frequency_mhz=float(self.get_param("frequency_mhz", 400.13)),
                points=int(self.get_param("points", 16384)),
                line_broadening=float(self.get_param("line_broadening", 1.0)),
            )
            spectrum.metadata["smiles"] = smiles
            spectrum.metadata["solvent"] = str(self.get_param("solvent", "CDCl3"))

        spectrum.mode = "NMR"
        if bool(self.get_param("pick_peaks", True)):
            ensure_peaks(spectrum, prominence=float(self.get_param("prominence", 0.02)))
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        nucleus = str(self.get_param("nucleus", "1H"))
        unit = "ppm" if nucleus != "19F" else "ppm"
        rows = []
        for peak in sorted(spectrum.peaks, key=lambda item: -float(item.x)):
            rows.append(
                [
                    round(float(peak.x), 3),
                    round(float(peak.intensity or peak.y), 3),
                    peak.assignment or peak.label,
                ]
            )
        table = Table(
            name=f"{nucleus} NMR peaks",
            columns=[f"shift ({unit})", "integral / intensity", "assignment"],
            rows=rows[:60],
        )
        lines = [
            f"{nucleus} NMR at {float(self.get_param('frequency_mhz', 400.13)):.2f} MHz "
            f"in {self.get_param('solvent', 'CDCl3')}",
            f"{len(rows)} signals:",
        ]
        for row in rows[:12]:
            lines.append(f"  δ {row[0]:>7.3f}  ({row[1]:>7.3f})  {row[2]}")
        return {"table": table, "text": Text(name=f"{nucleus} NMR", text="\n".join(lines))}
