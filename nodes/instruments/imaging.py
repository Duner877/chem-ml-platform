"""Chemical imaging: Raman mapping, FTIR imaging, hyperspectral imaging."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from models.materials import simulate_map
from workflow_engine.node_base import ParameterSpec
from workflow_engine.objects import Image, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes.instruments._base import InstrumentNode, find_spectrum

__all__ = ["RamanMappingNode", "FTIRImagingNode", "HyperspectralNode"]


class _ImagingNode(InstrumentNode):
    """Shared behaviour of the chemical imaging nodes."""

    output_ports = [
        Port("image", "Image", "化学成像图"),
        Port("spectrum", "Spectrum", "平均谱"),
        Port("table", "Table", "组分统计"),
        Port("text", "Text", "成像报告"),
    ]

    parameters = [
        ParameterSpec("size", "integer", 64, "图像边长（像素）", min=8, max=256),
        ParameterSpec("phases", "integer", 3, "组分数量", min=1, max=8),
        ParameterSpec("seed", "integer", 61, "随机种子", advanced=True),
    ]

    def measure(self, inputs: Dict[str, Any], ctx: Any = None) -> Optional[Spectrum]:
        image, spectrum = simulate_map(
            kind=self.kind,
            size=int(self.get_param("size", 64)),
            phases=int(self.get_param("phases", 3)),
            seed=int(self.get_param("seed", 61)),
        )
        self._image = image
        return spectrum

    def summarize(self, spectrum: Spectrum) -> Dict[str, Any]:
        image = getattr(self, "_image", None)
        values = image.array() if image is not None else np.zeros((1, 1))
        phases = int(self.get_param("phases", 3))
        counts = [
            int(np.sum(np.isclose(values, index / max(1.0, float(phases - 1)), atol=1e-6)))
            for index in range(phases)
        ]
        total = sum(counts) or 1
        rows = [
            [f"phase_{index}", count, round(count / total * 100.0, 2)]
            for index, count in enumerate(counts)
        ]
        table = Table(
            name="phase abundance", columns=["phase", "pixels", "area %"], rows=rows
        )
        lines = [
            f"{self.technique} imaging: {int(values.shape[1])}×{int(values.shape[0])} px, "
            f"{phases} components",
        ]
        for row in rows:
            lines.append(f"  {row[0]:<8} {row[2]:6.2f}%")
        outputs: Dict[str, Any] = {
            "table": table,
            "text": Text(name=self.technique, text="\n".join(lines)),
        }
        if image is not None:
            outputs["image"] = image
        return outputs


@register_node
class RamanMappingNode(_ImagingNode):
    """Raman chemical mapping."""

    name = "Raman Mapping"
    category = "Instruments/Imaging"
    description = "拉曼面扫成像：生成高光谱数据立方体并输出组分分布图与平均谱。"
    version = "0.7.1"
    tags = ["instrument", "imaging", "raman", "hyperspectral"]
    aliases = ["RamanMap"]
    icon = "RM"

    technique = "Raman mapping"
    instrument = "virtual Raman microscope"
    kind = "raman"


@register_node
class FTIRImagingNode(_ImagingNode):
    """FTIR chemical imaging."""

    name = "FTIR Imaging"
    category = "Instruments/Imaging"
    description = "红外化学成像：基于特征吸收带生成组分分布图与平均红外谱。"
    version = "0.7.1"
    tags = ["instrument", "imaging", "ftir", "infrared"]
    aliases = ["FTIRImage"]
    icon = "FI"

    technique = "FTIR imaging"
    instrument = "virtual FTIR imaging system"
    kind = "ftir"


@register_node
class HyperspectralNode(_ImagingNode):
    """Generic hyperspectral imaging."""

    name = "Hyperspectral Imaging"
    category = "Instruments/Imaging"
    description = "通用高光谱成像：匹配滤波生成组分丰度图与端元光谱。"
    version = "0.7.1"
    tags = ["instrument", "imaging", "hyperspectral", "unmixing"]
    aliases = ["HSI"]
    icon = "HS"

    technique = "Hyperspectral"
    instrument = "virtual hyperspectral camera"
    kind = "hyperspectral"
