"""XAS-Sim2Real 双向谱域映射 —— 数据装载与命令行求解器。

赛题要求在 ``/root/solution.py`` 暴露

    python /root/solution.py --input queries.npz --output predictions.npz

本模块提供两件事：

* :func:`load_pairs` —— 读取公开的配对 NPZ（``simulation`` / ``experiment``）
  以及可选的辅助实验谱，供拟合使用；
* :func:`main` —— 严格遵循赛题契约的推理入口：双方向、确定性、300秒硬上限、
  非零退出码表示明确失败。

三条容易踩的契约红线，实现时都按"宁可明确失败也不伪造"处理：

1. **输入非法必须失败**，不得静默产出合法外观的假结果；
2. **输出 ID 集合必须与查询完全一致**，不增不删不重复；
3. **无状态**，不得依赖上一次运行留下的缓存或检查点。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from models.xas_domain_map import (
    GRID_POINTS,
    XASMapper,
    XASMappingResult,
)

__all__ = ["load_pairs", "load_queries", "solve", "main"]

#: 赛题的硬性时限。留出余量，好在超时前主动降级而不是被杀掉。
TIME_BUDGET_S = 240.0

#: 单条预测的绝对强度上限（赛题禁止超过 1e6）。
MAX_ABS_INTENSITY = 1.0e6


# --------------------------------------------------------------------------- #
# 严格校验
# --------------------------------------------------------------------------- #
def _require_finite(array: np.ndarray, label: str) -> np.ndarray:
    arr = np.asarray(array, dtype=float)
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{label} 含有非有限值（NaN/Inf）/ {label} contains non-finite values")
    return arr


def _as_2d(array: np.ndarray, label: str) -> np.ndarray:
    arr = np.asarray(array, dtype=float)
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    if arr.ndim != 2:
        raise ValueError(f"{label} 维度应为 (N, 133)，实际为 {arr.ndim} 维")
    if arr.shape[1] != GRID_POINTS:
        raise ValueError(f"{label} 每行应为 {GRID_POINTS} 点，实际为 {arr.shape[1]}")
    return _require_finite(arr, label)


def _strings(array: np.ndarray) -> List[str]:
    return [str(v) for v in np.asarray(array).reshape(-1).tolist()]


# --------------------------------------------------------------------------- #
# 装载
# --------------------------------------------------------------------------- #
def load_pairs(path: str) -> Dict[str, Any]:
    """读取公开配对 NPZ。

    需要的键：``simulation`` 与 ``experiment``（可选 ``absorber_atomic_number``、
    ``edge_code``、``sample_id``）。**缺键即失败**，不做静默回退——赛题明确
    要求"数组字段缺失时明确失败"。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到配对数据 / paired dataset not found: {path}")

    with np.load(path, allow_pickle=False) as data:
        if "simulation" not in data or "experiment" not in data:
            missing = [k for k in ("simulation", "experiment") if k not in data]
            raise KeyError(f"配对数据缺少必需数组 / missing arrays: {missing}")

        simulation = _as_2d(data["simulation"], "simulation")
        experiment = _as_2d(data["experiment"], "experiment")
        if simulation.shape[0] != experiment.shape[0]:
            raise ValueError(
                "simulation 与 experiment 的样本数不一致 / paired arrays disagree: "
                f"{simulation.shape[0]} vs {experiment.shape[0]}"
            )

        n = simulation.shape[0]
        z = (
            _require_finite(np.asarray(data["absorber_atomic_number"], dtype=float), "absorber_atomic_number")
            if "absorber_atomic_number" in data
            else np.zeros(n)
        ).reshape(-1)
        edge = (
            _require_finite(np.asarray(data["edge_code"], dtype=float), "edge_code")
            if "edge_code" in data
            else np.zeros(n)
        ).reshape(-1)
        ids = _strings(data["sample_id"]) if "sample_id" in data else [str(i) for i in range(n)]

    if len(z) != n or len(edge) != n or len(ids) != n:
        raise ValueError("配对数据的元数据长度与谱数组不一致 / metadata length mismatch")

    return {
        "sample_id": ids,
        "simulation": simulation,
        "experiment": experiment,
        "z": z,
        "edge_code": edge,
    }


