"""XAS-Sim2Real 双向映射的合成数据验证。

真实配对数据不在仓库里（赛题数据在评测环境），所以这里造一批**结构已知**
的合成谱：模拟域与实验域之间存在真实的系统性差异（展宽、位移、缩放、
噪声），然后检查双向映射是否真的学到了这个变换，而不是退化成常数。

这是"先自己验证再交付"的一步：引擎如果连有明确规律的数据都拟合不了，
就不可能在真实数据上工作。
"""

from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.xas_domain_map import GRID_POINTS, build_grid, extract_features  # noqa: E402
from models.xas_sim2real import load_queries, solve  # noqa: E402


def _synthetic_spectrum(rng: np.random.Generator, z: float, edge_code: int) -> np.ndarray:
    """造一条物理上像 XANES 的谱：pre-edge 平、边跳、白线、post-edge 振荡衰减。"""
    grid = build_grid()
    edge_e = {0: 7050.0, 1: 720.0, 2: 707.0}[int(edge_code)]
    del edge_e  # 相对能量网格上吸收边就在 0 eV，这里只用码来区分类别

    white_height = 0.6 + 0.35 * ((z % 9) / 9.0)
    white_pos = 1.0 + 1.6 * (((z * 7) % 5) / 5.0)
    pre_level = 0.02 + 0.01 * ((z % 4) / 4.0)

    curve = np.full(grid.size, pre_level)
    curve += white_height * np.exp(-0.5 * ((grid - white_pos) / 0.9) ** 2)
    # arctan 边跳
    curve += (0.85 + 0.1 * ((z % 6) / 6.0)) / (1.0 + np.exp(-(grid - 0.4) / 0.28))
    # post-edge 振荡衰减
    post = np.clip(grid - 2.0, 0.0, None)
    curve += 0.11 * np.exp(-post / 9.0) * np.sin(post / 1.35 + (z % 7) * 0.4)

    curve = curve + rng.normal(0.0, 0.004, size=grid.size)
    peak = float(curve.max())
    return curve / peak if peak > 0 else curve


