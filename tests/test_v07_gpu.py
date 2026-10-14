"""v0.7 Phase E tests -- GPU / PyTorch nodes (spec sections 7.1, 7.2, 22-F)."""

from __future__ import annotations

import json

import pytest

from nodes.gpu import (
    GpuDeviceInfoNode,
    InferenceBenchmarkNode,
    ModelInferenceNode,
    PyTorchTensorOpNode,
    torch_status,
)
from workflow_engine.objects import Table, Text

try:
    import torch  # noqa: F401

    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

pytestmark = pytest.mark.skipif(not HAS_TORCH, reason="torch not installed (CPU/GPU check requires it)")


class TestTorchStatus:
    def test_status_shape(self):
        status = torch_status()
        assert status["torch_installed"] is True
        assert status["torch_version"]
        assert isinstance(status["cuda_available"], bool)
        # On this CPU-only machine cuda must be False; on CUDA machines it
        # must list real GPUs.  Either way the report is honest.
        if status["cuda_available"]:
            assert status["gpus"]
        else:
            assert status["gpus"] == []


class TestGpuDeviceInfo:
    def test_report_is_json_and_honest(self):
        node = GpuDeviceInfoNode(node_id="gpu1")
        outputs = node.process({}, ctx=None)
        report = json.loads(outputs["report"].text)
        assert report["torch_installed"] is True
        assert "cuda_available" in report
        table = outputs["table"]
        assert isinstance(table, Table)


class TestTensorOp:
    def test_matmul_deterministic_by_seed(self):
        def run(seed: int) -> float:
            node = PyTorchTensorOpNode(node_id="t", params={"size": 16, "seed": seed, "op": "matmul"})
            result = json.loads(node.process({}, ctx=None)["result"].text)
            assert result["device"] in {"cpu"} or result["device"].startswith("cuda")
            assert result["deterministic"] is True
            assert result["seed"] == seed
            return result["checksum"]

        assert run(42) == run(42)

    def test_cpu_fallback_flagged_when_cuda_missing(self):
        status = torch_status()
        node = PyTorchTensorOpNode(
            node_id="t", params={"device": "cuda", "require_gpu": False, "size": 8}
        )
        outputs = node.process({}, ctx=None)
        result = json.loads(outputs["result"].text)
        if not status["cuda_available"]:
            # honest CPU fallback must be recorded, never hidden
            assert result["device"] == "cpu"
            assert result["fallback_used"] is True
        else:
            assert result["fallback_used"] is False

    def test_require_gpu_fails_honestly_without_cuda(self):
        status = torch_status()
        if status["cuda_available"]:
            pytest.skip("CUDA available; nothing to test")
        from workflow_engine.errors import NodeInputError

        node = PyTorchTensorOpNode(
            node_id="t", params={"device": "cuda", "require_gpu": True, "size": 8}
        )
        with pytest.raises(NodeInputError) as excinfo:
            node.process({}, ctx=None)
        assert "GPU_UNAVAILABLE" in str(excinfo.value)


class TestModelInference:
    def test_forward_pass_runs(self):
        node = ModelInferenceNode(
            node_id="m", params={"batch_size": 4, "input_dim": 8, "hidden_dim": 16}
        )
        result = json.loads(node.process({}, ctx=None)["result"].text)
        assert result["output_shape"] == [4, 1]
        assert result["device"] in {"cpu"} or result["device"].startswith("cuda")
        assert result["forward_ms"] >= 0


class TestBenchmark:
    def test_benchmark_rows(self):
        node = InferenceBenchmarkNode(
            node_id="b",
            params={"batch_size": 8, "input_dim": 16, "repeats": 3, "warmup": 1},
        )
        table = node.process({}, ctx=None)["result"]
        assert isinstance(table, Table)
        assert len(table.rows) == 3
        assert table.columns == ["run", "duration_ms", "throughput_samples_per_s"]
