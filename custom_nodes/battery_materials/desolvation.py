"""Pre-desolvation in hard-carbon nanopores: size-sieving node family (v0.7.3).

Wraps :mod:`models.desolvation` -- the analytical surrogates calibrated on

    Lu, Yang et al., *Consummating ion desolvation in hard carbon anodes for
    reversible sodium storage*, Nat. Commun. **15**, 3497 (2024),
    doi:10.1038/s41467-024-47522-y

-- into the workflow graph.

Three nodes are exposed so a workflow can either see the whole mechanism at once
or pick the stage it cares about:

``DesolvationSieveNode``      Fig. 2d/2e  -- sizes, blocking, barriers, the curve
``ElectrolyteAgingNode``      Fig. 1      -- impedance / OCP / ICE vs rest time
``DoubleSEIEnergeticsNode``   Fig. 4h/4i  -- S-SEI vs I-SEI activation energies

Every node records which engine answered in ``metadata["engine"]``.  These are
closed-form surrogates, **not** VASP NEB, not COMPASS III MD and not XPS
acquisition; the summaries say so in the same words a user sees on the canvas,
because a plot that looks like Fig. 2e but was not computed by NEB must not be
mistaken for one.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

from models.desolvation import (
    ACTIVATION_ENERGIES_KJ,
    BARRIER_AGG_EV,
    BARRIER_CIP_EV,
    ICE_AT_10D,
    ICE_AT_12H,
    MAX_COORDINATION,
    PAPER_PORE_DIAMETER_A,
    R_FORTY_H,
    R_FOUR_H,
    TAU_FILL_H,
    activation_energy,
    aging_curves,
    arrhenius_series,
    barrier_curve,
    lumo_shift,
    rdf_na_p,
    sieving,
)
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

__all__ = [
    "DesolvationSieveNode",
    "ElectrolyteAgingNode",
    "DoubleSEIEnergeticsNode",
    "PreDesolvationMechanismNode",
]

_ENGINE = "internal:analytical-surrogate"
_CITATION = (
    "Lu, Yang et al., Nat. Commun. 15, 3497 (2024), "
    "doi:10.1038/s41467-024-47522-y"
)

_PROVENANCE_ZH = (
    "解析代理模型，非第一性原理。尺寸与能垒取自论文实测值，"
    "曲线形状为建模选择。/ Analytical surrogate, not first-principles: "
    "sizes and barriers are the paper's measured values, curve shapes are "
    "a modelling choice."
)


@register_node
class DesolvationSieveNode(ScientificNode):
    """Size-sieving of solvation structures through a hard-carbon nanopore.

    Reproduces Fig. 2d (characteristic sizes) and Fig. 2e (crossing barriers):
    solvated cations far larger than the throat are rejected, the survivors
    arrive in an aggregated state, which is the paper's pre-desolvation
    mechanism.

    The barrier model is *derived* from the two reported barriers rather than
    tuned to them, so CIP reproduces 0.50 eV and AGG 1.10 eV exactly.  A species
    too large for the throat is reported with ``blocked=True`` and an infinite
    barrier -- never a large finite number that would plot like a weak barrier.

    Outputs
    -------
    ``sieve``    Table -- one row per solvation state
    ``barrier``  Spectrum -- crossing energy profiles (Fig. 2e)
    ``rdf``      Spectrum -- Na-P radial distribution, bulk vs in-pore
    ``text``     Text   -- mechanism summary with the honest provenance note
    """

    name = "Pre-desolvation Sieve"
    category = "Instruments/Electrochemistry"
    description = (
        "硬碳纳米孔的尺寸筛分模型：按溶剂化结构特征尺寸判定能否穿过孔口，"
        "给出过孔能垒曲线与孔内 Na–P 配位（Fig. 2d/2e + 补充 Fig. 9）。"
    )
    tags = ["hard-carbon", "desolvation", "solvation", "sei", "sodium", "pore"]
    icon = "DS"
    capabilities = ["models_nanopore_desolvation"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = []
    output_ports = [
        Port("sieve", "Table", "各溶剂化结构的尺寸、反射系数与过孔能垒"),
        Port("barrier", "Spectrum", "过孔相对能量曲线（Fig. 2e）"),
        Port("rdf", "Spectrum", "Na–P 径向分布：体相 vs 孔内"),
        Port("text", "Text", "预脱溶剂机理说明与数据出处"),
    ]

    parameters = [
        ParameterSpec(
            "pore_diameter", "number", PAPER_PORE_DIAMETER_A,
            "孔口直径（论文实测约 4 Å，墨水瓶型）", unit="Å",
            min=2.0, max=20.0, step=0.1,
        ),
        ParameterSpec(
            "electrolyte", "enum", "ether", "电解液体系",
            options=[
                ("ether", "1 M NaPF6 in diglyme（醚系）"),
                ("ester", "1 M NaPF6 in EC/DEC（酯系）"),
            ],
        ),
        ParameterSpec(
            "concentration", "number", 1.0, "盐浓度", unit="mol/L",
            min=0.1, max=5.0, step=0.1,
        ),
        ParameterSpec(
            "dielectric", "number", 7.2, "介电常数（diglyme 约 7.2）",
            min=1.0, max=100.0, step=0.1, advanced=True,
        ),
        ParameterSpec(
            "curve_points", "integer", 61, "能垒曲线采样点数", min=11, max=401,
            advanced=True,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        pore = float(self.get_param("pore_diameter", PAPER_PORE_DIAMETER_A))
        conc = float(self.get_param("concentration", 1.0))
        eps = float(self.get_param("dielectric", 7.2))
        points = int(self.get_param("curve_points", 61))
        language = str(self.get_param("language", "zh") or "zh")

        result = sieving(pore_diameter_a=pore)
        curve = barrier_curve(pore, n_points=points)
        rdf_bulk = rdf_na_p(conc, eps, confinement=False)
        rdf_pore = rdf_na_p(conc, eps, confinement=True)

        sieve_table = self._sieve_table(result)
        barrier_spectrum = self._barrier_spectrum(curve, pore)
        rdf_spectrum = self._rdf_spectrum(rdf_bulk, rdf_pore)
        summary = self._summarise(result, rdf_bulk, rdf_pore, pore, conc, language)

        self.log(
            f"sieve: admitted {result.admitted}, excluded {result.excluded}, "
            f"mean coordination {result.mean_coordination:.2f}, engine {_ENGINE}"
        )
        return {
            "sieve": sieve_table,
            "barrier": barrier_spectrum,
            "rdf": rdf_spectrum,
            "text": summary,
        }

    # -- output builders ---------------------------------------------------- #
    @staticmethod
    def _sieve_table(result: Any) -> Table:
        records: List[Dict[str, Any]] = []
        for state in result.states:
            records.append(
                {
                    "species": state.species,
                    "label": state.label,
                    "size_angstrom": round(state.size_a, 3),
                    "radius_ratio": round(state.radius_ratio, 4),
                    "reflection_sigma": round(state.reflection, 4),
                    "pf6_coordination": state.coordination,
                    "barrier_eV": None if state.blocked else round(state.barrier_ev, 4),
                    "blocked": state.blocked,
                    "passes": not state.blocked,
                }
            )
        # Table.rows is List[List[Any]]; from_records does the dict->list
        # projection and derives the column union.  Hand-building both invites
        # the two to drift apart.
        return Table.from_records(
            records,
            name="desolvation sieve",
            units={"size_angstrom": "Å", "barrier_eV": "eV"},
            metadata={"engine": _ENGINE, "citation": _CITATION},
        )

    @staticmethod
    def _barrier_spectrum(curve: Dict[str, List[List[float]]], pore: float) -> Spectrum:
        # Spectrum carries one trace in x/y and extra traces in z.  An infinite
        # barrier is dropped here and named in metadata, because a curve that
        # stops mid-axis would read as a weak barrier rather than as "cannot
        # pass".
        x = list(curve["coordinate"])
        traces: List[List[float]] = []
        names: List[str] = []
        omitted: List[str] = []
        for key, values in curve.items():
            if key == "coordinate":
                continue
            if any(not math.isfinite(v) for v in values):
                omitted.append(key)
                continue
            traces.append(list(values))
            names.append(key)
        meta = {
            "engine": _ENGINE,
            "citation": _CITATION,
            "pore_diameter_angstrom": pore,
            "calibration": "CIP 0.50 eV, AGG 1.10 eV (Fig. 2e, measured)",
            "note": _PROVENANCE_ZH,
            "series_names": names,
            "omitted": omitted,
        }
        primary = traces[0] if traces else [0.0] * len(x)
        return Spectrum(
            mode="Generic",
            x=[float(v) for v in x],
            y=[float(v) for v in primary],
            z=[[float(v) for v in t] for t in traces],
            x_unit="normalised crossing coordinate",
            y_unit="eV",
            name="pore crossing barriers",
            metadata=meta,
        )

    @staticmethod
    def _rdf_spectrum(bulk: Dict[str, Any], pore: Dict[str, Any]) -> Spectrum:
        bulk_g = [float(v) for v in bulk["g_r"]]
        pore_g = [float(v) for v in pore["g_r"]]
        return Spectrum(
            mode="Generic",
            x=[float(v) for v in bulk["r_angstrom"]],
            y=bulk_g,
            z=[pore_g],
            x_unit="Å",
            y_unit="g(r)",
            name="Na-P radial distribution",
            metadata={
                "engine": "internal:association-theory-rdf",
                "citation": _CITATION,
                "series_names": ["体相 1 M / bulk", "孔内受限 / in-pore"],
                "bulk_coordination": round(bulk["mean_coordination"], 3),
                "pore_coordination": round(pore["mean_coordination"], 3),
                "max_coordination": MAX_COORDINATION,
                "note": (
                    "缔合理论替代 2 ns COMPASS III 轨迹，趋势可信、绝对配位数不保证。/ "
                    "Association theory replaces a 2 ns COMPASS III trajectory; "
                    "the trend is trustworthy, absolute coordination is not."
                ),
            },
        )

    def _summarise(
        self,
        result: Any,
        rdf_bulk: Dict[str, Any],
        rdf_pore: Dict[str, Any],
        pore: float,
        conc: float,
        language: str,
    ) -> Text:
        lines: List[str] = []
        if language.startswith("zh"):
            lines.append(f"硬碳纳米孔预脱溶剂模型（孔口 {pore:.1f} Å，{conc:.1f} M）")
            lines.append("=" * 58)
            lines.append("")
            lines.append("尺寸筛分结果：")
            for state in result.states:
                if state.blocked:
                    verdict = "无法通过（孔口阻塞）"
                    energy = "∞"
                else:
                    verdict = "可通过"
                    energy = f"{state.barrier_ev:.2f} eV"
                lines.append(
                    f"  {state.species:14s} 尺寸 {state.size_a:6.2f} Å  "
                    f"配位 {state.coordination}  {energy:>10s}  {verdict}"
                )
            lines.append("")
            lines.append(
                f"孔内平均 PF6 配位 = {result.mean_coordination:.2f}；"
                f"Na–P 配位由体相 {rdf_bulk['mean_coordination']:.2f} "
                f"升至孔内 {rdf_pore['mean_coordination']:.2f}。"
            )
            lines.append("")
            lines.append(
                "机理：大于孔口的溶剂化结构被直接挡回（SSIP 完全无法进入），"
                "能进入的只有小尺寸的接触离子对与聚集体。"
                "孔内因此是高聚集态而非体相电解液——"
                "溶剂壳被部分剥除，而不是变成裸 Na⁺。"
            )
            lines.append("")
            lines.append(f"能垒标定：CIP {BARRIER_CIP_EV:.2f} eV、AGG {BARRIER_AGG_EV:.2f} eV"
                         f"（Fig. 2e 实测，两点定标故精确复现）")
        else:
            lines.append(f"Pre-desolvation model for a hard-carbon pore "
                         f"(throat {pore:.1f} Å, {conc:.1f} M)")
            lines.append("=" * 58)
            lines.append("")
            for state in result.states:
                energy = "infinite" if state.blocked else f"{state.barrier_ev:.2f} eV"
                verdict = "blocked at the throat" if state.blocked else "passes"
                lines.append(
                    f"  {state.species:14s} size {state.size_a:6.2f} Å  "
                    f"coord {state.coordination}  {energy:>10s}  {verdict}"
                )
            lines.append("")
            lines.append(
                f"Mean PF6 coordination in-pore {result.mean_coordination:.2f}; "
                f"Na-P coordination rises from {rdf_bulk['mean_coordination']:.2f} "
                f"in bulk to {rdf_pore['mean_coordination']:.2f} in-pore."
            )
            lines.append("")
            lines.append(
                "Mechanism: structures larger than the throat are rejected outright "
                "(SSIP cannot enter at all); only the compact contact pair and the "
                "aggregate fit through. The pore therefore holds an aggregated "
                "state, not bulk electrolyte -- the solvation shell is partially "
                "stripped, never converted to bare Na+."
            )
        lines.append("")
        lines.append(_PROVENANCE_ZH)
        lines.append(f"数据出处 / source: {_CITATION}")
        return Text(
            name="pre-desolvation mechanism",
            text="\n".join(lines),
            language=language,
            metadata={"engine": _ENGINE, "citation": _CITATION},
        )


@register_node
class ElectrolyteAgingNode(ScientificNode):
    """Rest-time dependence of impedance, OCP and initial coulombic efficiency.

    Reproduces the shape of Fig. 1a/1c/1d: as the pores fill, the interface
    impedance relaxes and the ICE saturates.  The relaxation time is fixed by
    the two impedances the paper reports (86.2 ohm at 4 h, 14.6 ohm at 40 h), and
    both of those values come out of the curve exactly.

    Outputs
    -------
    ``curves``  Spectrum -- impedance, OCP and ICE against rest time
    ``table``   Table   -- the same series tabulated
    ``text``    Text    -- summary with the saturation caveat
    """

    name = "Electrolyte Aging"
    category = "Instruments/Electrochemistry"
    description = (
        "电解液静置老化动力学：按孔填充时间常数给出界面阻抗、开路电压与"
        "首效随静置时间的演化（Fig. 1a/1c/1d）。"
    )
    tags = ["aging", "sei", "ice", "impedance", "hard-carbon"]
    icon = "AG"
    capabilities = ["models_electrolyte_aging"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = []
    output_ports = [
        Port("curves", "Spectrum", "阻抗 / OCP / 首效 随静置时间"),
        Port("table", "Table", "老化序列逐点数值"),
        Port("text", "Text", "老化机理说明"),
    ]

    parameters = [
        ParameterSpec(
            "tau_fill", "number", TAU_FILL_H, "孔填充时间常数",
            unit="h", min=0.5, max=500.0, step=0.1,
        ),
        ParameterSpec(
            "r_initial", "number", R_FOUR_H, "初始界面阻抗（4 h 实测值）",
            unit="Ω", min=0.1, max=10000.0, step=0.1,
        ),
        ParameterSpec(
            "r_residual", "number", R_FORTY_H, "残余界面阻抗（40 h 实测值）",
            unit="Ω", min=0.001, max=10000.0, step=0.1,
        ),
        ParameterSpec(
            "sei_loss", "number", 12.5, "老化期不可逆 Na 损失",
            unit="%", min=0.0, max=100.0, step=0.1,
        ),
        ParameterSpec(
            "residual_loss", "number", 100.0 - ICE_AT_10D,
            "满孔后残余不可逆 Na 损失（决定首效上限）",
            unit="%", min=0.0, max=100.0, step=0.01,
        ),
        ParameterSpec(
            "max_time", "number", 240.0, "静置时间上限", unit="h",
            min=1.0, max=2000.0, step=1.0,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        tau = float(self.get_param("tau_fill", TAU_FILL_H))
        r0 = float(self.get_param("r_initial", R_FOUR_H))
        rinf = float(self.get_param("r_residual", R_FORTY_H))
        loss = float(self.get_param("sei_loss", 12.5))
        residual = float(self.get_param("residual_loss", 100.0 - ICE_AT_10D))
        max_time = float(self.get_param("max_time", 240.0))
        language = str(self.get_param("language", "zh") or "zh")

        # Sample at the times the paper actually reports (4 h and 40 h impedance,
        # 12 h and 10 d ICE) rather than on an even grid.  A uniform 25-point
        # grid over 240 h steps by 10 h and lands on neither 12 h nor 40 h, so
        # the table the user reads showed the fit without ever showing the
        # numbers it is supposed to reproduce.
        points = 25
        even = [max_time * i / (points - 1) for i in range(points)]
        anchors = [t for t in (0.0, 4.0, 12.0, 40.0, max_time) if 0.0 <= t <= max_time]
        times = sorted(set(round(t, 6) for t in (*even, *anchors)))
        result = aging_curves(
            tau_fill_h=tau,
            time_h=times,
            r_initial_ohm=r0,
            r_residual_ohm=rinf,
            sei_capacity_loss=loss,
            residual_loss_percent=residual,
        )

        spectrum = Spectrum(
            mode="Generic",
            x=[float(v) for v in result.time_h],
            y=[float(v) for v in result.impedance_ohm],
            z=[
                [float(v) for v in result.ocp_volt],
                [float(v) for v in result.ice_percent],
            ],
            x_unit="h",
            y_unit="Ω",
            name="aging series",
            metadata={
                "engine": result.engine,
                "citation": _CITATION,
                "tau_fill_h": round(result.tau_fill_h, 4),
                "series_names": [
                    "界面阻抗 / interface impedance",
                    "开路电压 / OCP",
                    "首效 / ICE",
                ],
                "scale_note": (
                    "三条序列量纲不同（Ω / V / %），图上共用归一化坐标，"
                    "请按 series_names 读数。/ Three series in different units "
                    "share one normalised axis; read them by series_names."
                ),
                "note": _PROVENANCE_ZH,
            },
        )

        rows = [
            {
                "time_h": round(t, 3),
                "impedance_ohm": round(z, 4),
                "ocp_volt": round(v, 5),
                "ice_percent": round(i, 4),
            }
            for t, z, v, i in zip(
                result.time_h, result.impedance_ohm, result.ocp_volt, result.ice_percent
            )
        ]
        table = Table.from_records(
            rows,
            name="aging table",
            units={"time_h": "h", "impedance_ohm": "Ω", "ocp_volt": "V", "ice_percent": "%"},
            metadata={"engine": result.engine},
        )

        self.log(
            f"aging: tau={result.tau_fill_h:.2f} h, "
            f"R {r0:.1f} -> {rinf:.1f} ohm, ICE plateau {100.0 - residual:.2f}%"
        )
        return {
            "curves": spectrum,
            "table": table,
            "text": self._text(result, r0, rinf, loss, residual, language),
        }

    @staticmethod
    def _text(
        result: Any,
        r0: float,
        rinf: float,
        loss: float,
        residual: float,
        language: str,
    ) -> Text:
        plateau = 100.0 - residual
        if language.startswith("zh"):
            body = (
                f"静置老化动力学（τ_fill = {result.tau_fill_h:.2f} h）\n"
                f"{'=' * 58}\n\n"
                f"孔填充分数 f(t) = 1 − exp(−t/τ)，两个锚点由实测阻抗固定：\n"
                f"  4 h  → {r0:.2f} Ω\n"
                f"  40 h → {rinf:.2f} Ω\n\n"
                f"界面阻抗随孔填充下降，开路电压上升；SEI 在孔仍为空时生成，\n"
                f"因此不可逆 Na 损失在孔填满后停止增加。\n\n"
                f"损失分为两部分，不要混淆：\n"
                f"  老化期损失 sei_loss = {loss:.2f}%（t=0 时全部尚未形成，随孔填充逐步生成）\n"
                f"  满孔残余损失 residual_loss = {residual:.2f}%（孔填满后依然不可逆）\n\n"
                f"因此首效上限 = 100 − residual_loss = {plateau:.2f}%，"
                f"与论文 10 天实测 {ICE_AT_10D:.2f}% 一致。\n"
                f"若要复现论文 12 h 的 {ICE_AT_12H:.2f}%，请把 sei_loss 设为 "
                f"{sei_loss_for_12h(result.tau_fill_h, plateau):.4f}% —— "
                f"不是 {plateau - ICE_AT_12H:.2f}%，因为曲线是\n"
                f"  ICE(t) = {plateau:.2f} − sei_loss · exp(−t/τ)，"
                f"12 h 时指数因子是 {math.exp(-12.0 / result.tau_fill_h):.4f} 而非 1。\n\n"
                f"曲线为拟合式，未复现实验散点；数值非第一性原理计算。"
            )
        else:
            body = (
                f"Aging kinetics (tau_fill = {result.tau_fill_h:.2f} h)\n"
                f"{'=' * 58}\n\n"
                f"Filling fraction f(t) = 1 - exp(-t/tau); both anchors come from\n"
                f"the measured impedances: 4 h -> {r0:.2f} ohm, 40 h -> {rinf:.2f} ohm.\n\n"
                f"The interface impedance relaxes as pores fill and the OCP rises; "
                f"SEI forms while pores are still empty, so irreversible Na loss "
                f"stops growing once the pores are full.\n\n"
                f"The loss splits in two, and the two are not interchangeable:\n"
                f"  during aging, sei_loss = {loss:.2f}% (none of it formed at t=0; "
                f"it accumulates as pores fill)\n"
                f"  at full filling, residual_loss = {residual:.2f}% (still "
                f"irreversible with the pores completely wet)\n\n"
                f"The ICE ceiling is therefore 100 - residual_loss = {plateau:.2f}%, "
                f"matching the measured {ICE_AT_10D:.2f}% at 10 days.\n"
                f"To also reproduce the {ICE_AT_12H:.2f}% at 12 h, set "
                f"sei_loss = {sei_loss_for_12h(result.tau_fill_h, plateau):.4f}% -- "
                f"not {plateau - ICE_AT_12H:.2f}%, because the curve is\n"
                f"  ICE(t) = {plateau:.2f} - sei_loss * exp(-t/tau), and at 12 h "
                f"the exponential is {math.exp(-12.0 / result.tau_fill_h):.4f}, "
                f"not 1.\n\n"
                f"The curves are fits, not a reproduction of the experimental "
                f"scatter; the values are not first-principles calculations."
            )
        return Text(
            name="aging summary",
            text=body,
            language=language,
            metadata={"engine": result.engine, "citation": _CITATION},
        )


def sei_loss_for_12h(tau_fill_h: float, plateau: float) -> float:
    """The ``sei_loss`` that puts ``ICE_AT_12H`` at **t = 12 h**, not at t = 0.

    The curve is ``ICE(t) = plateau - sei_loss * exp(-t/tau)``, so the obvious
    ``plateau - ICE_AT_12H`` places the measured 12 h value at t = 0 and is off
    by a factor of ``1/exp(-12/tau)`` (about 1.8 at tau = 20.27 h).  Quoting the
    naive difference made the node tell users to set a parameter that does not
    reproduce the number it was derived from.
    """
    return (float(plateau) - ICE_AT_12H) / math.exp(-12.0 / float(tau_fill_h))


@register_node
class DoubleSEIEnergeticsNode(ScientificNode):
    """Surface vs in-pore SEI energetics -- the double-SEI model's evidence.

    The paper's mechanistic argument rests on a single asymmetry: the in-pore
    SEI (I-SEI) has a *lower* activation energy than the surface SEI (S-SEI),
    because pre-desolvation already removed part of the solvation shell before
    the ion ever reached the carbon.  That difference is measured, and it is
    returned here verbatim together with the Arrhenius lines built from it.

    This node also supplies the electrolyte LUMO shift, which the paper asserts
    but never computes -- the Coulombic screening estimate is flagged as the
    platform's own addition, not the authors'.

    Outputs
    -------
    ``arrhenius``  Spectrum -- ln(1/R) versus 1000/T for both SEI layers
    ``table``      Table   -- activation energies and the S-to-I reduction
    ``text``       Text    -- the double-SEI argument with the LUMO estimate
    """

    name = "Double SEI Energetics"
    category = "Instruments/Electrochemistry"
    description = (
        "双 SEI 能量学：对比表面 SEI 与孔内 SEI 的活化能（Fig. 4h/4i），"
        "给出 Arrhenius 直线，并估算预脱溶剂引起的电解液 LUMO 位移。"
    )
    tags = ["sei", "arrhenius", "activation-energy", "lumo", "hard-carbon"]
    icon = "SE"
    capabilities = ["models_double_sei_energetics"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = []
    output_ports = [
        Port("arrhenius", "Spectrum", "ln(1/R) ~ 1000/T 拟合直线"),
        Port("table", "Table", "S-SEI / I-SEI 活化能与降幅"),
        Port("text", "Text", "双 SEI 机理与 LUMO 估算"),
    ]

    parameters = [
        ParameterSpec(
            "electrolyte", "enum", "ether", "电解液体系",
            options=[
                ("ether", "1 M NaPF6 in diglyme（醚系）"),
                ("ester", "1 M NaPF6 in EC/DEC（酯系）"),
            ],
        ),
        ParameterSpec(
            "process", "enum", "1", "过程",
            options=[
                ("1", "脱溶剂电阻 R1"),
                ("2", "穿 SEI 传输电阻 R2"),
            ],
        ),
        ParameterSpec(
            "resistance", "number", 50.0, "参考阻抗", unit="Ω",
            min=0.001, max=1e6, step=1.0, advanced=True,
        ),
        ParameterSpec(
            "dielectric", "number", 7.2, "电解液介电常数（LUMO 估算用）",
            min=1.0, max=100.0, step=0.1, advanced=True,
        ),
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        electrolyte = str(self.get_param("electrolyte", "ether"))
        process = int(self.get_param("process", 1))
        resistance = float(self.get_param("resistance", 50.0))
        eps = float(self.get_param("dielectric", 7.2))
        language = str(self.get_param("language", "zh") or "zh")

        series_s = arrhenius_series(electrolyte, "S", process, resistance_ohm=resistance)
        series_i = arrhenius_series(electrolyte, "I", process, resistance_ohm=resistance)
        lumo = lumo_shift(dielectric_constant=eps)

        ea_s = activation_energy(electrolyte, "S", process)
        ea_i = activation_energy(electrolyte, "I", process)
        ea_s2 = activation_energy(electrolyte, "S", 2)
        ea_i2 = activation_energy(electrolyte, "I", 2)

        spectrum = Spectrum(
            mode="Generic",
            x=[float(v) for v in series_s["inverse_temperature"]],
            y=[float(v) for v in series_s["ln_inverse_resistance"]],
            z=[[float(v) for v in series_i["ln_inverse_resistance"]]],
            x_unit="1000/T (K⁻¹)",
            y_unit="ln(1/R)",
            name="Arrhenius fits",
            metadata={
                "engine": "internal:arrhenius-fit",
                "citation": _CITATION,
                "activation_energy_S_kJ": ea_s,
                "activation_energy_I_kJ": ea_i,
                "temperature_window_K": [278.0, 333.0],
                "series_names": ["S-SEI 表面 / surface", "I-SEI 孔内 / in-pore"],
                "note": (
                    "论文警告温度区间过宽会破坏线性，故固定为 278–333 K。/ "
                    "The paper warns a wide temperature window breaks the "
                    "linearity, so the window is fixed at 278-333 K."
                ),
            },
        )

        rows = [
            {
                "electrolyte": electrolyte,
                "process": "脱溶剂 R1 / desolvation" if process == 1 else "穿 SEI R2 / transport",
                "E_a_S_SEI_kJ": ea_s,
                "E_a_I_SEI_kJ": ea_i,
                "reduction_kJ": round(ea_s - ea_i, 4),
                "reduction_percent": round(100.0 * (ea_s - ea_i) / ea_s, 3),
            },
            {
                "electrolyte": electrolyte,
                "process": "穿 SEI R2 / transport",
                "E_a_S_SEI_kJ": ea_s2,
                "E_a_I_SEI_kJ": ea_i2,
                "reduction_kJ": round(ea_s2 - ea_i2, 4),
                "reduction_percent": round(100.0 * (ea_s2 - ea_i2) / ea_s2, 3),
            },
        ]
        table = Table.from_records(
            rows,
            name="activation energies",
            units={"E_a_S_SEI_kJ": "kJ/mol", "E_a_I_SEI_kJ": "kJ/mol"},
            metadata={"engine": "internal:reported-values", "citation": _CITATION},
        )

        self.log(
            f"double SEI: Ea S={ea_s:.2f} I={ea_i:.2f} kJ/mol, "
            f"reduction {ea_s - ea_i:.2f} kJ/mol ({electrolyte})"
        )
        return {
            "arrhenius": spectrum,
            "table": table,
            "text": self._text(electrolyte, ea_s, ea_i, ea_s2, ea_i2, lumo, language),
        }

    @staticmethod
    def _text(
        electrolyte: str,
        ea_s: float,
        ea_i: float,
        ea_s2: float,
        ea_i2: float,
        lumo: Dict[str, float],
        language: str,
    ) -> Text:
        delta = ea_s - ea_i
        pct = 100.0 * delta / ea_s
        if language.startswith("zh"):
            body = (
                f"双 SEI 能量学（{electrolyte}）\n{'=' * 58}\n\n"
                f"脱溶剂过程 R1：  表面 S-SEI {ea_s:.2f} → 孔内 I-SEI {ea_i:.2f} kJ/mol"
                f"（降低 {delta:.2f} kJ/mol，{pct:.1f}%）\n"
                f"穿 SEI 传输 R2： 表面 {ea_s2:.2f} → 孔内 {ea_i2:.2f} kJ/mol\n\n"
                f"孔内 SEI 的活化能系统性更低，这正是双 SEI 模型的判据性证据：\n"
                f"Na⁺ 到达碳表面前，预脱溶剂已经剥掉了一部分溶剂壳，\n"
                f"所以剩余的脱溶剂驱动力变小、能垒更低。\n\n"
                f"电解液 LUMO 位移估算：{lumo['delta_lumo_eV']:+.3f} eV"
                f"（负值 = LUMO 被抬高 → 更难得电子 → 还原分解被抑制）\n"
                f"来源声明：上述活化能为论文实测值，本平台原样引用；\n"
                f"它们不是本平台的第一性原理计算（NEB / DFT），也不冒充计算结果。\n"
                f"注意：论文只断言了 LUMO 升高而未给出计算，此处为平台的库仑屏蔽\n"
                f"估算（ε={lumo['dielectric_constant']}，"
                f"r_agg={lumo['r_aggregate_angstrom']} Å，"
                f"r_bulk={lumo['r_bulk_angstrom']} Å），属于作者之外的补充。"
            )
        else:
            body = (
                f"Double-SEI energetics ({electrolyte})\n{'=' * 58}\n\n"
                f"Desolvation R1: surface {ea_s:.2f} -> in-pore {ea_i:.2f} kJ/mol "
                f"(lower by {delta:.2f} kJ/mol, {pct:.1f}%)\n"
                f"Transport R2:    surface {ea_s2:.2f} -> in-pore {ea_i2:.2f} kJ/mol\n\n"
                f"The systematically lower in-pore activation energy is the "
                f"decisive evidence for the double-SEI model: by the time Na+ "
                f"reaches the carbon, pre-desolvation already stripped part of "
                f"the shell, so what remains is cheaper.\n\n"
                f"Electrolyte LUMO shift estimate: {lumo['delta_lumo_eV']:+.3f} eV "
                f"(negative = LUMO raised, harder to reduce, decomposition "
                f"suppressed). The paper asserts this without computing it; the "
                f"number here is the platform's Coulombic screening estimate and "
                f"is ours, not the authors'.\n\n"
                f"Provenance: the activation energies above are the paper's "
                f"measured values, quoted verbatim. They are not "
                f"first-principles (NEB / DFT) results computed here and are "
                f"not presented as such."
            )
        return Text(
            name="double SEI energetics",
            text=body,
            language=language,
            metadata={
                "engine": "internal:reported-values+lumo-surrogate",
                "citation": _CITATION,
                "reported_values": ACTIVATION_ENERGIES_KJ,
            },
        )


class _BranchProblem(str):
    """Why a branch could not be read, so the report can say which it was."""

    MISSING = "not_connected"
    SCHEMA = "schema_mismatch"


#: Stage ids and labels in one place: the readable path and the failure path
#: must not be able to drift into naming the same stage differently.
_STAGE_ID = {
    "sieve": "1_size_sieve",
    "aging": "2_aging_gain",
    "energetics": "3_double_sei",
}
_STAGE_LABEL = {
    "sieve": ("可通过孔口的溶剂化结构", "solvation states that fit"),
    "aging": ("首效随静置的提升", "ICE gain with rest time"),
    "energetics": ("孔内 SEI 活化能降幅", "in-pore SEI barrier reduction"),
}


class _Branch:
    """One upstream branch: its rows, or the reason there are none."""

    def __init__(self, name: str, rows: Any) -> None:
        self.name = name
        if isinstance(rows, tuple):
            self.rows: List[Dict[str, Any]] = []
            self.reason: str = rows[0]
            self.detail: str = rows[1]
        else:
            self.rows = rows
            self.reason = ""
            self.detail = ""

    def __bool__(self) -> bool:
        return bool(self.rows)

    @property
    def verdict(self) -> str:
        return self.reason or "ok"


def _rows_of(value: Any, columns: Sequence[str]) -> Any:
    """Reorder a ``Table``'s rows into ``columns``, or explain why not.

    Returns a list of **dicts keyed by column name**, never positional lists.
    Three different upstream tables are consumed here and their column orders
    have no reason to agree; indexing by position once put a species label
    where a radius was expected.  A name lookup makes that class of bug
    impossible to write.

    On failure it returns ``(reason, detail)`` rather than a bare ``None``:
    "the wire is not connected" and "the wire is connected but the upstream
    column was renamed" send the user to completely different places, and
    collapsing both into "not connected" sends them to the wrong one.
    """
    table = getattr(value, "columns", None)
    rows = getattr(value, "rows", None)
    if value is None or not table or rows is None:
        return _BranchProblem.MISSING, "the branch is not connected"
    index = {str(name): i for i, name in enumerate(table)}
    absent = [name for name in columns if name not in index]
    if absent:
        return (
            _BranchProblem.SCHEMA,
            f"upstream table has {list(table)}; missing {absent}",
        )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if len(row) < len(table):
            return (
                _BranchProblem.SCHEMA,
                f"a row has {len(row)} cells but the table declares {len(table)}",
            )
        out.append({name: row[index[name]] for name in columns})
    return out


@register_node
class PreDesolvationMechanismNode(ScientificNode):
    """The paper's central claim as one connected, visualisable model.

    The three stage nodes each reproduce one figure, but the *argument* needs
    them together: a species small enough to enter (Fig. 2d/2e) pays a lower
    activation energy inside the pore than on the surface (Fig. 4h), which is
    why resting time keeps buying efficiency until the pores fill (Fig. 1a).
    This node takes all three results, checks that they actually agree, and
    emits the combined view plus a verdict.

    The consistency checks are the point.  Three independently-calibrated
    surrogates that contradict each other would still produce three plausible
    plots; saying so is more useful than drawing them.

    Inputs
    ------
    ``sieve``    Table   -- from :class:`DesolvationSieveNode`
    ``aging``    Table   -- from :class:`ElectrolyteAgingNode`
    ``energetics`` Table -- from :class:`DoubleSEIEnergeticsNode`
    All three are optional so a workflow can feed a partial chain, but an
    unconnected branch is named in the output instead of silently ignored.

    Outputs
    -------
    ``mechanism`` Spectrum -- the combined multi-series view
    ``stages``    Table    -- stage-by-stage verdict
    ``text``      Text     -- the argument, with the caveats attached
    """

    name = "Pre-desolvation Mechanism"
    category = "Instruments/Electrochemistry"
    description = (
        "预脱溶剂机制汇总节点：把尺寸筛分、静置老化与双 SEI 能量学三条支路"
        "接成一条证据链，逐项检查三者是否自洽，输出论文 Fig.1a 的首效主曲线"
        "与可交互的分阶段判据表。"
    )
    tags = ["hard-carbon", "desolvation", "sei", "evidence", "sodium"]
    icon = "PD"
    capabilities = ["models_pre_desolvation_mechanism"]
    execution_mode = "internal_deterministic_rules"
    reproducibility_level = "deterministic"

    input_ports: List[Port] = [
        Port("sieve", "Table", "尺寸筛分结果", optional=True),
        Port("aging", "Table", "静置老化序列", optional=True),
        Port("energetics", "Table", "双 SEI 活化能", optional=True),
    ]
    output_ports = [
        Port("mechanism", "Spectrum", "首效随静置时间的归一化曲线"),
        Port("sieving", "Spectrum", "溶剂化半径比 vs 尺寸筛分（孔径轴）"),
        Port("barriers", "Spectrum", "表面 SEI 与孔内 SEI 活化能对比"),
        Port("stages", "Table", "分阶段判据与自洽性检查"),
        Port("text", "Text", "机制证据链与限制说明"),
    ]

    parameters = [
        ParameterSpec(
            "language", "enum", "zh", "说明语言",
            options=[("zh", "中文"), ("en", "English")],
        ),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        language = str(self.get_param("language", "zh") or "zh")
        zh = language == "zh"

        sieve = _Branch("sieve", _rows_of(
            inputs.get("sieve"),
            ["species", "label", "size_angstrom", "radius_ratio", "pf6_coordination"],
        ))
        aging = _Branch("aging", _rows_of(
            inputs.get("aging"),
            ["time_h", "impedance_ohm", "ice_percent"],
        ))
        energetics = _Branch("energetics", _rows_of(
            inputs.get("energetics"),
            ["electrolyte", "E_a_S_SEI_kJ", "E_a_I_SEI_kJ", "reduction_percent"],
        ))
        sieve_rows, aging_rows, energy_rows = sieve.rows, aging.rows, energetics.rows
        branches = (sieve, aging, energetics)

        stages: List[List[Any]] = []
        connected: List[str] = []
        missing: List[str] = []

        def unreadable(branch: _Branch) -> List[Any]:
            """One stage row saying exactly what went wrong with this branch."""
            missing.append(branch.name)
            stages.append([
                _STAGE_ID[branch.name],
                _STAGE_LABEL[branch.name][zh],
                branch.detail if branch.reason == _BranchProblem.SCHEMA else "—",
                branch.reason,
            ])
            return []

        # -- stage 1: does anything fit through the throat? ----------------- #
        admitted = 0
        if sieve:
            admitted = sum(
                1 for row in sieve_rows if float(row["radius_ratio"]) < 1.0
            )
            connected.append("sieve")
            stages.append([
                _STAGE_ID["sieve"],
                translate_stage(zh, "可通过孔口的溶剂化结构", "solvation states that fit"),
                f"{admitted}/{len(sieve_rows)}",
                "ok" if admitted else "blocked",
            ])
        else:
            unreadable(sieve)

        # -- stage 2: does resting time keep paying? ------------------------ #
        ice_gain = None
        if aging_rows:
            connected.append("aging")
            first = float(aging_rows[0]["ice_percent"])
            last = float(aging_rows[-1]["ice_percent"])
            ice_gain = last - first
            # Monotonicity is checked, not assumed: a curve that dips means the
            # single-exponential model has been pushed outside its validity.
            values = [float(row["ice_percent"]) for row in aging_rows]
            rising = all(b >= a for a, b in zip(values, values[1:]))
            stages.append([
                _STAGE_ID["aging"],
                translate_stage(zh, "首效随静置的提升", "ICE gain with rest time"),
                f"{ice_gain:+.2f} pp",
                "ok" if rising and ice_gain > 0 else "non_monotonic",
            ])
        else:
            unreadable(aging)

        # -- stage 3: is the in-pore path actually cheaper? ------------------ #
        reduction = None
        if energy_rows:
            connected.append("energetics")
            reduction = float(energy_rows[0]["reduction_percent"])
            stages.append([
                _STAGE_ID["energetics"],
                translate_stage(zh, "孔内 SEI 活化能降幅", "in-pore SEI barrier reduction"),
                f"{reduction:+.1f} %",
                "ok" if reduction > 0 else "contradicts",
            ])
        else:
            unreadable(energetics)

        # -- the combined view ---------------------------------------------- #
        # A Spectrum has exactly one abscissa, so merging branches means putting
        # them all on one axis.  The aging curve is in hours and the sieving
        # curve is in angstroms: resampling one onto the other invents data,
        # and comparing row counts does not detect it -- it fails exactly when
        # the two happen to have the same number of rows, which is the case a
        # user is most likely to hit by trimming one branch.  So the size
        # branch gets its own output, and this merged view carries only the
        # branches that genuinely share an axis.
        curves: List[Tuple[str, List[float], List[float]]] = []

        if aging_rows:
            hours = [float(row["time_h"]) for row in aging_rows]
            ice = [float(row["ice_percent"]) for row in aging_rows]
            curves.append((
                "ICE vs rest time",
                hours,
                _normalise(ice),
            ))

        dropped: List[str] = []
        if sieve_rows:
            dropped.append(
                "radius ratio (SolvationState): different abscissa (angstrom "
                "vs hours) -- see the 'sieving' output"
            )

        if curves:
            axis = curves[0][1]
            z: List[List[float]] = [list(curves[0][2])]
            mechanism = Spectrum(
                name="pre-desolvation mechanism",
                x=list(axis),
                y=z[0],
                z=z,
                x_unit="h",
                y_unit="normalized to first point",
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "series_names": [name for name, _, _ in curves],
                    "dropped_series": dropped,
                    "ice_gain_points": ice_gain,
                    "sei_reduction_percent": reduction,
                    "admitted_species": admitted,
                },
            )
        else:
            mechanism = Spectrum(
                name="pre-desolvation mechanism",
                x=[],
                y=[],
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "series_names": [],
                    "dropped_series": dropped,
                    "note": "no branch delivered a plottable series",
                },
            )

        # The size-sieving branch, on its own axis in its own unit.
        if sieve_rows:
            sieving = Spectrum(
                name="size sieving",
                x=[float(row["size_angstrom"]) for row in sieve_rows],
                y=_normalise([float(row["radius_ratio"]) for row in sieve_rows]),
                x_unit="angstrom",
                y_unit="normalized to first point",
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "series_names": ["radius ratio (SolvationState)"],
                    "admitted_species": admitted,
                },
            )
        else:
            sieving = Spectrum(
                name="size sieving",
                x=[],
                y=[],
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "series_names": [],
                    "note": "the sieving branch is not connected",
                },
            )

        # The S-SEI / I-SEI pair is the paper's decisive comparison and has only
        # two values; giving it its own spectrum is what lets the plot panel
        # render it legibly instead of as two dots on a 25-point axis.
        if energy_rows:
            barriers = Spectrum(
                name="double SEI barriers",
                x=[0.0, 1.0],
                y=[
                    float(energy_rows[0]["E_a_S_SEI_kJ"]),
                    float(energy_rows[0]["E_a_I_SEI_kJ"]),
                ],
                x_unit="S-SEI | I-SEI",
                y_unit="kJ/mol",
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "series_names": ["surface SEI", "in-pore SEI"],
                },
            )
        else:
            barriers = Spectrum(
                name="double SEI barriers",
                x=[],
                y=[],
                metadata={"engine": _ENGINE, "citation": _CITATION},
            )

        verdict = "ok" if len(missing) == 0 else "partial"
        if reduction is not None and reduction <= 0:
            verdict = "contradicts"
        elif ice_gain is not None and ice_gain <= 0:
            verdict = "contradicts"

        stages_table = Table.from_records(
            [
                {
                    "stage": stage,
                    "quantity": quantity,
                    "value": value,
                    "verdict": check,
                }
                for stage, quantity, value, check in stages
            ],
            name="pre-desolvation stages",
            metadata={"engine": _ENGINE, "citation": _CITATION},
        )

        return {
            "mechanism": mechanism,
            "sieving": sieving,
            "barriers": barriers,
            "stages": stages_table,
            "text": Text(
                name="pre-desolvation mechanism",
                text=_mechanism_text(
                    zh=zh,
                    admitted=admitted if sieve_rows else None,
                    ice_gain=ice_gain,
                    reduction=reduction,
                    connected=connected,
                    missing=missing,
                    verdict=verdict,
                ),
                language=language,
                metadata={
                    "engine": _ENGINE,
                    "citation": _CITATION,
                    "verdict": verdict,
                    "connected_stages": connected,
                    "missing_stages": missing,
                },
            ),
        }


def translate_stage(zh: bool, cn: str, en: str) -> str:
    return cn if zh else en


def _normalise(values: Sequence[float]) -> List[float]:
    """Divide by the first point so curves of different units share an axis."""
    if not values:
        return []
    base = abs(float(values[0])) or 1.0
    return [float(v) / base for v in values]


def _mechanism_text(
    *,
    zh: bool,
    admitted: Optional[int],
    ice_gain: Optional[float],
    reduction: Optional[float],
    connected: Sequence[str],
    missing: Sequence[str],
    verdict: str,
) -> str:
    """The argument, assembled from whatever actually arrived."""
    if zh:
        lines = ["硬碳预脱溶剂机制证据链", "=" * 46, ""]
        if admitted is not None:
            lines.append(
                f"1. 尺寸筛分：{admitted} 种溶剂化结构的半径小于 4 Å 孔口，"
                "可在进入前完成部分脱溶剂。"
            )
        else:
            lines.append("1. 尺寸筛分：未连接该支路。")
        if ice_gain is not None:
            lines.append(
                f"2. 静置老化：首效随静置时间提升 {ice_gain:+.2f} 个百分点，"
                "对应孔逐渐被电解液填充。"
            )
        else:
            lines.append("2. 静置老化：未连接该支路。")
        if reduction is not None:
            lines.append(
                f"3. 双 SEI：孔内 SEI 活化能比表面低 {reduction:.1f}%，"
                "说明 Na⁺ 到达碳表面时溶剂化壳已被剥去一部分。"
            )
        else:
            lines.append("3. 双 SEI：未连接该支路。")
        lines += [
            "",
            f"结论状态：{verdict}",
            "",
            "限制：三条支路均为解析代理模型，非第一性原理计算（NEB / COMPASS III MD）。"
            "尺寸与活化能取自论文实测值，曲线形状为建模选择。"
            "机制结论以论文为准，本平台负责把三条证据链可视化并检查其自洽性。",
        ]
        return "\n".join(lines)

    lines = ["Hard-carbon pre-desolvation evidence chain", "=" * 46, ""]
    if admitted is not None:
        lines.append(
            f"1. Size sieve: {admitted} solvation structures are smaller than the "
            "4 A throat and can shed part of their shell before entry."
        )
    else:
        lines.append("1. Size sieve: branch not connected.")
    if ice_gain is not None:
        lines.append(
            f"2. Rest-time aging: ICE improves by {ice_gain:+.2f} percentage "
            "points as the pores fill."
        )
    else:
        lines.append("2. Rest-time aging: branch not connected.")
    if reduction is not None:
        lines.append(
            f"3. Double SEI: the in-pore activation energy is {reduction:.1f}% "
            "below the surface value, i.e. the shell is already partly gone "
            "when Na+ reaches the carbon."
        )
    else:
        lines.append("3. Double SEI: branch not connected.")
    lines += [
        "",
        f"Verdict: {verdict}",
        "",
        "Limits: all three branches are analytical surrogates, not "
        "first-principles (NEB / COMPASS III MD). Sizes and activation "
        "energies are the paper's measured values; curve shapes are a "
        "modelling choice. The mechanism claim is the authors'; this "
        "platform visualises the chain and checks that it is self-consistent.",
    ]
    return "\n".join(lines)