def _to_experiment(sim: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """施加真实的实验域系统误差：能量零点位移、展宽、缩放、噪声、混合。"""
    grid = build_grid()
    shifted = np.interp(grid - 0.18, grid, sim, left=sim[0], right=sim[-1])
    broadened = 0.72 * shifted + 0.28 * np.convolve(
        np.pad(shifted, 1, mode="edge"), np.array([0.25, 0.5, 0.25]), mode="valid"
    )
    exp = broadened * 1.07 + 0.015
    exp = exp + rng.normal(0.0, 0.006, size=grid.size)
    return exp


def build_dataset(n: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    zs, edges, sims, exps = [], [], [], []
    for i in range(n):
        z = float(8 + (i * 7) % 83)
        edge = float(i % 3)
        sim = _synthetic_spectrum(rng, z, int(edge))
        exp = _to_experiment(sim, rng)
        zs.append(z)
        edges.append(edge)
        sims.append(sim)
        exps.append(exp)
    return {
        "sample_id": [f"S{i:04d}" for i in range(n)],
        "simulation": np.array(sims),
        "experiment": np.array(exps),
        "z": np.array(zs),
        "edge_code": np.array(edges),
    }


def _mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def main() -> int:
    print("=" * 70)
    print("XAS-Sim2Real 双向映射 —— 合成数据验证")
    print("=" * 70)

    grid = build_grid()
    assert grid.size == GRID_POINTS, grid.size
    assert abs(grid[1] - grid[0] - 0.25) < 1e-12, "步长必须是 0.25 eV"

    # -- 特征提取基本性质 ------------------------------------------------- #
    print("\n[1] 特征提取")
    rng = np.random.default_rng(0)
    curve = _synthetic_spectrum(rng, 26.0, 0)
    feats = extract_features(curve, 26.0, 0)
    print(f"    维度 = {feats.size}（有限 = {bool(np.all(np.isfinite(feats)))}）")
    assert feats.size > 0 and np.all(np.isfinite(feats))

    # 白线位置应当被特征抓到：换元素应当改变描述子
    f1 = extract_features(_synthetic_spectrum(rng, 26.0, 0), 26.0, 0)
    f2 = extract_features(_synthetic_spectrum(rng, 74.0, 2), 74.0, 2)
    print(f"    不同 (Z, edge) 的描述子距离 = {np.linalg.norm(f1 - f2):.4f}（应 > 0）")
    assert np.linalg.norm(f1 - f2) > 0

    # -- 训练 / 测试划分 ---------------------------------------------------- #
    print("\n[2] 拟合与双向精度（60 训练 / 20 测试）")
    train = build_dataset(60, seed=1)
    test = build_dataset(20, seed=99)

    # 共用元素/边分布，模拟真实"同分布查询"
    pairs = {
        "sample_id": train["sample_id"],
        "simulation": train["simulation"],
        "experiment": train["experiment"],
        "z": train["z"],
        "edge_code": train["edge_code"],
    }

    for direction in ("sim2exp", "exp2sim"):
        src_key = "simulation" if direction == "sim2exp" else "experiment"
        dst_key = "experiment" if direction == "sim2exp" else "simulation"
        queries = {
            "sample_id": test["sample_id"],
            "direction": [direction] * len(test["sample_id"]),
            "spectrum": test[src_key],
            "z": test["z"],
            "edge_code": test["edge_code"],
        }
        ids, pred, results = solve(queries, pairs)

        truth = test[dst_key]
        mae = _mae(pred, truth)

        # 基线1：直接照抄源谱（域相同才有效，这里应当很差）
        copy_mae = _mae(queries["spectrum"], truth)
        # 基线2：训练目标均值
        mean_baseline = _mae(
            np.repeat(pairs[dst_key].mean(axis=0, keepdims=True), len(truth), axis=0), truth
        )

        # 一阶导数误差（赛题评分项之一）
        d_pred = np.diff(pred, axis=1)
        d_true = np.diff(truth, axis=1)
        d_mae = float(np.mean(np.abs(d_pred - d_true)))

        # 最高峰位置误差（赛题评分项之一）
        peak_err = float(
            np.mean(np.abs(pred.argmax(axis=1) - truth.argmax(axis=1)))
        )

        print(f"\n    === {direction} ===")
        print(f"    逐点 MAE      : {mae:.5f}")
        print(f"    照抄源谱基线  : {copy_mae:.5f}   (越差说明域差异越大)")
        print(f"    目标均值基线  : {mean_baseline:.5f}")
        print(f"    一阶导数 MAE  : {d_mae:.5f}")
        print(f"    最高峰位移(点): {peak_err:.3f}")
        print(f"    外推标记条数  : {sum(1 for r in results if r.extrapolating)}")
        print(f"    支撑样本数    : {results[0].n_support}")

        assert mae < mean_baseline, f"{direction}: 模型必须优于均值基线"
        assert np.all(np.isfinite(pred))
        assert pred.shape == (len(test["sample_id"]), GRID_POINTS)

    # -- 双向一致性 -------------------------------------------------------- #
    print("\n[3] 往返一致性（sim -> exp -> sim）")
    fwd_queries = {
        "sample_id": test["sample_id"],
        "direction": ["sim2exp"] * len(test["sample_id"]),
        "spectrum": test["simulation"],
        "z": test["z"],
        "edge_code": test["edge_code"],
    }
    _, exp_hat, _ = solve(fwd_queries, pairs)

    back_queries = {
        "sample_id": test["sample_id"],
        "direction": ["exp2sim"] * len(test["sample_id"]),
        "spectrum": exp_hat,
        "z": test["z"],
        "edge_code": test["edge_code"],
    }
    _, sim_roundtrip, _ = solve(back_queries, pairs)

    rt_mae = _mae(sim_roundtrip, test["simulation"])
    direct_mae = _mae(exp_hat, test["experiment"])
    print(f"    sim -> exp 误差         : {direct_mae:.5f}")
    print(f"    往返后 sim 误差         : {rt_mae:.5f}")
    print(f"    往返放大倍数            : {rt_mae / max(direct_mae, 1e-9):.2f}x")

    # -- 确定性 ------------------------------------------------------------ #
    print("\n[4] 确定性（重复运行必须逐位一致）")
    _, pred_a, _ = solve(fwd_queries, pairs)
    _, pred_b, _ = solve(fwd_queries, pairs)
    identical = np.array_equal(pred_a, pred_b)
    max_diff = float(np.max(np.abs(pred_a - pred_b)))
    print(f"    逐位相同 = {identical}，最大差异 = {max_diff:.3e}")
    assert identical, "确定性契约被破坏"

    # -- 空训练集降级 ------------------------------------------------------ #
    print("\n[5] 空训练集降级路径")
    empty = {
        "sample_id": [],
        "simulation": np.zeros((0, GRID_POINTS)),
        "experiment": np.zeros((0, GRID_POINTS)),
        "z": np.zeros(0),
        "edge_code": np.zeros(0),
    }
    _, flat_pred, flat_res = solve(fwd_queries, empty)
    print(f"    输出形状 = {flat_pred.shape}，有限 = {bool(np.all(np.isfinite(flat_pred)))}")
    print(f"    方法标注 = {flat_res[0].method}")
    assert flat_pred.shape == (len(test["sample_id"]), GRID_POINTS)
    assert np.all(np.isfinite(flat_pred))

    # -- 未见吸收边应标为外推 --------------------------------------------- #
    print("\n[6] 未见吸收边应标记为外推")
    ood_queries = {
        "sample_id": ["OOD-1"],
        "direction": ["sim2exp"],
        "spectrum": test["simulation"][:1],
        "z": np.array([8.0]),
        "edge_code": np.array([7.0]),  # 训练集只含 0/1/2
    }
    _, _, ood_res = solve(ood_queries, pairs)
    print(f"    extrapolating = {ood_res[0].extrapolating}")
    print(f"    notes = {ood_res[0].notes}")
    assert ood_res[0].extrapolating, "未见吸收边必须标记外推"

    # -- CLI 端到端 -------------------------------------------------------- #
    print("\n[7] CLI 端到端（契约：predictions.npz 只含两个数组）")
    with tempfile.TemporaryDirectory() as tmp:
        qpath = os.path.join(tmp, "queries.npz")
        ppath = os.path.join(tmp, "paired.npz")
        opath = os.path.join(tmp, "predictions.npz")
        np.savez(
            qpath,
            sample_id=np.array(["a", "b", "c", "d"]),
            direction=np.array(["sim2exp", "exp2sim", "sim2exp", "exp2sim"]),
            spectrum=np.vstack(
                [test["simulation"][:2], test["experiment"][:2]]
            ),
            absorber_atomic_number=np.array([26.0, 26.0, 57.0, 57.0]),
            edge_code=np.array([0.0, 0.0, 1.0, 1.0]),
        )
        np.savez(
            ppath,
            sample_id=train["sample_id"],
            simulation=train["simulation"],
            experiment=train["experiment"],
            absorber_atomic_number=train["z"],
            edge_code=train["edge_code"],
        )

        from models.xas_sim2real import main as cli_main

        code = cli_main(["--input", qpath, "--output", opath, "--paired", ppath, "--verbose"])
        print(f"    退出码 = {code}")
        assert code == 0

        with np.load(opath, allow_pickle=False) as out:
            keys = sorted(out.files)
            print(f"    输出数组 = {keys}")
            assert keys == ["prediction", "sample_id"], keys
            got_ids = [str(v) for v in out["sample_id"]]
            assert got_ids == ["a", "b", "c", "d"], got_ids
            assert out["prediction"].shape == (4, GRID_POINTS)
            assert np.all(np.isfinite(out["prediction"]))
            assert float(np.max(np.abs(out["prediction"]))) <= 1e6
        print("    契约校验通过")

        # 缺失文件必须非零退出
        bad = cli_main(["--input", os.path.join(tmp, "nope.npz"), "--output", opath])
        print(f"    缺文件退出码 = {bad}（应为非 0）")
        assert bad != 0

        # 缺字段必须非零退出
        broken = os.path.join(tmp, "broken.npz")
        np.savez(broken, sample_id=np.array(["x"]), spectrum=test["simulation"][:1])
        bad2 = cli_main(["--input", broken, "--output", opath])
        print(f"    缺字段退出码 = {bad2}（应为非 0）")
        assert bad2 != 0

    print("\n" + "=" * 70)
    print("全部验证通过 ✓")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())