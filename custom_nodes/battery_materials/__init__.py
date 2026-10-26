"""电池材料节点分组。

硬碳预脱溶剂、双 SEI 能量学与电解液老化。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.battery_materials import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.battery_materials.desolvation import (
    DesolvationSieveNode,
    ElectrolyteAgingNode,
    DoubleSEIEnergeticsNode,
    PreDesolvationMechanismNode,
)

__all__ = [
    "DesolvationSieveNode",
    "ElectrolyteAgingNode",
    "DoubleSEIEnergeticsNode",
    "PreDesolvationMechanismNode",
]
