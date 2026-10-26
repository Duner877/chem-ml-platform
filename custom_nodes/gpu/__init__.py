"""GPU 计算节点分组。

PyTorch 张量运算、模型推理与 GPU 设备探测。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.gpu import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.gpu.gpu_nodes import (
    GpuDeviceInfoNode,
    PyTorchTensorOpNode,
    ModelInferenceNode,
    InferenceBenchmarkNode,
)

__all__ = [
    "GpuDeviceInfoNode",
    "PyTorchTensorOpNode",
    "ModelInferenceNode",
    "InferenceBenchmarkNode",
]
