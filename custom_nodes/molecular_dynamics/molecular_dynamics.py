"""Molecular dynamics nodes backed by :mod:`simulation_runtime`.

Each node drives the corresponding engine (GROMACS / LAMMPS / OpenMM) through the
unified simulation runtime.  When the external program is missing the runtime
falls back to the built-in **Lennard-Jones MD** engine (:mod:`simulations.lj_md`)
and records it in ``Text.data["engine"]`` -- honest, reproducible dynamics on any
laptop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from simulation_runtime import run
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Material, Molecule, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import build_molecule, first_of

__all__ = ["MolecularDynamicsNode", "GROMACSNode", "LAMMPSNode", "OpenMMNode"]

ENGINES = ["gromacs", "lammps", "openmm"]


class MolecularDynamicsNode(ScientificNode):
    """Shared behaviour of the molecular dynamics nodes."""

    category = "Simulation/MD"
    capabilities = ["requires_external_software", "experimental"]
    implementation_status = "experimental"
    # -- v0.7.2 task P0-05: execution provenance ------------------------ #
    capability_status = "experimental"
    execution_mode = "internal_approximation"
    required_dependencies = ["gromacs >= 2022", "lammps >= 2022", "openmm >= 8"]
    input_constraints = (
        "需要一个带坐标的 Molecule；内置 Lennard-Jones 引擎不支持键约束、水模型或恒温器。"
        "时间步长与步数为声明式参数，不做单位自动换算声明。"
    )
    validation_evidence = []
    limitations = [
        "内置 Lennard-Jones 引擎仅演示动力学流程，不对热力学量作定量声明。",
        "未安装 GROMACS / LAMMPS / OpenMM 时结果必须视为近似。",
        "不模拟溶剂、恒温器与周期性边界的真实实现细节。",
    ]
    reproducibility_level = "deterministic"
    executable = "gmx"
    backend_name = "gromacs"

    input_ports = [Port("molecule", "Molecule", "输入分子（需坐标）", optional=True, multi=True)]
    output_ports = [
        Port("molecule", "Molecule", "模拟后的分子（终态坐标）"),
        Port("spectrum", "Spectrum", "径向分布函数 g(r)"),
        Port("table", "Table", "动力学统计"),
        Port("text", "Text", "模拟报告"),
    ]

    parameters = [
        ParameterSpec("smiles", "string", "", "备用 SMILES（无上游时使用）"),
        ParameterSpec("temperature", "number", 0.7, "约化温度（LJ 单位）", min=0.0),
        ParameterSpec("steps", "integer", 200, "积分步数", min=1, max=100000),
        ParameterSpec("dt", "number", 0.005, "时间步长（LJ 单位）", min=0.0001),
        ParameterSpec("exe_path", "file", "", "外部程序路径（覆盖 PATH）", advanced=True),
        ParameterSpec("timeout_s", "number", 600.0, "超时", unit="s", min=1.0),
        ParameterSpec("force_internal", "boolean", False, "强制使用内置引擎", advanced=True),
    ]

    def _resolve_molecule(self, inputs: Dict[str, Any]) -> Molecule:
        incoming = first_of(inputs.get("molecule"), Molecule, what="input 'molecule'")
        if incoming is not None and incoming.smiles:
            return incoming
        smiles = str(self.get_param("smiles", "") or "").strip()
        if not smiles:
            raise NodeInputError(
                f"{self.node_type()}: connect a molecule or set the 'smiles' parameter"
            )
        return build_molecule(smiles)

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        molecule = self._resolve_molecule(inputs)
        result = run(
            "md",
            molecule,
            backend=self.backend_name,
            temperature=float(self.get_param("temperature", 0.7)),
            steps=int(self.get_param("steps", 200) or 200),
            dt=float(self.get_param("dt", 0.005)),
            exe_path=str(self.get_param("exe_path", "") or ""),
            timeout=float(self.get_param("timeout_s", 600.0)),
            force_internal=bool(self.get_param("force_internal", False)),
            workdir=Path(ctx.run_dir) if ctx is not None else None,
        )
        self.log(f"{self.node_type()} -> {result.engine}")
        return result.ports


@register_node
class GROMACSNode(MolecularDynamicsNode):
    """GROMACS molecular dynamics wrapper."""

    name = "GROMACS"
    category = "Simulation/MD"
    description = "调用 GROMACS 运行分子动力学；未安装时使用内置 Lennard-Jones 引擎。"
    tags = ["simulation", "md", "gromacs"]
    capabilities = ["requires_external_software", "experimental"]
    aliases = ["GROMACS", "gmx"]
    icon = "GR"
    executable = "gmx"
    backend_name = "gromacs"


@register_node
class LAMMPSNode(MolecularDynamicsNode):
    """LAMMPS molecular dynamics wrapper."""

    name = "LAMMPS"
    category = "Simulation/MD"
    description = "调用 LAMMPS 运行分子动力学；未安装时使用内置 Lennard-Jones 引擎。"
    tags = ["simulation", "md", "lammps"]
    aliases = ["LAMMPS", "lmp"]
    icon = "LM"
    executable = "lmp"
    backend_name = "lammps"


@register_node
class OpenMMNode(MolecularDynamicsNode):
    """OpenMM molecular dynamics wrapper."""

    name = "OpenMM"
    category = "Simulation/MD"
    description = "调用 OpenMM 运行分子动力学；未安装时使用内置 Lennard-Jones 引擎。"
    tags = ["simulation", "md", "openmm"]
    aliases = ["OpenMM"]
    icon = "OM"
    executable = "python"
    backend_name = "openmm"
