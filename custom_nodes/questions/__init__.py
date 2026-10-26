"""科学问题节点分组。

顶层科学问题节点：这是什么化合物、该合成什么材料。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.questions import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.questions.discovery import (
    MaterialDiscoveryNode,
)
from custom_nodes.questions.identification import (
    UnknownCompoundIdentificationNode,
)

__all__ = [
    "MaterialDiscoveryNode",
    "UnknownCompoundIdentificationNode",
]
