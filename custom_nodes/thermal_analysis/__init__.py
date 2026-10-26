"""热分析节点分组。

热重、差示扫描量热、动态力学分析。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.thermal_analysis import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.thermal_analysis.thermal import (
    DSCNode,
    TGANode,
    DMANode,
)

__all__ = [
    "DSCNode",
    "TGANode",
    "DMANode",
]
