"""光谱节点分组。

紫外-可见、荧光、红外、拉曼、核磁共振，以及光谱成像与高光谱。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.spectroscopy import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.spectroscopy.electronic import (
    UVVisNode,
    FluorescenceNode,
)
from custom_nodes.spectroscopy.imaging import (
    RamanMappingNode,
    FTIRImagingNode,
    HyperspectralNode,
)
from custom_nodes.spectroscopy.nmr import (
    NMRNode,
)
from custom_nodes.spectroscopy.vibrational import (
    IRNode,
    RamanNode,
)

__all__ = [
    "UVVisNode",
    "FluorescenceNode",
    "RamanMappingNode",
    "FTIRImagingNode",
    "HyperspectralNode",
    "NMRNode",
    "IRNode",
    "RamanNode",
]
