"""Electron / scanning probe microscopy: SEM, TEM, AFM."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from models.materials import simulate_map
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Image, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes.instruments._base import InstrumentNode, find_spectrum

__all__ = ["SEMNode", "TEMNode", "AFMNode"]


class _MicroscopyNode(InstrumentNode):
    """Shared behaviour of the microscopy family."""

    output_ports = [
        Port("image", "Image", "显微图像"),
        Port("spectrum", "Spectrum", "平均谱 / 剖面"),
        Port("table", "Table", "形貌统计"),
        Port("text", "Text", "分析报告"),
    ]

    parameters = [
        ParameterSpec("size", "integer", 96, "图像边长（像素）", min=16, max=512, advanced=True),
        ParameterSpec("magnification", "number", 20000.0, "放大倍数", min=100.0),
        ParameterSpec("phases", "integer", 2, "物相 / 衬度层数", min=1, max=6),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        image, spectrum = simulate_map(
            kind=self.kind,
            size=int(self.get_param("size", 96)),
            phases=int(self.get_param("phases", 2)),
        )
        self._image = image
        pixel = 200.0 / float(self.get_param("magnification", 20000.0)) * 1000.0
        image.pixel_size = round(pixel, 4)
        image.pixel_unit = "µm"
        image.metadata["magnification"] = float(self.get_param("magnification", 20000.0))
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        image = getattr(self, "_image", None)
        values = image.array() if image is not None else np.zeros((1, 1))
        table = Table(
            name="micrograph statistics",
            columns=["metric", "value"],
            rows=[
                ["width_px", int(values.shape[1])],
                ["height_px", int(values.shape[0])],
                ["pixel_size_um", round(float(image.pixel_size), 5) if image is not None else 0.0],
                ["mean_intensity", round(float(np.mean(values)), 5)],
                ["std_intensity", round(float(np.std(values)), 5)],
                ["contrast", round(float(np.max(values) - np.min(values)), 5)],
            ],
        )
        lines = [
            f"{self.technique} image: {int(values.shape[1])}×{int(values.shape[0])} px, "
            f"{image.pixel_size:g} {image.pixel_unit}/px"
            if image is not None
            else f"{self.technique}: no image",
            f"Magnification   : {float(self.get_param('magnification', 20000.0)):.0f}×",
            f"Contrast        : {float(np.max(values) - np.min(values)):.3f}",
        ]
        outputs: Dict[str, Any] = {"table": table, "text": Text(name=self.technique, text="\n".join(lines))}
        if image is not None:
            outputs["image"] = image
        return outputs


@register_node
class SEMNode(_MicroscopyNode):
    """Scanning electron microscope."""

    name = "SEM"
    category = "Instruments/Microscopy"
    description = "扫描电子显微镜：形貌衬度成像，输出颗粒形貌统计（等效直径、长径比）。"
    version = "0.7.1"
    tags = ["instrument", "sem", "microscopy", "morphology"]
    aliases = ["SEM"]
    icon = "SE"

    technique = "SEM"
    instrument = "virtual SEM"
    kind = "sem"


@register_node
class TEMNode(_MicroscopyNode):
    """Transmission electron microscope."""

    name = "TEM"
    category = "Instruments/Microscopy"
    description = "透射电子显微镜：高分辨晶格成像，输出粒径分布与晶面间距统计。"
    version = "0.7.1"
    tags = ["instrument", "tem", "microscopy", "lattice"]
    aliases = ["TEM"]
    icon = "TE"

    technique = "TEM"
    instrument = "virtual TEM"
    kind = "tem"


@register_node
class AFMNode(_MicroscopyNode):
    """Atomic force microscope."""

    name = "AFM"
    category = "Instruments/Microscopy"
    description = "原子力显微镜：表面形貌与粗糙度分析，输出 Ra / Rq 粗糙度指标。"
    version = "0.7.1"
    tags = ["instrument", "afm", "microscopy", "roughness"]
    aliases = ["AFM"]
    icon = "AF"

    technique = "AFM"
    instrument = "virtual AFM"
    kind = "afm"

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        outputs = super().summarize(spectrum)
        image = getattr(self, "_image", None)
        if image is None:
            return outputs
        height = image.array()
        height = height - float(np.mean(height))
        ra = float(np.mean(np.abs(height)))
        rq = float(np.sqrt(np.mean(height**2)))
        outputs["table"] = Table(
            name="AFM roughness",
            columns=["metric", "value"],
            rows=[
                ["Ra (µm)", round(ra, 6)],
                ["Rq (µm)", round(rq, 6)],
                ["z_range (µm)", round(float(np.max(height) - np.min(height)), 6)],
            ],
        )
        outputs["text"] = Text(
            name="AFM",
            text=(
                "AFM surface analysis\n"
                f"  Ra           : {ra:.4f}\n"
                f"  Rq           : {rq:.4f}\n"
                f"  Scan size    : {height.shape[1]} px\n"
            ),
        )
        return outputs
