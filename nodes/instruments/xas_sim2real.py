"""XANES 谱域双向映射节点（sim2exp / exp2sim）。

把 :mod:`models.xas_domain_map` 的能力暴露成可视化节点，使
XAS-Sim2Real 这类"谱到谱迁移"任务可以在 GUI 里编排、观察、并复核外推标记。

节点刻意**不**承诺物相或晶体结构识别：它只做统一网格上的曲线映射，
并把方法来源（恒等 + 残差修正）、支撑样本量、最近邻距离如实写进摘要，
让使用者能区分"验证过的映射"与"训练域外的外推"。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from models.xas_domain_map import GRID_POINTS, XASMapper, build_grid
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

__all__ = ["XASSim2RealNode"]

#: 单色设计语言下的灰阶图标底色，与 Instruments/Surface 同族
CATEGORY_ACCENT = "#6b7280"


@register_node
class XASSim2RealNode(ScientificNode):
    """XAS 谱域双向映射：模拟谱 ↔ 实验谱。"""

    name = "XAS 谱域映射"
    category = "Instruments/Surface"
    description = (
        "XANES 谱到谱双向迁移：sim2exp 由标准化模拟谱预测实验谱，"
        "exp2sim 反向。采用恒等映射 + 岭回归/近邻残差修正，"
        "输出方法来源、支撑样本量与外推标记，不做物相或结构判定。"
    )
    tags = ["xas", "xanes", "sim2exp", "exp2sim", "domain transfer", "spectrum"]
    aliases = ["XAS Sim2Real", "XAS 谱域映射", "Sim2Real"]
    icon = "XS"

    input_ports = [
        # 用 Spectrum 而不是固定 NPZ 路径：这样上游既能接真实文件节点，
        # 也能接另一个仪器的输出，保持工作流的可组合性。
        Port("spectrum", "Spectrum", "待映射的源谱（模拟谱或实验谱）", optional=True, multi=True),
    ]

    output_ports = [
        Port("prediction", "Spectrum", "目标域预测谱"),
        Port("table", "Table", "逐点预测与残差"),
        Port("text", "Text", "映射方法与可靠性说明"),
    ]

    parameters = [
        ParameterSpec(
            "direction",
            "enum",
            "sim2exp",
            "映射方向",
            options=["sim2exp", "exp2sim"],
        ),
        ParameterSpec(
            "absorbed_Z",
            "number",
            0.0,
            "吸收元素原子序数（0 = 取上游谱自带值）",
            min=0.0,
            max=118.0,
            step=1.0,
        ),
        ParameterSpec(
            "edge_code",
            "enum",
            "K",
            "吸收边",
            options=["K", "L2", "L3"],
        ),
        ParameterSpec(
            "paired_path",
            "string",
            "",
            "配对训练数据 NPZ 路径（留空则用恒等映射）",
            advanced=True,
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectra = self._collect_spectra(inputs)
        if not spectra:
            raise NodeInputError(
                f"{self.node_type()}: 没有输入谱图。请连接一个 Spectrum 输入，或在配对数据路径中提供查询。"
            )

        direction = str(self.get_param("direction", "sim2exp") or "sim2exp").strip()
        if direction not in ("sim2exp", "exp2sim"):
            raise NodeInputError(f"{self.node_type()}: 未知 direction {direction!r}")

        edge_code = {"K": 0, "L2": 1, "L3": 2}.get(
            str(self.get_param("edge_code", "K") or "K"), 0
        )
        z_param = float(self.get_param("absorbed_Z", 0.0) or 0.0)

        mapper, support_note = self._build_mapper(direction)
        grid = build_grid()

        predictions: List[np.ndarray] = []
        details: List[str] = []
        rows: List[List[Any]] = []
        any_extrapolation = False
        support = 0

        for spectrum in spectra:
            curve = np.asarray(spectrum.y, dtype=float)
            if curve.size != GRID_POINTS:
                curve = _resize_to_grid(curve)

            z_value = z_param or float(spectrum.metadata.get("absorber_atomic_number", 0.0) or 0.0)
            code = edge_code if edge_code or not spectrum.metadata.get("edge_code") else int(
                spectrum.metadata.get("edge_code") or edge_code
            )

            if mapper is None:
                predicted = np.array(curve, dtype=float)
                note = "无配对训练数据，使用恒等映射 / identity map"
                distance = float("inf")
                extrapolating = True
                method = "identity"
                support = 0
            else:
                result = mapper.predict(curve, z=z_value, edge_code=code)
                predicted = result.prediction
                note = result.method
                distance = result.nearest_distance
                extrapolating = result.extrapolating
                method = result.method
                support = result.n_support
                any_extrapolation = any_extrapolation or extrapolating

            predicted = np.nan_to_num(predicted, nan=0.0, posinf=0.0, neginf=0.0)
            predictions.append(predicted)
            details.append(
                f"  [{spectrum.name}] 方法={note}，最近邻距离="
                f"{('∞' if not np.isfinite(distance) else f'{distance:.3f}')}"
                f"{'，外推' if extrapolating else ''}"
            )

            for i in range(min(GRID_POINTS, predicted.size)):
                rows.append(
                    [
                        spectrum.name,
                        round(float(grid[i]), 4),
                        round(float(curve[i]), 6),
                        round(float(predicted[i]), 6),
                        round(float(predicted[i] - curve[i]), 6),
                    ]
                )

        prediction_spectrum = Spectrum.from_arrays(
            grid,
            np.mean(np.vstack(predictions), axis=0),
            mode="XAS",
            x_unit="eV (relative to edge)",
            y_unit="normalized intensity",
            name=f"XAS {direction} prediction",
        )
        prediction_spectrum.technique = "XANES domain transfer"
        prediction_spectrum.metadata.update(
            {
                "direction": direction,
                "method": method,
                "n_support": support,
                "extrapolating": bool(any_extrapolation),
                "n_input_spectra": len(spectra),
            }
        )

        table = Table(
            name="XAS domain mapping",
            columns=[
                "spectrum",
                "energy (eV)",
                "source intensity",
                "predicted intensity",
                "correction",
            ],
            rows=rows,
        )

        grid_note = f"统一网格 {GRID_POINTS} 点，{grid[0]:.1f}–{grid[-1]:.1f} eV"
        header = [
            f"XAS 谱域映射 / XANES domain transfer — 方向 direction = {direction}",
            f"{grid_note}；配对支撑样本 support = {support}",
        ]
        if support_note:
            header.append(f"训练数据：{support_note}")
        header.append("逐谱诊断 / per-spectrum diagnostics：")
        header.extend(details)
        header.append(
            "说明：本节点只做统一网格上的谱到谱映射，不反演结构、不判定物相。"
        )
        if any_extrapolation:
            header.append(
                "⚠ 至少一条查询落在训练支撑范围之外，应按低置信度外推看待，"
                "而非已验证的校准结果。"
            )

        text = Text(name="XAS domain transfer", text="\n".join(header))
        return {"prediction": prediction_spectrum, "table": table, "text": text}

    # -- helpers -------------------------------------------------------------- #
    @staticmethod
    def _collect_spectra(inputs: Dict[str, Any]) -> List[Spectrum]:
        raw = inputs.get("spectrum")
        if raw is None:
            return []
        if isinstance(raw, Spectrum):
            return [raw]
        if isinstance(raw, (list, tuple)):
            return [item for item in raw if isinstance(item, Spectrum)]
        return []

    def _build_mapper(self, direction: str):
        path = str(self.get_param("paired_path", "") or "").strip()
        if not path:
            return None, "未提供 paired_path"
        try:
            from models.xas_sim2real import load_pairs

            pairs = load_pairs(path)
        except Exception as exc:  # noqa: BLE001 - 训练数据不可用时降级而非崩溃
            return None, f"配对数据不可用（{exc}），已降级为恒等映射"

        source = pairs["simulation"] if direction == "sim2exp" else pairs["experiment"]
        target = pairs["experiment"] if direction == "sim2exp" else pairs["simulation"]
        if source.shape[0] == 0:
            return None, "配对训练集为空"

        mapper = XASMapper(
            source=source,
            target=target,
            z_values=pairs["z"],
            edge_codes=pairs["edge_code"],
            direction=direction,
        )
        return mapper, f"{source.shape[0]} 对配对谱"


def _resize_to_grid(curve: np.ndarray) -> np.ndarray:
    """把任意长度的曲线放到标准 133 点网格上（线性插值）。"""
    src = np.asarray(curve, dtype=float).reshape(-1)
    if src.size == GRID_POINTS:
        return src
    target = build_grid()
    if src.size == 0:
        return np.zeros(GRID_POINTS, dtype=float)
    src_grid = np.linspace(-3.0, 30.0, src.size, dtype=float)
    return np.interp(target, src_grid, src)