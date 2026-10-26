"""质谱节点分组。

液相 / 气相 / 元素 / 飞行时间质谱，以及碎片化路径解析。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.mass_spectrometry import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.mass_spectrometry.fragmentation import (
    FragmentationPathwayNode,
)
from custom_nodes.mass_spectrometry.mass_spec_core import (
    VendorSpectrumNode,
    ProfileCentroidNode,
)
from custom_nodes.mass_spectrometry.ms import (
    LCMSNode,
    GCMSNode,
    MALDINode,
    ICPMSNode,
)

__all__ = [
    "FragmentationPathwayNode",
    "VendorSpectrumNode",
    "ProfileCentroidNode",
    "LCMSNode",
    "GCMSNode",
    "MALDINode",
    "ICPMSNode",
]
