"""Quantum chemistry nodes backed by :mod:`simulation_runtime`.

Each node drives the corresponding back-end (ORCA / Gaussian / Psi4 / CP2K)
through the unified simulation runtime.  When the external program is missing the
runtime falls back to the built-in **extended Hückel** engine
(:mod:`simulations.eht`) and records it in ``Text.data["engine"]``, so a laptop
run is never mistaken for a real electronic-structure calculation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from simulation_runtime import run
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import build_molecule, first_of

__all__ = [
    "QuantumChemistryNode",
    "ORCANode",
    "GaussianNode",
    "Psi4Node",
    "CP2KNode",
]

METHODS = ["eht", "hf", "b3lyp", "pbe", "pbe0", "mp2", "ccsd(t)"]
BASIS_SETS = ["MINI", "STO-3G", "3-21G", "6-31G*", "def2-SVP", "def2-TZVP"]
TASKS = ["single_point", "optimize", "frequencies", "excitation"]


class QuantumChemistryNode(ScientificNode):
    """Shared behaviour of the quantum chemistry nodes."""

    category = "Simulation/Quantum"
    #: v0.7.1 task E/F: real external software when present, honest internal
    #: approximation (EHT / tight-binding) otherwise -- never silently mixed.
    capabilities = ["requires_external_software", "experimental"]
    implementation_status = "experimental"
    # -- v0.7.2 task P0-05: execution provenance ------------------------ #
    # The real program does the work when it is installed; otherwise a built-in
    # extended-Hückel engine stands in.  The two are never mixed silently.
    capability_status = "experimental"
    execution_mode = "internal_approximation"
    required_dependencies = ["orca >= 5.0", "gaussian (g16/g09)", "psi4 >= 1.8", "cp2k >= 2023.1"]
    input_constraints = (
        "需要一个带元素与坐标的 Molecule；原子数超过 200 时内置引擎会拒绝执行。"
        "方法/基组为声明式参数，内置引擎按 MINI/STO-3G 语义近似。"
    )
    validation_evidence = []
    limitations = [
        "内置扩展 Hückel / 紧束缚近似，不作能量或光谱的定量准确度声明。",
        "未安装 ORCA / Gaussian / Psi4 / CP2K 时结果必须视为近似，不代表真实 DFT 计算。",
        "对外部软件的输出解析仅覆盖已声明的任务类型（单点 / 优化 / 频率 / 激发）。",
    ]
    reproducibility_level = "deterministic"
    #: name of the external executable searched on ``PATH``
    executable = "orca"
    #: simulation_runtime back-end selected by this node
    backend_name = "orca"
    default_method = "b3lyp"
    default_basis = "def2-SVP"

    input_ports = [Port("molecule", "Molecule", "输入分子", optional=True, multi=True)]
    output_ports = [
        Port("molecule", "Molecule", "带计算性质的分子"),
        Port("spectrum", "Spectrum", "预测谱图（频率 / 激发）"),
        Port("table", "Table", "计算结果"),
        Port("text", "Text", "计算报告"),
    ]

    parameters = [
        ParameterSpec("smiles", "string", "", "备用 SMILES"),
        ParameterSpec("method", "enum", "b3lyp", "计算方法", options=METHODS),
        ParameterSpec("basis", "enum", "def2-SVP", "基组", options=BASIS_SETS),
        ParameterSpec("charge", "integer", 0, "电荷"),
        ParameterSpec("multiplicity", "integer", 1, "自旋多重度", min=1),
        ParameterSpec("task", "enum", "single_point", "计算任务", options=TASKS),
        ParameterSpec("exe_path", "file", "", "外部程序路径（覆盖 PATH）", advanced=True),
        ParameterSpec("timeout_s", "number", 600.0, "超时", unit="s", min=1.0),
        ParameterSpec("force_internal", "boolean", False, "强制使用内置引擎", advanced=True),
    ]

    # -- internals ------------------------------------------------------------ #
    def _resolve_molecule(self, inputs: Dict[str, Any]) -> Molecule:
        """Return the molecule to compute, from the graph or from parameters."""
        incoming = first_of(inputs.get("molecule"), Molecule, what="input 'molecule'")
        if incoming is not None and incoming.smiles:
            return incoming
        smiles = str(self.get_param("smiles", "") or "").strip()
        if not smiles:
            raise NodeInputError(
                f"{self.node_type()}: connect a molecule or set the 'smiles' parameter"
            )
        return build_molecule(smiles)

    # -- execution ------------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        molecule = self._resolve_molecule(inputs)
        result = run(
            "quantum",
            molecule,
            backend=self.backend_name,
            method=str(self.get_param("method", self.default_method)),
            basis=str(self.get_param("basis", self.default_basis)),
            charge=int(self.get_param("charge", 0) or 0),
            multiplicity=int(self.get_param("multiplicity", 1) or 1),
            task=str(self.get_param("task", "single_point")),
            exe_path=str(self.get_param("exe_path", "") or ""),
            timeout=float(self.get_param("timeout_s", 600.0)),
            force_internal=bool(self.get_param("force_internal", False)),
            workdir=Path(ctx.run_dir) if ctx is not None else None,
        )
        self.log(f"{self.node_type()} -> {result.engine}")
        # v0.7.3 (audit P0-4): publish the engine that actually ran, so
        # provenance can name it.  ``execution_mode`` alone would only say
        # "internal_approximation" without identifying the approximation.
        self.last_engine = str(result.engine or "")
        self.fallback_used = bool(getattr(result, "fallback_used", False))
        self.fallback_reason = str(getattr(result, "fallback_reason", "") or "")
        return result.ports


@register_node
class ORCANode(QuantumChemistryNode):
    """ORCA single point / optimisation / frequency wrapper."""

    name = "ORCA"
    category = "Simulation/Quantum"
    description = "调用 ORCA 做单点能 / 几何优化 / 频率计算；未安装时使用内置扩展 Hückel 引擎。"
    tags = ["simulation", "quantum", "orca", "dft"]
    capabilities = ["requires_external_software", "experimental"]
    aliases = ["ORCA"]
    icon = "OR"
    executable = "orca"
    backend_name = "orca"


@register_node
class GaussianNode(QuantumChemistryNode):
    """Gaussian single point / optimisation / frequency wrapper."""

    name = "Gaussian"
    category = "Simulation/Quantum"
    description = "生成 Gaussian 输入并运行；未安装时使用内置扩展 Hückel 引擎。"
    tags = ["simulation", "quantum", "gaussian", "dft"]
    capabilities = ["requires_external_software", "experimental"]
    aliases = ["Gaussian", "g16", "g09"]
    icon = "GA"
    executable = "g16"
    backend_name = "gaussian"


@register_node
class Psi4Node(QuantumChemistryNode):
    """Psi4 single point / optimisation / frequency wrapper."""

    name = "Psi4"
    category = "Simulation/Quantum"
    description = "生成 Psi4 输入脚本并运行；未安装时使用内置扩展 Hückel 引擎。"
    tags = ["simulation", "quantum", "psi4"]
    aliases = ["Psi4"]
    icon = "PS"
    executable = "psi4"
    backend_name = "psi4"


@register_node
class CP2KNode(QuantumChemistryNode):
    """CP2K (Quickstep DFT) wrapper."""

    name = "CP2K"
    category = "Simulation/Quantum"
    description = "生成 CP2K 输入并运行 DFT；未安装时使用内置扩展 Hückel 引擎。"
    tags = ["simulation", "quantum", "cp2k", "dft"]
    aliases = ["CP2K"]
    icon = "CP"
    executable = "cp2k.psmp"
    backend_name = "cp2k"
    default_method = "pbe"
