"""共享基础设施节点分组。

节点基类与厂商谱图适配器，不直接提供节点。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes._shared import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes._shared import (
    _base,
)
from custom_nodes._shared import (
    vendor_adapters,
)
from custom_nodes._shared import _base  # noqa: F401
from custom_nodes._shared import vendor_adapters  # noqa: F401

__all__ = [
    "_base",
    "vendor_adapters",
]
