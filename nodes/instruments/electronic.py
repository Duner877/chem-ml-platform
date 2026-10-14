"""Electronic spectroscopy: UV-Vis absorption and fluorescence."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.spectra import predict_fluorescence, predict_uvvis
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.registry import register_node

from nodes._helpers import ensure_peaks, peaks_to_table
from nodes.instruments._base import (
    InstrumentNode,
    find_spectrum,
    resolve_smiles,
    sample_items,
)

__all__ = ["UVVisNode", "FluorescenceNode"]


@register_node
class UVVisNode(InstrumentNode):
    """Ultraviolet-visible absorption spectrometer."""

    name = "UV-Vis"
    category = "Instruments/Electronic"
    description = "紫外-可见吸收光谱仪：基于 Woodward-Fieser 规则估算最大吸收波长 λmax。"
    tags = ["instrument", "uvvis", "absorption", "woodward-fieser"]
    aliases = ["UVVis", "UV-Vis"]
    icon = "UV"

    technique = "UV-Vis"
    instrument = "virtual UV-Vis spectrometer"

    parameters = [
        ParameterSpec("smiles", "string", "", "待测物 SMILES"),
        ParameterSpec("path_length_cm", "number", 1.0, "光程", unit="cm", min=0.01, max=10.0),
        ParameterSpec("points", "integer", 400, "谱图采样点数", min=100, max=4000, advanced=True),
        ParameterSpec("noise", "number", 0.002, "相对噪声水平", min=0.0, max=0.5, step=0.001),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        spectrum = find_spectrum(sample_items(inputs), mode="UV-Vis")
        if spectrum is not None:
            return spectrum
        smiles = resolve_smiles(self, inputs)
        if not smiles:
            raise NodeInputError("UVVisNode: connect a molecule or set the 'smiles' parameter")
        spectrum = predict_uvvis(
            smiles,
            points=int(self.get_param("points", 400)),
            noise=float(self.get_param("noise", 0.002)),
        )
        spectrum.mode = "UV-Vis"
        spectrum.metadata["smiles"] = smiles
        ensure_peaks(spectrum, prominence=0.05)
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        highest = spectrum.max_peak()
        table = peaks_to_table(spectrum, limit=20, name="UV-Vis λmax")
        lines = [f"UV-Vis: {len(spectrum.peaks)} absorption band(s)"]
        if highest is not None:
            lines.append(f"λmax = {highest.x:.1f} nm (rel. {float(highest.y):.2f})")
        return {"table": table, "text": Text(name="UV-Vis", text="\n".join(lines))}


@register_node
class FluorescenceNode(InstrumentNode):
    """Steady state fluorescence spectrometer."""

    name = "Fluorescence"
    category = "Instruments/Electronic"
    description = "荧光光谱仪：基于镜像规则与 Stokes 位移生成激发 / 发射谱。"
    tags = ["instrument", "fluorescence", "emission", "stokes"]
    aliases = ["Fluorescence", "FL"]
    icon = "FL"

    technique = "Fluorescence"
    instrument = "virtual fluorescence spectrometer"

    parameters = [
        ParameterSpec("smiles", "string", "", "待测物 SMILES"),
        ParameterSpec("excitation_nm", "number", 260.0, "激发波长", unit="nm", min=200.0, max=900.0),
        ParameterSpec(
            "stokes_shift_nm", "number", 70.0, "Stokes 位移", unit="nm", min=0.0, max=400.0
        ),
        ParameterSpec("points", "integer", 400, "谱图采样点数", min=100, max=4000, advanced=True),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        spectrum = find_spectrum(sample_items(inputs), mode="Fluorescence")
        if spectrum is not None:
            return spectrum
        smiles = resolve_smiles(self, inputs)
        if not smiles:
            raise NodeInputError(
                "FluorescenceNode: connect a molecule or set the 'smiles' parameter"
            )
        spectrum = predict_fluorescence(
            smiles,
            excitation_nm=float(self.get_param("excitation_nm", 260.0)),
            stokes_shift_nm=float(self.get_param("stokes_shift_nm", 70.0)),
            points=int(self.get_param("points", 400)),
        )
        spectrum.mode = "Fluorescence"
        spectrum.metadata["smiles"] = smiles
        ensure_peaks(spectrum, prominence=0.05)
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        emission = spectrum.max_peak()
        excitation = float(self.get_param("excitation_nm", 260.0))
        table = peaks_to_table(spectrum, limit=10, name="emission bands")
        lines = [
            f"Excitation     : {excitation:.1f} nm",
            f"Emission max   : {emission.x:.1f} nm" if emission else "Emission max   : n/a",
            f"Stokes shift   : {float(self.get_param('stokes_shift_nm', 70.0)):.1f} nm",
        ]
        return {"table": table, "text": Text(name="Fluorescence", text="\n".join(lines))}
