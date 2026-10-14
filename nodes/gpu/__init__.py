"""GPU / PyTorch nodes (v0.7 -- spec section 7).

Nodes in this package report the **actual** execution device and never claim
GPU acceleration that did not happen.  When torch is missing they raise a
``NodeInputError`` carrying the ``DEPENDENCY_MISSING`` guidance; when a CUDA
device is requested but unavailable they raise with ``GPU_UNAVAILABLE``
guidance.  Both behaviours are covered by tests.
"""

from .gpu_nodes import (
    GpuDeviceInfoNode,
    InferenceBenchmarkNode,
    ModelInferenceNode,
    PyTorchTensorOpNode,
    torch_status,
)

__all__ = [
    "GpuDeviceInfoNode",
    "PyTorchTensorOpNode",
    "ModelInferenceNode",
    "InferenceBenchmarkNode",
    "torch_status",
]
