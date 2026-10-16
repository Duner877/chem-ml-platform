"""XAS-Sim2Real 节点 + CLI 的端到端验收。

覆盖三层，确保赛题交付不是"能跑就行"：

1. **节点层** —— 真实 registry 创建 ``XASSim2RealNode`` 并执行，
   验证输出对象类型、133 点网格、方向切换与降级路径；
2. **CLI 层** —— 完全按赛题的命令行契约调用 ``solution.py``，
   检查退出码、输出数组集合、ID 完整性、数值合法性；
3. **性能层** —— 确认远在 300 秒硬上限之内完成。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import check_xas_sim2real as synth  # noqa: E402
from models.xas_domain_map import GRID_POINTS, build_grid  # noqa: E402
from workflow_engine.objects import Spectrum  # noqa: E402

PYTHON = sys.executable


def _make_pairs(tmp: str, n: int = 60, seed: int = 7):
    data = synth.build_dataset(n, seed=seed)
    path = os.path.join(tmp, "paired.npz")
    np.savez(
        path,
        sample_id=np.array(data["sample_id"]),
        simulation=data["simulation"],
        experiment=data["experiment"],
        absorber_atomic_number=data["z"],
        edge_code=data["edge_code"],
    )
    return data, path


def section(title: str) -> None:
    print(f"\n{'=' * 66}\n{title}\n{'=' * 66}")


def test_node(direction: str, pairs_path: str, source: np.ndarray) -> None:
    """通过真实 registry 创建并执行节点。"""
    from nodes.loader import get_registry

    registry = get_registry()
    node = registry.create("XASSim2RealNode", params={"direction": direction, "paired_path": pairs_path})

    upstream = Spectrum.from_arrays(
        build_grid(),
        source[0],
        mode="XAS",
        name=f"source {direction}",
    )
    upstream.metadata["absorber_atomic_number"] = 26.0
    upstream.metadata["edge_code"] = 0

    outputs = node.execute({"spectrum": [upstream]})

    assert "prediction" in outputs, sorted(outputs)
    pred = outputs["prediction"]
    assert isinstance(pred, Spectrum), type(pred)
    assert len(pred.x) == GRID_POINTS, len(pred.x)
    assert len(pred.y) == GRID_POINTS, len(pred.y)
    assert np.all(np.isfinite(np.asarray(pred.y, dtype=float))), "预测谱含非有限值"

    assert "table" in outputs and outputs["table"].rows, "逐点表为空"
    assert "text" in outputs

    text = outputs["text"].text
    assert direction in text, f"摘要未标注方向：{text[:200]}"
    assert "不反演结构" in text or "不判定物相" in text, "摘要缺少适用性声明"

    print(f"  节点输出：spectrum({len(pred.y)}点) / table({len(outputs['table'].rows)}行) / text")
    print(f"  摘要首行：{text.splitlines()[0]}")
    assert outputs["prediction"].metadata.get("direction") == direction


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="xas-e2e-")
    try:
        data, pairs_path = _make_pairs(tmp)

        # -- 节点层 ---------------------------------------------------------- #
        section("[1] 节点层：真实 registry 创建与执行")
        test_node("sim2exp", pairs_path, data["simulation"])
        test_node("exp2sim", pairs_path, data["experiment"])

        # 降级：不给 paired_path，必须仍产出合法结果
        from nodes.loader import get_registry

        node = get_registry().create("XASSim2RealNode", params={"direction": "sim2exp"})
        up = Spectrum.from_arrays(build_grid(), data["simulation"][0], mode="XAS", name="degraded")
        out = node.execute({"spectrum": [up]})
        assert len(out["prediction"].y) == GRID_POINTS
        assert np.all(np.isfinite(np.asarray(out["prediction"].y, dtype=float)))
        assert "恒等" in out["text"].text or "identity" in out["text"].text
        print(f"  降级路径 OK（无 paired_path）：method={out['prediction'].metadata.get('method')}")

        # 无输入必须明确失败，不能静默产出假结果
        from workflow_engine.errors import NodeInputError

        try:
            node.execute({})
            raise AssertionError("空输入应当抛 NodeInputError")
        except NodeInputError as exc:
            print(f"  空输入正确失败：{str(exc)[:60]}…")

        # -- CLI 层 ---------------------------------------------------------- #
        section("[2] CLI 层：赛题命令行契约")
        solution = os.path.join(_ROOT, "solution.py")
        assert os.path.exists(solution), "缺少 /root/solution.py 入口"

        qpath = os.path.join(tmp, "queries.npz")
        opath = os.path.join(tmp, "predictions.npz")
        n_q = 24
        half = n_q // 2
        query_ids = [f"Q{i:03d}" for i in range(n_q)]
        query_dir = ["sim2exp"] * half + ["exp2sim"] * (n_q - half)
        query_spec = np.vstack([data["simulation"][:half], data["experiment"][: n_q - half]])
        np.savez(
            qpath,
            sample_id=np.array(query_ids),
            direction=np.array(query_dir),
            energy=build_grid(),
            spectrum=query_spec,
            absorber_atomic_number=np.full(n_q, 26.0),
            edge_code=np.zeros(n_q),
        )

        started = time.perf_counter()
        proc = subprocess.run(
            [PYTHON, solution, "--input", qpath, "--output", opath, "--paired", pairs_path],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=tmp,  # 从任意工作目录调用，验证 sys.path 引导正确
        )
        elapsed = time.perf_counter() - started
        print(f"  退出码 = {proc.returncode}，用时 = {elapsed:.2f}s（上限 300s）")
        assert proc.returncode == 0, proc.stderr[-800:]
        assert elapsed < 300.0, f"超过赛题硬上限：{elapsed:.1f}s"

        with np.load(opath, allow_pickle=False) as out:
            keys = sorted(out.files)
            print(f"  输出数组 = {keys}")
            assert keys == ["prediction", "sample_id"], f"输出数组必须只有两个，实际 {keys}"

            got_ids = [str(v) for v in out["sample_id"]]
            assert sorted(got_ids) == sorted(query_ids), "输出 ID 集合与查询不一致"
            assert len(got_ids) == len(set(got_ids)) == n_q, "ID 数量或重复数不对"

            pred = out["prediction"]
            assert pred.shape == (n_q, GRID_POINTS), pred.shape
            assert np.all(np.isfinite(pred)), "含非有限值"
            assert float(np.max(np.abs(pred))) <= 1e6, "强度越界"
            assert pred.dtype == np.float64, pred.dtype

            # 逐方向核对：模型应当比"原样返回查询谱"更接近真值
            truth = np.vstack([data["experiment"][:half], data["simulation"][: n_q - half]])
            mae_model = float(np.mean(np.abs(pred - truth)))
            mae_copy = float(np.mean(np.abs(query_spec - truth)))
            print(f"  逐点 MAE  = {mae_model:.5f}")
            print(f"  原样返回  = {mae_copy:.5f}（基线）")
            assert mae_model < mae_copy, "模型必须优于原样返回查询谱"

        # -- 确定性（跨进程） ----------------------------------------------- #
        section("[3] 确定性：跨进程重复运行")
        opath2 = os.path.join(tmp, "predictions2.npz")
        subprocess.run(
            [PYTHON, solution, "--input", qpath, "--output", opath2, "--paired", pairs_path],
            capture_output=True, text=True, timeout=300, cwd=tmp,
        )
        with np.load(opath, allow_pickle=False) as a, np.load(opath2, allow_pickle=False) as b:
            pa, pb = a["prediction"], b["prediction"]
        same = np.array_equal(pa, pb)
        max_abs = float(np.max(np.abs(pa - pb)))
        rel = max_abs / max(float(np.max(np.abs(pa))), 1e-12)
        print(f"  逐位相同 = {same}，最大绝对差 = {max_abs:.3e}，相对差 = {rel:.3e}")
        print(f"  容差要求：atol=1e-6, rtol=1e-5")
        assert np.allclose(pa, pb, atol=1e-6, rtol=1e-5), "跨进程结果超出容差"

        # -- 失败路径 -------------------------------------------------------- #
        section("[4] 失败路径：必须非零退出")
        cases = [
            ("缺文件", os.path.join(tmp, "missing.npz")),
        ]
        for label, bad in cases:
            rc = subprocess.run(
                [PYTHON, solution, "--input", bad, "--output", opath],
                capture_output=True, text=True, timeout=120,
            ).returncode
            print(f"  {label} → 退出码 {rc}")
            assert rc != 0, f"{label} 必须非零退出"

        broken = os.path.join(tmp, "broken.npz")
        np.savez(broken, sample_id=np.array(["x"]), spectrum=data["simulation"][:1])
        rc = subprocess.run(
            [PYTHON, solution, "--input", broken, "--output", opath],
            capture_output=True, text=True, timeout=120,
        ).returncode
        print(f"  缺 direction 字段 → 退出码 {rc}")
        assert rc != 0, "缺字段必须非零退出"

        nan_path = os.path.join(tmp, "nan.npz")
        bad_spec = data["simulation"][:2].copy()
        bad_spec[0, 5] = np.nan
        np.savez(
            nan_path,
            sample_id=np.array(["a", "b"]),
            direction=np.array(["sim2exp", "exp2sim"]),
            spectrum=bad_spec,
            absorber_atomic_number=np.array([26.0, 26.0]),
            edge_code=np.array([0.0, 0.0]),
        )
        rc = subprocess.run(
            [PYTHON, solution, "--input", nan_path, "--output", opath],
            capture_output=True, text=True, timeout=120,
        ).returncode
        print(f"  含 NaN → 退出码 {rc}")
        assert rc != 0, "含 NaN 必须非零退出"

        print(f"\n{'=' * 66}\n端到端验收全部通过 ✓\n{'=' * 66}")
        return 0
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())