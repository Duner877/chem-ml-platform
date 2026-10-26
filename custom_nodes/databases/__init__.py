"""数据库节点分组。

谱库、化学数据库与材料数据库的检索节点。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.databases import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.databases.chemical import (
    PubChemNode,
    ChEMBLNode,
    ZINCNode,
    PDBNode,
)
from custom_nodes.databases.materials_db import (
    MaterialsProjectNode,
    CODNode,
    ICSDNode,
    AFLOWNode,
)
from custom_nodes.databases.spectral import (
    MassBankNode,
    MoNANode,
    GNPSNode,
    HMDBNode,
    BMRBNode,
    NISTNode,
)

__all__ = [
    "PubChemNode",
    "ChEMBLNode",
    "ZINCNode",
    "PDBNode",
    "MaterialsProjectNode",
    "CODNode",
    "ICSDNode",
    "AFLOWNode",
    "MassBankNode",
    "MoNANode",
    "GNPSNode",
    "HMDBNode",
    "BMRBNode",
    "NISTNode",
]