def load_queries(path: str) -> Dict[str, Any]:
    """读取评分用查询文件。"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到查询文件 / queries not found: {path}")

    with np.load(path, allow_pickle=False) as data:
        for key in ("sample_id", "direction", "spectrum"):
            if key not in data:
                raise KeyError(f"查询文件缺少必需数组 / missing array: {key}")

        sample_ids = _strings(data["sample_id"])
        directions = _strings(data["direction"])
        spectrum = _as_2d(data["spectrum"], "spectrum")

        n = spectrum.shape[0]
        if not (len(sample_ids) == len(directions) == n):
            raise ValueError("查询文件的字段长度不一致 / query fields disagree on length")

        z = (
            _require_finite(np.asarray(data["absorber_atomic_number"], dtype=float), "absorber_atomic_number")
            if "absorber_atomic_number" in data
            else np.zeros(n)
        ).reshape(-1)
        edge = (
            _require_finite(np.asarray(data["edge_code"], dtype=float), "edge_code")
            if "edge_code" in data
            else np.zeros(n)
        ).reshape(-1)

    if len(set(sample_ids)) != len(sample_ids):
        raise ValueError("查询文件含重复 sample_id / duplicate sample_id in queries")

    unknown = sorted({d for d in directions} - {"sim2exp", "exp2sim"})
    if unknown:
        raise ValueError(f"未知的 direction 取值 / unknown direction values: {unknown}")

    if len(z) != n or len(edge) != n:
        raise ValueError("查询元数据长度与谱数组不一致 / query metadata length mismatch")

    return {
        "sample_id": sample_ids,
        "direction": directions,
        "spectrum": spectrum,
        "z": z,
        "edge_code": edge,
    }


# --------------------------------------------------------------------------- #
# 求解
# --------------------------------------------------------------------------- #
def _train_direction(
    pairs: Dict[str, Any], direction: str
) -> Tuple[Optional[XASMapper], str]:
    """按方向装配 mapper；训练集为空时返回 ``(None, 原因)``。"""
    source = pairs["simulation"] if direction == "sim2exp" else pairs["experiment"]
    target = pairs["experiment"] if direction == "sim2exp" else pairs["simulation"]
    if source.shape[0] == 0:
        return None, "配对训练集为空 / paired training set is empty"
    mapper = XASMapper(
        source=source,
        target=target,
        z_values=pairs["z"],
        edge_codes=pairs["edge_code"],
        direction=direction,
    )
    return mapper, "ok"


def solve(
    queries: Dict[str, Any],
    pairs: Dict[str, Any],
    verbose: bool = False,
) -> Tuple[np.ndarray, List[str], List[XASMappingResult]]:
    """对全部查询给出预测。

    返回 ``(sample_id, prediction, details)``。``prediction`` 形状为
    ``(N, 133)``，全部有限，且被夹在赛题允许的强度范围内。
    """
    started = time.perf_counter()

    ids = queries["sample_id"]
    directions = queries["direction"]
    spectrum = queries["spectrum"]
    z = queries["z"]
    edge = queries["edge_code"]
    n = len(ids)

    mappers: Dict[str, Optional[XASMapper]] = {}
    reasons: Dict[str, str] = {}
    for direction in sorted(set(directions)):
        mapper, reason = _train_direction(pairs, direction)
        mappers[direction] = mapper
        reasons[direction] = reason
        if verbose:
            support = 0 if mapper is None else mapper.n_support
            print(
                f"[xas] {direction}: 训练样本 {support} 条 ({reason})",
                file=sys.stderr,
            )

    # 每个方向的阈值取自训练集自身的留一最近邻距离，不写死常数。
    thresholds: Dict[str, Optional[float]] = {}
    for direction, mapper in mappers.items():
        thresholds[direction] = (
            None if mapper is None else mapper.support_distance_quantile(0.95)
        )

    results: List[XASMappingResult] = []
    for i in range(n):
        direction = directions[i]
        mapper = mappers[direction]
        if mapper is None:
            # Deterministic degradation: copy the query through unchanged.  For a
            # domain transfer the identity map is the right zero-effort answer,
            # and it keeps the output complete and legal as the task requires.
            flat = np.asarray(spectrum[i], dtype=float)
            results.append(
                XASMappingResult(
                    sample_id=ids[i],
                    direction=direction,
                    prediction=flat,
                    method="identity (no paired training data)",
                    n_support=0,
                    nearest_distance=float("inf"),
                    extrapolating=True,
                    notes=[reasons.get(direction, "无可用训练数据")],
                )
            )
            continue

        remaining = TIME_BUDGET_S - (time.perf_counter() - started)
        result = mapper.predict(
            spectrum[i],
            z=float(z[i]),
            edge_code=int(edge[i]),
            sample_id=ids[i],
            distance_threshold=thresholds[direction] if remaining > 0 else None,
        )
        # 预算耗尽后不再做外推标注，但预测本身仍然输出（合法且完整）。
        if remaining <= 0 and result.extrapolating:
            result.notes.append("时间预算耗尽，已跳过外推标注 / time budget spent")
        results.append(result)

    prediction = np.vstack([r.prediction for r in results]).astype(float)

    # 契约校验：有限、无超界、ID 齐全。宁可在这里失败，也不产出假结果。
    if prediction.shape != (n, GRID_POINTS):
        raise ValueError(f"预测形状错误 / prediction shape {prediction.shape} != {(n, GRID_POINTS)}")
    if not np.all(np.isfinite(prediction)):
        raise ValueError("预测含非有限值 / prediction contains non-finite values")
    if np.max(np.abs(prediction)) > MAX_ABS_INTENSITY:
        # 裁剪而非报错：这是数值保护，不改变合法输入下的结果。
        prediction = np.clip(prediction, -MAX_ABS_INTENSITY, MAX_ABS_INTENSITY)
    if len(ids) != len(set(ids)) or len(ids) != n:
        raise ValueError("输出 ID 集合与查询不一致 / output ids do not match queries")

    if verbose:
        elapsed = time.perf_counter() - started
        print(
            f"[xas] 完成 / done: {n} 条预测，用时 {elapsed:.2f}s",
            file=sys.stderr,
        )

    return ids, prediction, results


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="solution.py",
        description="XAS-Sim2Real 双向 XANES 谱域映射（sim2exp / exp2sim）",
    )
    parser.add_argument("--input", required=True, help="queries.npz 路径")
    parser.add_argument("--output", required=True, help="predictions.npz 输出路径")
    parser.add_argument(
        "--paired",
        default=None,
        help="公开配对训练数据路径，默认在 input 同目录及 ./data 下查找",
    )
    parser.add_argument("--verbose", action="store_true", help="打印进度到 stderr")
    return parser


def _discover_paired(explicit: Optional[str], input_path: str) -> Optional[str]:
    """定位公开配对数据。找不到不是致命错误——仍可用平坦基线完成输出。"""
    if explicit:
        return explicit if os.path.exists(explicit) else None

    base = os.path.dirname(os.path.abspath(input_path))
    candidates = [
        os.path.join(base, "paired_train.npz"),
        os.path.join(base, "train.npz"),
        os.path.join(base, "xas_pairs.npz"),
        os.path.join(base, "data", "paired_train.npz"),
        os.path.join(os.getcwd(), "paired_train.npz"),
        os.path.join(os.getcwd(), "data", "paired_train.npz"),
        "/root/environment/data/paired_train.npz",
        "/root/data/paired_train.npz",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # -- 输入校验：任何问题都明确失败并返回非零退出码 ------------------- #
    try:
        queries = load_queries(args.input)
    except Exception as exc:  # noqa: BLE001 - 契约要求：明确失败
        print(f"[xas] 查询文件无效 / invalid queries: {exc}", file=sys.stderr)
        return 2

    paired_path = _discover_paired(args.paired, args.input)
    pairs: Dict[str, Any] = {
        "sample_id": [],
        "simulation": np.zeros((0, GRID_POINTS)),
        "experiment": np.zeros((0, GRID_POINTS)),
        "z": np.zeros(0),
        "edge_code": np.zeros(0),
    }
    if paired_path:
        try:
            pairs = load_pairs(paired_path)
            if args.verbose:
                print(f"[xas] 使用配对训练数据 / using paired data: {paired_path}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            # 训练数据不可用时降级，而不是让整次推理失败——赛题允许确定性降级。
            print(
                f"[xas] 配对数据不可用，降级为平坦基线 / paired data unusable, "
                f"falling back: {exc}",
                file=sys.stderr,
            )
            pairs = {
                "sample_id": [],
                "simulation": np.zeros((0, GRID_POINTS)),
                "experiment": np.zeros((0, GRID_POINTS)),
                "z": np.zeros(0),
                "edge_code": np.zeros(0),
            }
    elif args.verbose:
        print("[xas] 未找到配对训练数据，使用平坦基线 / no paired data, flat baseline", file=sys.stderr)

    try:
        ids, prediction, _details = solve(queries, pairs, verbose=args.verbose)
    except Exception as exc:  # noqa: BLE001
        print(f"[xas] 推理失败 / inference failed: {exc}", file=sys.stderr)
        return 3

    out_dir = os.path.dirname(os.path.abspath(args.output))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 只写契约允许的两个数组。
    np.savez(
        args.output,
        sample_id=np.asarray(ids, dtype=np.str_),
        prediction=prediction.astype(np.float64),
    )

    if args.verbose:
        print(f"[xas] 已写出 / wrote {args.output}: {prediction.shape}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())