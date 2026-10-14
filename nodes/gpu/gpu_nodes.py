"""GPU / PyTorch execution nodes (v0.7 -- spec sections 7.1, 7.2)."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

__all__ = [
    "torch_status",
    "GpuDeviceInfoNode",
    "PyTorchTensorOpNode",
    "ModelInferenceNode",
    "InferenceBenchmarkNode",
]


def torch_status() -> Dict[str, Any]:
    """Honest PyTorch / CUDA probe (never raises)."""
    info: Dict[str, Any] = {
        "torch_installed": False,
        "torch_version": "",
        "cuda_available": False,
        "cuda_version": "",
        "gpus": [],
        "error": "",
    }
    try:
        import torch

        info["torch_installed"] = True
        info["torch_version"] = torch.__version__
        info["cuda_available"] = bool(torch.cuda.is_available())
        if info["cuda_available"]:
            info["cuda_version"] = str(getattr(torch.version, "cuda", "") or "")
            for index in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(index)
                info["gpus"].append(
                    {
                        "index": index,
                        "name": props.name,
                        "total_memory_gb": round(props.total_memory / 1024**3, 2),
                    }
                )
    except Exception as exc:  # broken installs surface as an error string
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _resolve_device(preferred: str, require_gpu: bool) -> tuple:
    """Return (torch module, device string, fallback_reason)."""
    status = torch_status()
    if not status["torch_installed"]:
        raise NodeInputError(
            "PyTorch 未安装（DEPENDENCY_MISSING）：pip install torch "
            "（或参考 requirements.txt 的 CPU 基础安装）"
        )
    import torch

    if preferred.startswith("cuda"):
        if not status["cuda_available"]:
            if require_gpu:
                raise NodeInputError(
                    "GPU_UNAVAILABLE：请求 CUDA 设备但 torch.cuda.is_available()=False。"
                    "请安装与本机驱动匹配的 CUDA 版 torch，或将参数 require_gpu 设为 false "
                    "以允许诚实的 CPU 回退。"
                )
            return torch, "cpu", "CUDA requested but unavailable -> honest CPU fallback"
        return torch, preferred, ""
    return torch, "cpu", ""


# --------------------------------------------------------------------------- #
@register_node
class GpuDeviceInfoNode(ScientificNode):
    """Report PyTorch / CUDA / GPU state (spec section 7.1)."""

    name = "GPU Device Info"
    category = "GPU"
    #: v0.7.1 task E/F: hardware capability is declared; when CUDA is absent the
    #: node reports the honest CPU fallback / unavailable state.
    capabilities = ["requires_gpu"]
    description = (
        "检测 PyTorch 版本、CUDA 可用性、GPU 名称与显存。"
        "GPU 不可用时如实报告原因，绝不虚报加速。"
    )
    tags = ["gpu", "cuda", "pytorch", "diagnostics"]
    icon = "GPU"
    deterministic = True

    input_ports: List[Port] = []
    output_ports = [
        Port("report", "Text", "GPU 环境报告（JSON 文本）"),
        Port("table", "Table", "每块 GPU 一行的显存表"),
    ]

    parameters = [
        ParameterSpec(
            "include_memory_snapshot", "boolean", True,
            "包含当前显存占用快照（需要 CUDA 可用）",
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        import json

        status = torch_status()
        self.log(
            f"torch_installed={status['torch_installed']} "
            f"cuda_available={status['cuda_available']}"
        )
        if status["torch_installed"] and status["cuda_available"]:
            import torch

            if self.get_param("include_memory_snapshot"):
                for gpu in status["gpus"]:
                    index = gpu["index"]
                    with torch.cuda.device(index):
                        free, total = torch.cuda.mem_get_info(index)
                    gpu["free_memory_gb"] = round(free / 1024**3, 2)
                    gpu["total_memory_gb"] = round(total / 1024**3, 2)
        else:
            if not status["torch_installed"]:
                self.log("[warn] PyTorch not installed")
            else:
                self.log("[warn] CUDA unavailable on this machine")

        self.last_device = "cuda" if status["cuda_available"] else "cpu"
        self.last_provider = "pytorch"
        self.last_model = status["torch_version"]
        report_text = json.dumps(status, ensure_ascii=False, indent=2)
        rows = [
            [
                str(g.get("index", "")),
                str(g.get("name", "")),
                str(g.get("total_memory_gb", "")),
                str(g.get("free_memory_gb", "")),
            ]
            for g in status["gpus"]
        ]
        return {
            "report": Text(text=report_text, name="GPU status"),
            "table": Table(
                columns=["index", "name", "total_memory_gb", "free_memory_gb"],
                rows=rows,
                name="GPU memory",
            ),
        }


@register_node
class PyTorchTensorOpNode(ScientificNode):
    """Run a small tensor op on the selected device and report where it ran."""

    name = "PyTorch Tensor Operation"
    category = "GPU"
    #: v0.7.1 task E/F: hardware capability is declared; when CUDA is absent the
    #: node reports the honest CPU fallback / unavailable state.
    capabilities = ["requires_gpu"]
    description = (
        "在指定设备上执行张量运算（matmul / add / sigmoid），"
        "输出包含实际执行设备标注。"
    )
    tags = ["gpu", "tensor", "pytorch"]
    icon = "T#"
    deterministic = True
    cacheable = False

    input_ports: List[Port] = []
    output_ports = [Port("result", "Text", "运算结果与设备标注（JSON）")]

    parameters = [
        ParameterSpec("size", "integer", 256, "方阵边长", min=2, max=8192),
        ParameterSpec("op", "enum", "matmul", "运算类型", options=["matmul", "add", "sigmoid"]),
        ParameterSpec("device", "enum", "cpu", "首选设备", options=["cpu", "cuda", "cuda:0"]),
        ParameterSpec("require_gpu", "boolean", False, "GPU 不可用时是否报错（false=诚实 CPU 回退）"),
        ParameterSpec("seed", "integer", 42, "随机种子"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        import json

        torch, device, fallback = _resolve_device(
            str(self.get_param("device", "cpu")), bool(self.get_param("require_gpu"))
        )
        if fallback:
            self.log(f"[warn] {fallback}")
            self.fallback_used = True
            self.fallback_reason = fallback
        seed = int(self.get_param("seed") or 42)
        torch.manual_seed(seed)
        self.random_seed = seed
        n = int(self.get_param("size") or 256)
        a = torch.randn(n, n, device=device)
        b = torch.randn(n, n, device=device)
        op = str(self.get_param("op") or "matmul")
        if op == "matmul":
            result = a @ b
        elif op == "add":
            result = a + b
        else:
            result = torch.sigmoid(a)
        checksum = float(result.float().sum().item())
        self.last_device = str(result.device)
        self.last_provider = "pytorch"
        self.last_model = torch.__version__
        return {
            "result": Text(
                text=json.dumps(
                    {
                        "op": op,
                        "size": n,
                        "device": str(result.device),
                        "fallback_used": bool(fallback),
                        "seed": seed,
                        "checksum": round(checksum, 4),
                        "deterministic": True,
                    },
                    ensure_ascii=False,
                ),
                name="tensor op result",
            )
        }


@register_node
class ModelInferenceNode(ScientificNode):
    """Load a torch.nn.Module definition and run a forward pass.

    The model is created from a registered factory (currently the built-in
    ``mlp`` factory); weights are randomly initialised with the configured
    seed so runs are reproducible.  This node deliberately does NOT pretend
    to load user checkpoints yet -- checkpoint loading arrives with the
    workspace model store.
    """

    name = "Model Inference"
    category = "GPU"
    #: v0.7.1 task E/F: hardware capability is declared; when CUDA is absent the
    #: node reports the honest CPU fallback / unavailable state.
    capabilities = ["requires_gpu"]
    description = "在 CPU/GPU 上执行一个小型 MLP 前向推理，标注实际设备与耗时。"
    tags = ["gpu", "inference", "mlp", "pytorch"]
    icon = "MI"
    deterministic = True
    cacheable = False

    input_ports: List[Port] = []
    output_ports = [Port("result", "Text", "推理结果摘要（JSON）")]

    parameters = [
        ParameterSpec("batch_size", "integer", 32, "批大小", min=1, max=4096),
        ParameterSpec("input_dim", "integer", 64, "输入维度", min=1, max=4096),
        ParameterSpec("hidden_dim", "integer", 128, "隐藏层宽度", min=1, max=4096),
        ParameterSpec("device", "enum", "cpu", "首选设备", options=["cpu", "cuda", "cuda:0"]),
        ParameterSpec("require_gpu", "boolean", False, "GPU 不可用时是否报错"),
        ParameterSpec("seed", "integer", 42, "随机种子"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        import json

        torch, device, fallback = _resolve_device(
            str(self.get_param("device", "cpu")), bool(self.get_param("require_gpu"))
        )
        if fallback:
            self.log(f"[warn] {fallback}")
            self.fallback_used = True
            self.fallback_reason = fallback
        seed = int(self.get_param("seed") or 42)
        torch.manual_seed(seed)
        self.random_seed = seed

        batch = int(self.get_param("batch_size") or 32)
        in_dim = int(self.get_param("input_dim") or 64)
        hidden = int(self.get_param("hidden_dim") or 128)

        model = torch.nn.Sequential(
            torch.nn.Linear(in_dim, hidden),
            torch.nn.ReLU(),
            torch.nn.Linear(hidden, 1),
        ).to(device)
        x = torch.randn(batch, in_dim, device=device)
        started = time.perf_counter()
        with torch.no_grad():
            y = model(x)
        duration_ms = (time.perf_counter() - started) * 1000
        self.last_device = str(y.device)
        self.last_provider = "pytorch"
        self.last_model = f"mlp({in_dim}->{hidden}->1)"
        return {
            "result": Text(
                text=json.dumps(
                    {
                        "model": f"mlp({in_dim}->{hidden}->1)",
                        "batch_size": batch,
                        "output_shape": list(y.shape),
                        "device": str(y.device),
                        "fallback_used": bool(fallback),
                        "seed": seed,
                        "forward_ms": round(duration_ms, 3),
                        "output_mean": round(float(y.mean().item()), 6),
                    },
                    ensure_ascii=False,
                ),
                name="inference result",
            )
        }


@register_node
class InferenceBenchmarkNode(ScientificNode):
    """Measure forward-pass throughput on the selected device."""

    name = "Inference Benchmark"
    category = "GPU"
    #: v0.7.1 task E/F: hardware capability is declared; when CUDA is absent the
    #: node reports the honest CPU fallback / unavailable state.
    capabilities = ["requires_gpu"]
    description = "对指定设备进行前向吞吐基准测试（真实计时，不做假数据）。"
    tags = ["gpu", "benchmark", "pytorch"]
    icon = "BM"
    deterministic = False  # wall-clock timing is inherently non-deterministic
    cacheable = False

    input_ports: List[Port] = []
    output_ports = [Port("result", "Table", "每行一次计时测量的结果表")]

    parameters = [
        ParameterSpec("batch_size", "integer", 64, "批大小", min=1, max=4096),
        ParameterSpec("input_dim", "integer", 128, "输入维度", min=1, max=4096),
        ParameterSpec("repeats", "integer", 10, "计时次数", min=1, max=1000),
        ParameterSpec("warmup", "integer", 2, "预热次数（不计入）", min=0, max=100),
        ParameterSpec("device", "enum", "cpu", "首选设备", options=["cpu", "cuda", "cuda:0"]),
        ParameterSpec("require_gpu", "boolean", False, "GPU 不可用时是否报错"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        torch, device, fallback = _resolve_device(
            str(self.get_param("device", "cpu")), bool(self.get_param("require_gpu"))
        )
        if fallback:
            self.log(f"[warn] {fallback}")
            self.fallback_used = True
            self.fallback_reason = fallback
        torch.manual_seed(42)
        batch = int(self.get_param("batch_size") or 64)
        in_dim = int(self.get_param("input_dim") or 128)
        repeats = int(self.get_param("repeats") or 10)
        warmup = int(self.get_param("warmup") or 2)

        model = torch.nn.Sequential(
            torch.nn.Linear(in_dim, 256), torch.nn.ReLU(), torch.nn.Linear(256, 1)
        ).to(device)
        x = torch.randn(batch, in_dim, device=device)

        def one_pass() -> float:
            started = time.perf_counter()
            with torch.no_grad():
                model(x)
            if device.startswith("cuda"):
                torch.cuda.synchronize(device)
            return (time.perf_counter() - started) * 1000

        for _ in range(warmup):
            one_pass()
        rows = []
        for i in range(repeats):
            duration = one_pass()
            rows.append([str(i + 1), f"{duration:.3f}", f"{batch / (duration / 1000):.0f}"])
        self.last_device = device
        self.last_provider = "pytorch"
        self.last_model = f"mlp({in_dim}->256->1)"
        return {
            "result": Table(
                columns=["run", "duration_ms", "throughput_samples_per_s"],
                rows=rows,
                name="benchmark",
            )
        }
