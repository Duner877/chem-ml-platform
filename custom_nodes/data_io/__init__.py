"""数据输入输出节点分组。

谱图、表格、图像、分子与材料的文件读写。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.data_io import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.data_io.io import (
    SpectrumFileNode,
    TableFileNode,
    ImageFileNode,
    MoleculeInputNode,
    MaterialInputNode,
    TextInputNode,
    ExportNode,
)

__all__ = [
    "SpectrumFileNode",
    "TableFileNode",
    "ImageFileNode",
    "MoleculeInputNode",
    "MaterialInputNode",
    "TextInputNode",
    "ExportNode",
]
