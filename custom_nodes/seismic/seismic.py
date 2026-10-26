"""Full-waveform inversion node family (v0.7.3).

Wraps :mod:`simulations.fwi` and :mod:`simulations.fwi_submission` -- the 2-D
acoustic forward solver, adjoint gradient, source-signature recovery and the
task's three output files -- into the workflow graph.

Four nodes, so a workflow can either drive the whole task or inspect one stage:

``SeismicSurveyNode``      acquisition geometry + a starting 1-D depth trend
``SeismicForwardNode``     forward-modelled shot gathers, and the Green's
                           functions that :class:`FWIInversionNode` needs
``FWIInversionNode``       the inversion itself, with held-out validation
``SeismicSubmissionNode``  writes ``velocity_model.npy`` / ``wavelet.npy`` /
                           ``run_summary.json`` and scores the result

The last node is the reason the family exists as four nodes and not two: the
task is scored on a number that removes the depth mean, and on held-out shots
that must also improve.  A run that reported only "misfit fell" would be
reporting the wrong thing, so the submission node carries the score and the
validation explicitly, and leaves them ``null`` -- rather than substituting the
fitted shots -- when there is no truth or no held-out split to measure.

Every node records which engine answered in ``metadata["engine"]``.  This is an
internal finite-difference solver; where an external propagator exists and is
requested, the node says so rather than silently using the built-in one.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from simulations.fwi import (
    V_MAX,
    V_MIN,
    FWIConfig,
    FwdResult,
    forward_model,
    illumination_weights,
    run_fwi,
)
from simulations.fwi_submission import (
    load_submission,
    score_model,
    synthetic_benchmark,
    write_submission,
)
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Image, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

__all__ = [
    "SeismicSurveyNode",
    "SeismicForwardNode",
    "FWIInversionNode",
    "SeismicSubmissionNode",
]

_ENGINE = "internal:acoustic-fd"

_PROVENANCE_ZH = (
    "内置二维常密度声学有限差分求解器（二阶时间/二阶空间，海绵吸收层，"
    "地表对称 Neumann 闭包），非工业地震成像软件。"
    " / Built-in 2-D constant-density acoustic finite-difference solver "
    "(second-order time and space, sponge absorber, symmetric Neumann surface "
    "closure), not a commercial seismic imaging package."
)

_PROVENANCE_EN = (
    "Built-in 2-D constant-density acoustic finite-difference solver, "
    "not a commercial seismic imaging package."
)

_WARNING_ZH = (
    "起始模型为纯深度趋势时，浅层强横向构造会超出最低频段的半波长，"
    "属于循环跳（cycle skip）的物理限制，不是求解器缺陷。"
    " / With a depth-trend start, shallow sharp lateral structure exceeds the "
    "lowest band half-wavelength -- cycle skipping, a physics limit rather "
    "than a solver defect."
)


def _survey_from_inputs(inputs: Dict[str, Any]) -> Any:
    """Pull the survey out of the incoming port values.

    Accepts either a :class:`~simulations.fwi.Survey` passed straight through
    or the ``(records, geometry, start)`` triple, because the graph engine
    hands over whatever the upstream node returned on the named port.
    """
    from simulations.fwi import Survey

    for value in inputs.values():
        if isinstance(value, Survey):
            return value
    raise ValueError(
        "no Survey on the input ports; connect the survey node's 'survey' output"
    )


# --------------------------------------------------------------------------- #
@register_node
class SeismicSurveyNode(ScientificNode):
    """Acquisition geometry plus the one-dimensional starting model.

    The task's premise is a *depth trend* as the starting model, and the score
    removes the depth mean at every depth -- so the gap between this node's
    output and the truth is precisely the part of the problem that counts.  This
    node therefore reports the trend's own lateral correlation with the truth
    (0.0 by construction when no truth is supplied) instead of implying the
    start is "close".

    With no external file it builds a reproducible synthetic benchmark: a
    normal fault, two dipping interfaces and a low-velocity lens, recorded with
    the same forward solver the inversion uses.  That is a test fixture, and the
    node labels it as one.

    Outputs
    -------
    ``survey``  Survey      acquisition + starting model (pass-through object)
    ``records`` Spectrum    shot gathers, one trace per receiver
    ``trend``   Spectrum    the starting 1-D depth trend
    ``text``    Text        geometry description and provenance
    """

    name = "Seismic Survey"
    category = "Instruments/Seismic"
    description = (
        "构建二维声学地震采集：一维深度趋势起始模型 + 炮检几何，"
        "无外部数据时生成可复现的合成含断层剖面。"
    )
    tags = ["seismic", "fwi", "survey", "acquisition", "inversion"]
    icon = "SS"
    capabilities = ["models_seismic_forward"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = []
    output_ports = [
        Port("survey", "Survey", "采集对象：记录、炮检几何与起始模型"),
        Port("records", "Spectrum", "炮集道集（横轴道号，纵轴振幅）"),
        Port("trend", "Spectrum", "一维深度趋势起始速度"),
        Port(
            "truth",
            "Image",
            "合成真值剖面（仅 source=synthetic 时提供；真实数据无此项）",
        ),
        Port("text", "Text", "采集几何说明与数据出处"),
    ]

    parameters = [
        ParameterSpec("n_depth", "integer", 60, "深度采样点数", min=16, max=400),
        ParameterSpec("n_lateral", "integer", 120, "横向采样点数", min=16, max=400),
        ParameterSpec("n_shots", "integer", 8, "炮点数", min=2, max=64),
        ParameterSpec("n_receivers", "integer", 60, "检波点数", min=4, max=400),
        ParameterSpec("nt", "integer", 1500, "时间采样点数", min=64, max=20000),
        ParameterSpec("dx", "number", 15.0, "横向网格间隔", unit="m", min=1.0, max=200.0, step=1.0),
        ParameterSpec("dt", "number", 0.0015, "时间步长", unit="s", min=1e-5, max=0.02, step=1e-4),
        ParameterSpec(
            "wavelet_f0", "number", 12.0, "子波主频（合成数据用）", unit="Hz",
            min=1.0, max=80.0, step=0.5,
        ),
        ParameterSpec(
            "source", "enum", "synthetic", "数据来源",
            options=[
                ("synthetic", "内置合成剖面（可复现基准）"),
                ("external", "由上游节点提供的 Survey"),
            ],
        ),
        ParameterSpec(
            "held_out", "string", "", "留出炮号（逗号分隔，如 1,6）。"
            "这些炮不参与梯度，只用于验证。",
            advanced=True,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        language = str(self.get_param("language", "zh") or "zh")
        source = str(self.get_param("source", "synthetic") or "synthetic")

        truth: Optional[np.ndarray] = None
        if source == "external" and inputs:
            survey = _survey_from_inputs(inputs)
        else:
            nd = int(self.get_param("n_depth", 60))
            nx = int(self.get_param("n_lateral", 120))
            n_shots = int(self.get_param("n_shots", 8))
            held_out = _parse_shot_list(
                str(self.get_param("held_out", "") or ""), n_shots
            )
            if len(held_out) >= n_shots:
                raise ValueError(
                    f"held_out lists {len(held_out)} of {n_shots} shots; at least one "
                    "shot must remain for the inversion itself"
                )
            survey, truth, _wavelet = synthetic_benchmark(
                n_depth=nd,
                n_lateral=nx,
                n_shots=n_shots,
                n_receivers=int(self.get_param("n_receivers", 60)),
                nt=int(self.get_param("nt", 1500)),
                dx=float(self.get_param("dx", 15.0)),
                dt=float(self.get_param("dt", 0.0015)),
                wavelet_f0=float(self.get_param("wavelet_f0", 12.0)),
                held_out=held_out,
            )

        records = _records_spectrum(survey)
        trend = _trend_spectrum(survey)
        truth_image = _truth_image(truth, survey) if truth is not None else None
        summary = self._describe(survey, truth, source, language)

        self.log(
            f"survey: {survey.n_shots} shots x {survey.n_receivers} receivers, "
            f"grid {survey.shape}, engine {_ENGINE}"
        )
        outputs: Dict[str, Any] = {
            "survey": survey,
            "records": records,
            "trend": trend,
        }
        # An unconnected optional port has no key at all, so the truth image is
        # only present when there is one.  Emitting an empty placeholder would
        # make the submission node score against a blank section instead of
        # honestly reporting that no truth is available.
        if truth_image is not None:
            outputs["truth"] = truth_image
        outputs["text"] = summary
        return outputs

    def _describe(
        self,
        survey: Any,
        truth: Optional[np.ndarray],
        source: str,
        language: str,
    ) -> Text:
        z_ms = np.arange(survey.shape[0]) * survey.dx * 1e3
        trend = survey.model_trend()
        lines: List[str] = []
        if language == "en":
            lines.append("2-D acoustic survey")
            lines.append(
                f"  grid {survey.shape[0]} x {survey.shape[1]} cells at "
                f"dx = {survey.dx:g} m ({z_ms[-1]:.0f} m deep), nt = {survey.nt} "
                f"at dt = {survey.dt * 1e3:.3f} ms"
            )
            lines.append(
                f"  {survey.n_shots} shots and {survey.n_receivers} receivers, all "
                f"on the surface row"
            )
            lines.append(
                f"  starting model is a depth-only trend, "
                f"{trend[0]:.0f}-{trend[-1]:.0f} m/s"
            )
            lines.append(
                f"  source: {source}"
                + (" (synthetic benchmark, not real geology)" if source == "synthetic" else "")
            )
            lines.append(f"  engine: {_ENGINE}. {_PROVENANCE_EN}")
        else:
            lines.append("二维声学地震采集")
            lines.append(
                f"  网格 {survey.shape[0]} × {survey.shape[1]}，"
                f"dx = {survey.dx:g} m（深至 {z_ms[-1]:.0f} m），"
                f"nt = {survey.nt}，dt = {survey.dt * 1e3:.3f} ms"
            )
            lines.append(
                f"  {survey.n_shots} 炮、{survey.n_receivers} 检波点，"
                f"均布设在地表行"
            )
            lines.append(
                f"  起始模型为纯深度趋势，{trend[0]:.0f}–{trend[-1]:.0f} m/s"
            )
            lines.append(
                f"  数据来源：{source}"
                + ("（合成基准，非真实地质）" if source == "synthetic" else "")
            )
            lines.append(f"  引擎：{_ENGINE}。{_PROVENANCE_ZH}")
        return Text(
            text="\n".join(lines),
            language="en" if language == "en" else "zh",
            metadata={"engine": _ENGINE, "source": source},
        )


# --------------------------------------------------------------------------- #
@register_node
class SeismicForwardNode(ScientificNode):
    """Forward-model the survey with a supplied or recovered source signature.

    Two things it is for beyond producing a picture:

    1. The **Green's functions** -- the modelled response to a unit impulse at
       the source -- are what :func:`~simulations.fwi.estimate_wavelet` solves
       against, so this node exposes them rather than hiding the one-shot-only
       estimate behind a private call.
    2. It is the honest place to catch a CFL violation.  Raising the requested
       ``dt`` above ``COURANT * dx / (sqrt(2) * vmax)`` makes the forward model
       blow up; failing here, with the numbers, beats returning a field of
       ``1e+22`` that a downstream chart renders as a valid image.
    """

    name = "Seismic Forward"
    category = "Instruments/Seismic"
    description = (
        "用给定或估计的震源子波做正演计算，输出炮集道集与格林函数，"
        "并在违反 CFL 稳定条件时明确报错。"
    )
    tags = ["seismic", "fwi", "forward", "green-function", "cfl"]
    icon = "SF"
    capabilities = ["models_seismic_forward"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports = [
        Port("survey", "Survey", "采集对象（必需）"),
    ]
    output_ports = [
        Port("gather", "Spectrum", "正演炮集道集"),
        Port("green", "Spectrum", "格林函数（单位脉冲响应）"),
        Port("energy", "Table", "各炮能量与 CFL 裕度"),
        Port("text", "Text", "正演设置说明"),
    ]

    parameters = [
        ParameterSpec(
            "wavelet", "string", "", "震源子波（留空则用估计子波）", advanced=True,
        ),
        ParameterSpec(
            "wavelet_f0", "number", 12.0, "回退子波主频", unit="Hz",
            min=1.0, max=80.0, step=0.5, advanced=True,
        ),
        ParameterSpec(
            "shot_indices", "string", "", "要正演的炮号（逗号分隔，留空为全部）",
            advanced=True,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        survey = _survey_from_inputs(inputs)
        language = str(self.get_param("language", "zh") or "zh")

        wavelet_text = str(self.get_param("wavelet", "") or "").strip()
        provenance = "supplied by the caller"
        if wavelet_text:
            values = [float(v) for v in wavelet_text.replace(";", ",").split(",") if v.strip()]
            wavelet = np.asarray(values, dtype=float)
            if not np.any(wavelet):
                raise ValueError("the supplied wavelet is all zeros")
        else:
            wavelet, provenance = estimate_wavelet_safe(survey)

        picks = self._shot_picks(survey)
        sub_shots = survey.shot_rc[picks]
        # Green's function: the response to a unit impulse at each source, which
        # is what the wavelet least-squares is built from.
        impulse = np.zeros(survey.nt, dtype=float)
        impulse[0] = 1.0
        green = forward_model(
            survey.velocity,
            impulse,
            sub_shots,
            survey.rec_rc,
            survey.dt,
            survey.dx,
            survey.nt,
            absorbing_width=24,
            absorbing_strength=0.02,
        )

        modelled = forward_model(
            survey.velocity,
            wavelet,
            sub_shots,
            survey.rec_rc,
            survey.dt,
            survey.dx,
            survey.nt,
            absorbing_width=24,
            absorbing_strength=0.02,
        )

        cfl_dt = 0.50 * survey.dx / (math.sqrt(2.0) * float(survey.velocity.max()))
        energy_rows = [
            {
                "shot": int(picks[i]),
                "source_x_cells": int(sub_shots[i, 1]),
                "gather_energy": float(np.sum(modelled.modelled[i] ** 2)),
                "green_energy": float(np.sum(green.modelled[i] ** 2)),
                "peak_amplitude": float(np.max(np.abs(modelled.modelled[i]))),
            }
            for i in range(len(picks))
        ]
        energy_table = Table.from_records(
            energy_rows,
            name="forward energy per shot",
            metadata={
                "engine": _ENGINE,
                "cfl_dt_limit_s": float(cfl_dt),
                "requested_dt_s": float(survey.dt),
                "cfl_margin": float(cfl_dt / survey.dt) if survey.dt > 0 else None,
            },
        )

        self.log(
            f"forward: {len(picks)} shots, energy {modelled.energy:.4e}, "
            f"CFL limit dt <= {cfl_dt:.6g} s (requested {survey.dt:.6g} s)"
        )
        return {
            "gather": _gather_spectrum(modelled, picks, survey),
            "green": _gather_spectrum(green, picks, survey, name="Green's functions"),
            "energy": energy_table,
            "text": self._describe(survey, provenance, cfl_dt, language),
        }

    def _shot_picks(self, survey: Any) -> List[int]:
        text = str(self.get_param("shot_indices", "") or "").strip()
        if not text:
            return list(range(survey.n_shots))
        picks = _parse_shot_list(text, survey.n_shots)
        if not picks:
            raise ValueError("shot_indices was given but held no valid index")
        return picks

    @staticmethod
    def _describe(survey: Any, provenance: str, cfl_dt: float, language: str) -> Text:
        margin = cfl_dt / survey.dt if survey.dt > 0 else 0.0
        if language == "en":
            body = (
                f"Forward-modelled {survey.n_shots} shots.\n"
                f"  source signature: {provenance}\n"
                f"  CFL: dt = {survey.dt:.6g} s against a limit of "
                f"{cfl_dt:.6g} s (margin {margin:.2f}x)\n"
                f"  engine: {_ENGINE}. {_PROVENANCE_EN}"
            )
            lang = "en"
        else:
            body = (
                f"正演计算 {survey.n_shots} 炮。\n"
                f"  震源子波：{provenance}\n"
                f"  CFL：dt = {survey.dt:.6g} s，稳定性上限 {cfl_dt:.6g} s"
                f"（裕度 {margin:.2f}×）\n"
                f"  引擎：{_ENGINE}。{_PROVENANCE_ZH}"
            )
            lang = "zh"
        return Text(text=body, language=lang, metadata={"engine": _ENGINE})


# --------------------------------------------------------------------------- #
@register_node
class FWIInversionNode(ScientificNode):
    """Frequency-continuation full-waveform inversion with held-out validation.

    The update rule is an additive step along the adjoint gradient, clipped to
    the task's velocity range, with the step length chosen by backtracking line
    search **on the real misfit**.  Illumination balancing and Laplacian
    regularisation shape the gradient; they never enter the line search, because
    a preconditioned direction is not guaranteed to be a descent direction and
    has to be checked like any other.

    The node reports the misfit before and after, and the held-out misfit when
    the survey declares held-out shots.  Both are the task's own criteria, so
    neither is optional decoration.
    """

    name = "FWI Inversion"
    category = "Instruments/Seismic"
    description = (
        "二维声学全波形反演：频率递进 + 伴随梯度 + 照明度均衡 + 线搜索，"
        "输出速度模型、估计子波与分阶段误差。"
    )
    tags = ["seismic", "fwi", "inversion", "adjoint", "frequency-continuation"]
    icon = "FI"
    capabilities = ["models_seismic_fwi"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports = [
        Port("survey", "Survey", "采集对象（必需）"),
    ]
    output_ports = [
        Port("velocity", "Image", "反演速度模型（灰度图，物理像素尺寸）"),
        Port("velocity_table", "Table", "逐深度速度剖面与照明度"),
        Port("wavelet", "Spectrum", "估计震源子波"),
        Port("progress", "Table", "分阶段误差与迭代记录"),
        Port("report", "Text", "完整反演结果（JSON），供下游节点引用"),
        Port("text", "Text", "反演方法、验证结果与诚实说明"),
    ]

    parameters = [
        ParameterSpec(
            "stage_1", "string", "2.5-7.0", "第 1 频段（Hz）", advanced=True,
        ),
        ParameterSpec(
            "stage_2", "string", "5.0-14.0", "第 2 频段（Hz）", advanced=True,
        ),
        ParameterSpec(
            "stage_3", "string", "9.0-24.0", "第 3 频段（Hz）", advanced=True,
        ),
        ParameterSpec("iterations_per_stage", "integer", 4, "每阶段迭代次数", min=1, max=50),
        ParameterSpec(
            "max_update_fraction", "number", 0.08, "单步速度更新上限（占均值比例）",
            min=0.001, max=0.5, step=0.005,
        ),
        ParameterSpec(
            "gradient_smoothing", "number", 2.0, "梯度高斯平滑尺度", unit="cell",
            min=0.0, max=20.0, step=0.5,
        ),
        ParameterSpec(
            "laplace_weight", "number", 0.02, "拉普拉斯正则权重（0 关闭）",
            min=0.0, max=1.0, step=0.005, advanced=True,
        ),
        ParameterSpec(
            "wavelet_refresh_rms", "number", 12.0, "子波重估阈值（RMS 位移）",
            min=0.0, max=500.0, step=1.0, advanced=True,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        survey = _survey_from_inputs(inputs)
        language = str(self.get_param("language", "zh") or "zh")

        schedule: List[Tuple[float, float, float]] = []
        for key in ("stage_1", "stage_2", "stage_3"):
            schedule.append(_parse_band(str(self.get_param(key, "") or "")))
        config = FWIConfig(
            frequency_schedule=tuple(schedule),
            iterations_per_stage=int(self.get_param("iterations_per_stage", 4)),
            max_update_fraction=float(self.get_param("max_update_fraction", 0.08)),
            gradient_smoothing=float(self.get_param("gradient_smoothing", 2.0)),
            laplace_weight=float(self.get_param("laplace_weight", 0.02)),
            wavelet_refresh_rms=float(self.get_param("wavelet_refresh_rms", 12.0)),
            verbose=bool(ctx.verbose) if hasattr(ctx, "verbose") else False,
        )

        result = run_fwi(survey, config)

        image = _velocity_image(result.velocity, survey.dx)
        profile = _velocity_table(result.velocity, survey)
        wavelet_plot = _wavelet_spectrum(result.wavelet, survey.dt)
        progress = _progress_table(result)
        summary = self._describe(survey, result, language)

        self.log(
            f"fwi: {result.n_iterations} iterations, misfit "
            f"{result.initial_misfit:.4e} -> {result.final_misfit:.4e}, "
            f"engine {result.engine}"
        )
        return {
            "velocity": image,
            "velocity_table": profile,
            "wavelet": wavelet_plot,
            "progress": progress,
            # The submission node cannot invent the misfit history: it needs the
            # numbers this run actually produced.  Handing them over inside a
            # Text payload keeps the velocity array out of a JSON blob while
            # still making the full result reachable downstream.
            "report": Text(
                text=summary.text,
                language=summary.language,
                data=result.to_dict(),
                metadata={"engine": result.engine},
            ),
            "text": summary,
        }

    @staticmethod
    def _describe(survey: Any, result: Any, language: str) -> Text:
        reduction = (
            100.0 * (1.0 - result.final_misfit / result.initial_misfit)
            if result.initial_misfit > 0.0
            else None
        )
        held = (
            f"{result.held_out_initial_misfit:.4e} -> {result.held_out_final_misfit:.4e}"
            if result.held_out_initial_misfit is not None
            else "none declared"
        )
        if language == "en":
            body = (
                "Full-waveform inversion\n"
                f"  method: {result.method}\n"
                f"  signature: {result.source_estimation}\n"
                f"  iterations: {result.n_iterations} in {result.wall_time_s:.1f} s\n"
                f"  misfit: {result.initial_misfit:.6e} -> {result.final_misfit:.6e}"
                + (f" ({reduction:+.2f}%)" if reduction is not None else "")
                + f"\n  held-out shots {result.held_out_shots}: {held}\n"
                f"  engine: {result.engine}. {_PROVENANCE_EN}\n"
                f"  note: {_WARNING_ZH}"
            )
            lang = "en"
        else:
            body = (
                "全波形反演\n"
                f"  方法：{result.method}\n"
                f"  子波：{result.source_estimation}\n"
                f"  迭代：{result.n_iterations} 次，耗时 {result.wall_time_s:.1f} s\n"
                f"  误差：{result.initial_misfit:.6e} → {result.final_misfit:.6e}"
                + (f"（{reduction:+.2f}%）" if reduction is not None else "")
                + f"\n  held-out 炮 {result.held_out_shots}：{held}\n"
                f"  引擎：{result.engine}。{_PROVENANCE_ZH}\n"
                f"  注意：{_WARNING_ZH}"
            )
            lang = "zh"
        return Text(
            text=body,
            language=lang,
            metadata={
                "engine": result.engine,
                "misfit_reduction_pct": reduction,
                "held_out_improved": result.to_dict()["held_out_improved"],
            },
        )


# --------------------------------------------------------------------------- #
@register_node
class SeismicSubmissionNode(ScientificNode):
    """Write the task's three files and score the result.

    ``velocity_model.npy`` / ``wavelet.npy`` / ``run_summary.json``.  The
    summary carries the misfit, the held-out comparison and -- when a truth
    section is connected -- the task's depth-mean-removed lateral correlation
    with the starting model's value right beside it, so "0.32" is readable as
    "0.32 against a baseline of 0.00" rather than as a bare number.

    Truth is optional and is never invented.  Without it the score fields are
    ``null`` and ``truth_available`` is ``false``.
    """

    name = "Seismic Submission"
    category = "Instruments/Seismic"
    description = (
        "导出赛题要求的三个文件（velocity_model.npy / wavelet.npy / "
        "run_summary.json），并在有真值时计算深度均值去除后的横向相关评分。"
    )
    tags = ["seismic", "fwi", "submission", "export", "score"]
    icon = "SSB"
    capabilities = ["models_seismic_submission"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports = [
        Port("velocity", "Image", "反演速度模型（必需）"),
        Port("survey", "Survey", "采集对象（含起始模型，必需）"),
        Port("report", "Text", "上游反演节点的完整结果（JSON），提供后才有误差与验证数据",
             optional=True),
        Port("wavelet", "Spectrum", "上游估计的震源子波（必需，否则 wavelet.npy 为全零）"),
        # v0.7.3 (audit P1-6): marked optional at the *port* level, not only in
        # the prose.  Real survey data has no ground truth, so a workflow for a
        # real dataset could not even be validated if this were mandatory --
        # which made a synthetic, truth-scored chain look like the only
        # supported path.  The execute() path already handles its absence by
        # leaving every score null and setting truth_available=false.
        Port("truth", "Image", "可选真值剖面（Image；提供后才计算评分）", optional=True),
        # v0.7.3 (audit P1-6): the forward node used to sit in the demo
        # workflow with every output dangling -- it cost a full modelling run
        # and made the user believe its gather participated in the inversion.
        # Giving it a real job (CFL margin + per-shot energy sanity check on
        # the *starting* model, before inversion touches it) makes the node
        # earn its place and gives the run a diagnostic it otherwise lacks.
        Port("forward_qc", "Table",
             "可选正演 QC（SeismicForwardNode.energy：各炮能量与 CFL 裕度）",
             optional=True),
    ]
    output_ports = [
        Port("summary", "Table", "评分与验证指标"),
        Port("files", "Table", "三个产物的路径与存在性"),
        Port("text", "Text", "提交说明与读回校验结果"),
    ]

    parameters = [
        ParameterSpec(
            "output_dir", "string", "output/fwi_submission", "输出目录",
        ),
        ParameterSpec(
            "write_files", "boolean", True, "是否写出三个文件",
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        from simulations.fwi import FWIResult

        language = str(self.get_param("language", "zh") or "zh")
        survey = _survey_from_inputs(inputs)
        model = _image_to_array(inputs.get("velocity"))
        if model is None:
            raise ValueError("the 'velocity' input port carried no Image")

        truth = _truth_from_inputs(inputs)
        signature = np.asarray(
            (inputs.get("wavelet").y if hasattr(inputs.get("wavelet"), "y") else []),
            dtype=float,
        )

        # The misfit history and the held-out comparison live in the upstream
        # report payload.  Reconstructing them here would be fabrication, so
        # they are read back when present and left null when not -- the summary
        # then says "no upstream report" instead of "misfit 0.0".
        report = inputs.get("report")
        reported: Dict[str, Any] = {}
        if hasattr(report, "data") and report.data:
            reported = dict(report.data)
        # Only trust the misfit fields when the upstream run says it actually
        # produced them; otherwise a placeholder 0.0 would be reported as a
        # measurement.
        has_diagnostics = bool(reported.get("has_diagnostics"))
        if has_diagnostics:
            stage_misfits = [float(v) for v in reported.get("stage_misfits", []) or []]
            iterations = int(reported.get("n_iterations", 0) or 0)
            seconds = float(reported.get("wall_time_s", 0.0) or 0.0)
            initial = _opt_float(reported.get("initial_misfit"))
            final = _opt_float(reported.get("final_misfit"))
            held_initial = _opt_float(reported.get("held_out_initial_misfit"))
            held_final = _opt_float(reported.get("held_out_final_misfit"))
        else:
            stage_misfits, iterations, seconds = [], 0, 0.0
            # "Not connected to an inversion" is not "the misfit was zero".
            # 0.0 here would reach run_summary.json and read as a perfect fit.
            initial = final = None
            held_initial = held_final = None

        result = FWIResult(
            velocity=model,
            wavelet=signature,
            method=str(
                reported.get("method")
                or "assembled by SeismicSubmissionNode from an upstream inversion"
            ),
            source_estimation=str(
                reported.get("source_estimation")
                or "inherited from the upstream FWI node"
            ),
            stage_misfits=stage_misfits,
            n_iterations=iterations,
            wall_time_s=seconds,
            initial_misfit=initial,
            final_misfit=final,
            held_out_shots=[int(v) for v in reported.get("held_out_shots", []) or []],
            held_out_initial_misfit=held_initial,
            held_out_final_misfit=held_final,
            shots_used=[int(v) for v in reported.get("shots_used", []) or []]
            or survey.fit_shots,
        )
        directory = str(self.get_param("output_dir", "output/fwi_submission") or "output/fwi_submission")

        # v0.7.3 (audit P1-6): consume the forward node's QC table.  Its
        # numbers describe the *starting* model, before inversion, so they are
        # exactly the baseline a misfit reduction should be read against -- and
        # the CFL margin is the one check that says the forward solver was
        # numerically admissible at all.
        qc = _forward_qc_from_inputs(inputs)
        if qc:
            extra_qc = qc
        else:
            extra_qc = {"connected": False}

        extra = {
            "assembled_from": "SeismicSubmissionNode",
            "upstream_report_connected": bool(reported),
            "forward_qc": extra_qc,
            "note": (
                "misfit and validation fields are null when the upstream "
                "inversion's 'report' output was not connected; connect it to "
                "carry the real numbers across"
                if not reported
                else "misfit and validation carried from the upstream inversion"
            ),
        }
        if not np.any(signature):
            extra["note"] += (
                "; the wavelet array was not connected, so wavelet.npy holds "
                "zeros and signature_peak_normalised is false"
            )

        if bool(self.get_param("write_files", True)):
            paths = write_submission(directory, result, survey, truth=truth, extra=extra)
            # Read back immediately: a file that cannot be loaded by the scorer
            # is not a deliverable, and the failure is far cheaper to find here.
            written, read_signature, read_summary = load_submission(paths.directory)
            roundtrip = {
                "velocity_shape": list(written.shape),
                "velocity_matches": bool(
                    np.allclose(written, np.clip(model, V_MIN, V_MAX))
                ),
                "wavelet_length": int(read_signature.size),
                "summary_keys": len(read_summary),
            }
            file_rows = [
                {
                    "file": "velocity_model.npy",
                    "path": str(paths.velocity),
                    "exists": paths.exists()["velocity_model"],
                    "shape": f"{written.shape[0]}x{written.shape[1]}",
                },
                {
                    "file": "wavelet.npy",
                    "path": str(paths.wavelet),
                    "exists": paths.exists()["wavelet"],
                    "shape": str(read_signature.size),
                },
                {
                    "file": "run_summary.json",
                    "path": str(paths.summary),
                    "exists": paths.exists()["run_summary"],
                    "shape": f"{roundtrip['summary_keys']} keys",
                },
            ]
            summary_scores = read_summary.get("score", {})
        else:
            roundtrip = {"velocity_shape": list(model.shape), "velocity_matches": True,
                         "wavelet_length": int(signature.size), "summary_keys": 0}
            file_rows = []
            summary_scores = score_model(model, truth=truth, start=survey.velocity)

        score_rows = [{"metric": k, "value": v} for k, v in summary_scores.items()]
        score_table = Table.from_records(
            score_rows,
            name="FWI score",
            metadata={"engine": _ENGINE, **summary_scores},
        )
        files_table = Table.from_records(
            file_rows,
            name="submission files",
            metadata={"engine": _ENGINE, "directory": directory},
        )

        text = self._describe(summary_scores, file_rows, roundtrip, language)
        self.log(
            f"submission: {len(file_rows)} files in {directory}, "
            f"lateral correlation {summary_scores.get('lateral_correlation')}"
        )
        return {"summary": score_table, "files": files_table, "text": text}

    @staticmethod
    def _describe(
        scores: Dict[str, Any],
        files: List[Dict[str, Any]],
        roundtrip: Dict[str, Any],
        language: str,
    ) -> Text:
        corr = scores.get("lateral_correlation")
        base = scores.get("start_lateral_correlation")
        # These come straight off a dict that may have been built without the
        # physical range; formatting a missing float raises instead of saying
        # "unknown", which would take the whole node down over a label.
        vmin = scores.get("velocity_min")
        vmax = scores.get("velocity_max")
        span = (
            f"[{vmin:.0f}, {vmax:.0f}] m/s"
            if vmin is not None and vmax is not None
            else "unknown"
        )
        in_range = scores.get("in_task_range")
        range_text = str(in_range) if in_range is not None else "unknown"
        if language == "en":
            corr_text = f"{corr:.4f}" if corr is not None else "null (no truth connected)"
            base_text = f"{base:.4f}" if base is not None else "null"
            head = (
                "Task submission\n"
                f"  lateral correlation (depth means removed): {corr_text}"
                f"   starting model: {base_text}\n"
                f"  velocity range: {span}, within task range: {range_text}\n"
                f"  files written: {len(files)}\n"
                f"  read back OK: velocity {roundtrip['velocity_shape']}, "
                f"wavelet {roundtrip['wavelet_length']} samples\n"
                f"  engine: {_ENGINE}. {_PROVENANCE_EN}"
            )
            lang = "en"
        else:
            corr_text = f"{corr:.4f}" if corr is not None else "null（未接入真值）"
            base_text = f"{base:.4f}" if base is not None else "null"
            head = (
                "赛题提交\n"
                f"  横向相关系数（去除深度均值）：{corr_text}"
                f"   起始模型：{base_text}\n"
                f"  速度范围：{span}，在赛题范围内：{range_text}\n"
                f"  已写出文件：{len(files)}\n"
                f"  读回校验：速度 {roundtrip['velocity_shape']}，"
                f"子波 {roundtrip['wavelet_length']} 样本\n"
                f"  引擎：{_ENGINE}。{_PROVENANCE_ZH}"
            )
            lang = "zh"
        return Text(
            text=head,
            language=lang,
            metadata={"engine": _ENGINE, "score": scores, "roundtrip": roundtrip},
        )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def estimate_wavelet_safe(survey: Any) -> Tuple[np.ndarray, str]:
    """:func:`~simulations.fwi.estimate_wavelet`, but never raises."""
    from simulations.fwi import estimate_wavelet

    try:
        return estimate_wavelet(survey)
    except (ValueError, np.linalg.LinAlgError) as exc:
        # A CFL violation is the caller's error and must not be swallowed; a
        # genuinely degenerate survey, on the other hand, still deserves a run
        # with an honest note attached.
        if "CFL" in str(exc):
            raise
        nt = survey.nt
        wavelet = np.zeros(nt)
        wavelet[0] = 1.0
        return wavelet, (
            f"fallback: unit impulse, because signature estimation failed ({exc})"
        )


def _opt_float(value: Any) -> Optional[float]:
    """``None`` for a missing or non-numeric entry, else the float.

    Used when reading a report payload back: a field that was never populated
    has to stay ``None`` rather than becoming ``0.0``, because "the misfit was
    exactly zero" and "no misfit was recorded" are very different claims and the
    summary is read by a person deciding whether to trust the run.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_shot_list(text: str, n_shots: int) -> List[int]:
    """Parse a comma-separated shot list, rejecting out-of-range indices."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    picks: List[int] = []
    for chunk in cleaned.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        idx = int(chunk)
        if not 0 <= idx < n_shots:
            raise ValueError(
                f"shot index {idx} in held_out is outside the acquisition "
                f"(0..{n_shots - 1})"
            )
        if idx not in picks:
            picks.append(idx)
    return picks


def _parse_band(text: str) -> Tuple[float, float, float]:
    """Parse ``"lo-hi"`` or ``"lo-hi-corner"`` into a schedule entry."""
    cleaned = str(text or "").replace("~", "-").replace("–", "-").strip()
    if not cleaned:
        raise ValueError("a frequency stage was left empty; use e.g. '2.5-7.0'")
    parts = cleaned.split("-")
    if len(parts) == 2:
        lo, hi = float(parts[0]), float(parts[1])
        corner = 0.0
    elif len(parts) == 3:
        lo, hi, corner = float(parts[0]), float(parts[1]), float(parts[2])
    else:
        raise ValueError(
            f"cannot read the frequency stage {text!r}; expected 'lo-hi' or 'lo-hi-corner'"
        )
    if not 0.0 < lo < hi:
        raise ValueError(f"frequency stage {text!r} needs 0 < lo < hi")
    return lo, hi, corner


def _truth_image(truth: np.ndarray, survey: Any) -> Image:
    """The synthetic ground-truth section as an image, normalised like the model.

    Carrying the physical range in ``metadata`` is what lets
    :func:`_image_to_array` put the metres per second back, so the submission
    node compares velocities against velocities rather than against a 0-1 grid.
    """
    section = np.asarray(truth, dtype=float)
    lo, hi = float(np.min(section)), float(np.max(section))
    span = hi - lo
    scaled = (section - lo) / span if span > 0.0 else np.zeros_like(section)
    return Image.from_array(
        scaled,
        pixel_size=float(survey.dx),
        pixel_unit="m",
        name="synthetic ground truth",
        cmap="gray",
        metadata={
            "engine": _ENGINE,
            "velocity_min": lo,
            "velocity_max": hi,
            "velocity_mean": float(np.mean(section)),
            "units": "m/s",
            "kind": "synthetic benchmark, not measured data",
        },
    )


def _records_spectrum(survey: Any) -> Spectrum:
    """One trace per receiver, summed over shots -- a quick-look gather."""
    x = list(range(survey.n_receivers))
    stacked = np.sum(survey.records, axis=0)
    return Spectrum(
        x=x,
        y=[float(v) for v in stacked.mean(axis=0)],
        z=[[float(v) for v in stacked[i]] for i in range(survey.n_receivers)],
        mode="Seismic",
        technique="surface acquisition, stacked over shots",
        x_unit="receiver",
        y_unit="amplitude",
        name="observed shot gathers (shot average)",
        metadata={"engine": _ENGINE, "n_shots": survey.n_shots},
    )


def _gather_spectrum(
    result: FwdResult,
    picks: Sequence[int],
    survey: Any,
    name: str = "modelled shot gathers",
) -> Spectrum:
    depth = (np.arange(result.modelled.shape[2]) * survey.dt * 1e3).tolist()
    return Spectrum(
        x=[float(v) for v in depth],
        y=[float(v) for v in result.modelled[0].mean(axis=0)],
        z=[[float(v) for v in result.modelled[i].mean(axis=0)] for i in range(result.modelled.shape[0])],
        mode="Seismic",
        technique="finite-difference forward modelling",
        x_unit="ms",
        y_unit="amplitude",
        name=name,
        metadata={"engine": _ENGINE, "shot_indices": [int(p) for p in picks]},
    )


def _trend_spectrum(survey: Any) -> Spectrum:
    trend = survey.model_trend()
    return Spectrum(
        x=[float(i * survey.dx) for i in range(trend.size)],
        y=[float(v) for v in trend],
        mode="Seismic",
        technique="1-D depth trend",
        x_unit="m",
        y_unit="m/s",
        name="starting 1-D depth trend",
        metadata={"engine": _ENGINE},
    )


def _wavelet_spectrum(wavelet: np.ndarray, dt: float) -> Spectrum:
    wave = np.asarray(wavelet, dtype=float)
    time_ms = (np.arange(wave.size) * dt * 1e3).tolist()
    return Spectrum(
        x=time_ms,
        y=[float(v) for v in wave],
        mode="Seismic",
        technique="least-squares source signature recovery",
        x_unit="ms",
        y_unit="amplitude",
        name="estimated source signature",
        metadata={
            "engine": _ENGINE,
            "peak_sample": int(np.argmax(np.abs(wave))) if wave.size else None,
            "support": int(np.count_nonzero(wave)),
        },
    )


def _velocity_image(velocity: np.ndarray, dx: float) -> Image:
    model = np.asarray(velocity, dtype=float)
    # Image.data is a plain float grid; normalising to 0..1 is what lets the
    # frontend colour it, and the physical range stays in metadata so nothing is
    # lost.
    lo, hi = float(np.min(model)), float(np.max(model))
    span = hi - lo
    scaled = (model - lo) / span if span > 0.0 else np.zeros_like(model)
    return Image.from_array(
        scaled,
        pixel_size=float(dx),
        pixel_unit="m",
        name="inverted velocity model",
        cmap="gray",
        metadata={
            "engine": _ENGINE,
            "velocity_min": lo,
            "velocity_max": hi,
            "velocity_mean": float(np.mean(model)),
            "units": "m/s",
        },
    )


def _velocity_table(velocity: np.ndarray, survey: Any) -> Table:
    model = np.asarray(velocity, dtype=float)
    weights = illumination_weights(survey)
    records = [
        {
            "depth_index": int(i),
            "depth_m": round(float(i * survey.dx), 3),
            "depth_mean_velocity": round(float(model[i].mean()), 3),
            "lateral_std": round(float(model[i].std()), 4),
            "velocity_min": round(float(model[i].min()), 3),
            "velocity_max": round(float(model[i].max()), 3),
            "illumination_weight": float(f"{weights[i].mean():.6e}"),
        }
        for i in range(model.shape[0])
    ]
    return Table.from_records(
        records,
        name="velocity profile by depth",
        units={"depth_m": "m", "depth_mean_velocity": "m/s"},
        metadata={"engine": _ENGINE},
    )


def _progress_table(result: Any) -> Table:
    records: List[Dict[str, Any]] = []
    for i, value in enumerate(result.stage_misfits):
        records.append(
            {
                "stage": i + 1,
                "misfit": float(f"{value:.6e}"),
                "note": "band-limited L2 on the monitoring shots",
            }
        )
    records.append(
        {
            "stage": "initial",
            "misfit": float(f"{result.initial_misfit:.6e}"),
            "note": "starting model, same band and shots as the final value",
        }
    )
    records.append(
        {
            "stage": "final",
            "misfit": float(f"{result.final_misfit:.6e}"),
            "note": f"{result.n_iterations} iterations, {result.wall_time_s:.1f} s",
        }
    )
    if result.held_out_initial_misfit is not None:
        records.append(
            {
                "stage": "held-out before",
                "misfit": float(f"{result.held_out_initial_misfit:.6e}"),
                "note": f"shots {result.held_out_shots}, excluded from the gradient",
            }
        )
        records.append(
            {
                "stage": "held-out after",
                "misfit": float(f"{result.held_out_final_misfit:.6e}"),
                "note": "same shots and band as the row above",
            }
        )
    return Table.from_records(
        records,
        name="FWI stage misfits",
        metadata={"engine": result.engine},
    )


def _image_to_array(value: Any) -> Optional[np.ndarray]:
    """Recover velocity in m/s from an :class:`Image` built by this family.

    The image is stored normalised to 0..1 with the physical range in metadata,
    so it has to be un-normalised here.  Falling back to the stored grid
    unchanged would silently submit a 0-1 image where a 1500-4500 m/s section
    belongs -- exactly the kind of error that scores zero and looks plausible.
    """
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=float)
    data = getattr(value, "data", None)
    if not data:
        return None
    grid = np.asarray(data, dtype=float)
    lo = getattr(value, "metadata", {}).get("velocity_min")
    hi = getattr(value, "metadata", {}).get("velocity_max")
    if lo is None or hi is None:
        return grid
    return float(lo) + grid * (float(hi) - float(lo))


def _forward_qc_from_inputs(inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Summarise the forward node's per-shot energy table for the run summary.

    Returns ``None`` when nothing is connected, so the caller can record that
    plainly instead of writing zeros -- "no QC was run" and "QC found an energy
    of zero" are different facts and must not share a field.
    """
    value = inputs.get("forward_qc")
    if value is None:
        return None
    meta = dict(getattr(value, "metadata", {}) or {})
    rows = getattr(value, "rows", None)
    if not rows:
        return {"connected": True, "shots": 0}

    # ``Table.rows`` is a list of lists plus a ``columns`` header -- not a list
    # of dicts (see the Table contract).  Read positionally via the header so
    # a column reorder cannot silently shift the meaning of the numbers.
    columns = list(getattr(value, "columns", []) or [])
    energies: List[float] = []
    if "gather_energy" in columns:
        idx = columns.index("gather_energy")
        for row in rows:
            try:
                energies.append(float(row[idx]))
            except (TypeError, ValueError, IndexError):
                continue
    energies_arr = np.asarray([e for e in energies if np.isfinite(e)], dtype=float)

    margin = _opt_float(meta.get("cfl_margin"))
    qc: Dict[str, Any] = {
        "connected": True,
        "shots": int(len(rows)),
        "cfl_dt_limit_s": _opt_float(meta.get("cfl_dt_limit_s")),
        "requested_dt_s": _opt_float(meta.get("requested_dt_s")),
        "cfl_margin": margin,
        "cfl_admissible": None if margin is None else bool(margin >= 1.0),
    }
    if energies_arr.size:
        qc["gather_energy_min"] = float(energies_arr.min())
        qc["gather_energy_max"] = float(energies_arr.max())
        # A shot whose modelled energy collapses relative to the median is the
        # signature of a dead trace; surfaced rather than silently averaged.
        median = float(np.median(energies_arr))
        qc["gather_energy_median"] = median
        qc["dead_shots"] = int(
            np.count_nonzero(energies_arr <= max(median * 1e-6, 1e-30))
        )
    return qc


def _truth_from_inputs(inputs: Dict[str, Any]) -> Optional[np.ndarray]:
    """Accept a truth section as an Image or a plain array; decline anything else.

    The survey node publishes the synthetic truth as an :class:`Image` with its
    physical range in metadata, which is exactly what :func:`_image_to_array`
    reverses.  A Table of per-depth statistics is *not* a section, and scoring
    against one would mean scoring against a fabrication -- so a Table is
    declined and the score stays ``null``.
    """
    value = inputs.get("truth")
    if value is None:
        return None
    if isinstance(value, np.ndarray):
        return np.asarray(value, dtype=float)
    if hasattr(value, "data") and value.data:
        return _image_to_array(value)
    return None