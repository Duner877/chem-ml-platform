"""量子化学节点分组。

ORCA、Gaussian、Psi4、CP2K 的分子性质计算。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.quantum_chemistry import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.quantum_chemistry.quantum import (
    ORCANode,
    GaussianNode,
    Psi4Node,
    CP2KNode,
)

__all__ = [
    "ORCANode",
    "GaussianNode",
    "Psi4Node",
    "CP2KNode",
]
