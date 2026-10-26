"""通用分析节点分组。

基线校正、平滑、寻峰、归一化、描述符与相似度。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.analysis import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.analysis.analysis import (
    BaselineCorrectionNode,
    SmoothingNode,
    PeakPickingNode,
    NormalizeNode,
    ResampleNode,
    SpectrumMathNode,
    MolecularDescriptorsNode,
    SimilarityNode,
    SubstructureSearchNode,
    FunctionalGroupNode,
)

__all__ = [
    "BaselineCorrectionNode",
    "SmoothingNode",
    "PeakPickingNode",
    "NormalizeNode",
    "ResampleNode",
    "SpectrumMathNode",
    "MolecularDescriptorsNode",
    "SimilarityNode",
    "SubstructureSearchNode",
    "FunctionalGroupNode",
]
