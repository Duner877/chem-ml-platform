"""Solid-state / plane-wave DFT nodes backed by :mod:`simulation_runtime`.

``VASP`` and Quantum ESPRESSO are driven through their command line interface when
installed; otherwise the runtime falls back to the built-in **tight-binding**
engine (:mod:`simulations.tight_binding`) plus a powder XRD pattern
(:func:`models.materials.simulate_xrd`).  The engine that answered is recorded in
``Text.data["engine"]``.
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

from nodes._helpers import build_material, first_of

__all__ = ["SolidStateNode", "VASPNode", "QuantumESPRESSONode"]

CALCULATIONS = ["scf", "relax", "bands", "dos", "xrd"]
FUNCTIONALS = ["pbe", "pbesol", "lda", "scan", "hse06"]
LATTICE_KEYS = ("sc", "bcc", "fcc")


class SolidStateNode(ScientificNode):
    """Shared behaviour of the solid state simulation nodes."""

    category = "Simulation/Materials"
    capabilities = ["requires_external_software", "experimental"]
    implementation_status = "experimental"
    # -- v0.7.2 task P0-05: execution provenance ------------------------ #
    capability_status = "experimental"
    execution_mode = "internal_approximation"
    required_dependencies = ["vasp (vasp_std)", "quantum_espresso (pw.x)", "cp2k"]
    input_constraints = (
        "需要 Material 或带晶格的 Molecule；仅支持 sc/bcc/fcc 三种晶格语义。"
        "不接受实验测量的非理想结构（缺陷、表面、非晶）。"
    )
    validation_evidence = []
    limitations = [
        "内置紧束缚 / 近自由电子模型，能带与态密度只用于流程演示，不作定量声明。",
        "未安装 VASP / Quantum ESPRESSO / CP2K 时结果必须视为近似。",
        "不处理自旋极化、强关联与范德华修正。",
    ]
    reproducibility_level = "deterministic"
    executable = "pw.x"
    backend_name = "vasp"
    engine_name = "Solid-state DFT"

    input_ports = [Port("material", "Any", "上游材料（材料 / 分子）", optional=True, multi=True)]
    output_ports = [
        Port("material", "Material", "带计算性质的材料"),
        Port("spectrum", "Spectrum", "能带 / 态密度 / 衍射图"),
        Port("table", "Table", "计算结果"),
        Port("text", "Text", "计算报告"),
    ]

    parameters = [
        ParameterSpec("formula", "string", "LiFePO4", "化学式（无上游时使用）"),
        ParameterSpec("calculation", "enum", "scf", "计算类型", options=CALCULATIONS),
        ParameterSpec("functional", "enum", "pbe", "泛函", options=FUNCTIONALS),
        ParameterSpec("cutoff_ev", "number", 520.0, "平面波截断能", unit="eV", min=50.0),
        ParameterSpec("kpoints", "integer", 4, "k 点网格", min=1, max=32),
        ParameterSpec("lattice", "enum", "sc", "Bravais 格子（内置紧束缚用）", options=list(LATTICE_KEYS), advanced=True),
        ParameterSpec("hopping", "number", -1.0, "最近邻跃迁积分 t", unit="eV", advanced=True),
        ParameterSpec("a", "number", 0.0, "晶胞参数 a（0 = 自动）", unit="Å", advanced=True),
        ParameterSpec("b", "number", 0.0, "晶胞参数 b", unit="Å", advanced=True),
        ParameterSpec("c", "number", 0.0, "晶胞参数 c", unit="Å", advanced=True),
        ParameterSpec("alpha", "number", 90.0, "晶胞角 α", unit="°", advanced=True),
        ParameterSpec("beta", "number", 90.0, "晶胞角 β", unit="°", advanced=True),
        ParameterSpec("gamma", "number", 90.0, "晶胞角 γ", unit="°", advanced=True),
        ParameterSpec("wavelength", "number", 1.5406, "XRD 波长", unit="Å", advanced=True),
        ParameterSpec("exe_path", "file", "", "外部程序路径（覆盖 PATH）", advanced=True),
        ParameterSpec("timeout_s", "number", 1800.0, "超时", unit="s", min=1.0),
        ParameterSpec("force_internal", "boolean", False, "强制使用内置引擎", advanced=True),
    ]

    # -- internals ------------------------------------------------------------ #
    def _resolve_material(self, inputs: Dict[str, Any]) -> Material:
        """Return the material to simulate, from the graph or from parameters."""
        incoming = first_of(inputs.get("material"), Material, required=False)
        if incoming is not None:
            return incoming
        molecule = first_of(inputs.get("material"), Molecule, required=False)
        if molecule is not None and molecule.formula:
            return build_material(molecule.formula, name=molecule.name or molecule.formula)
        formula = str(self.get_param("formula", "") or "").strip()
        if not formula:
            raise NodeInputError(
                f"{self.node_type()}: connect a material or set the 'formula' parameter"
            )
        lattice = {
            "a": float(self.get_param("a", 0.0) or 0.0),
            "b": float(self.get_param("b", 0.0) or 0.0),
            "c": float(self.get_param("c", 0.0) or 0.0),
            "alpha": float(self.get_param("alpha", 90.0) or 90.0),
            "beta": float(self.get_param("beta", 90.0) or 90.0),
            "gamma": float(self.get_param("gamma", 90.0) or 90.0),
        }
        return build_material(formula, lattice=lattice)

    # -- execution ------------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        material = self._resolve_material(inputs)
        result = run(
            "materials",
            material,
            backend=self.backend_name,
            calculation=str(self.get_param("calculation", "scf")),
            functional=str(self.get_param("functional", "pbe")),
            cutoff_ev=float(self.get_param("cutoff_ev", 520.0)),
            kpoints=int(self.get_param("kpoints", 4) or 4),
            lattice=str(self.get_param("lattice", "sc")),
            hopping=float(self.get_param("hopping", -1.0)),
            a=float(self.get_param("a", 10.33) or 10.33),
            b=float(self.get_param("b", 6.01) or 6.01),
            c=float(self.get_param("c", 4.69) or 4.69),
            alpha=float(self.get_param("alpha", 90.0) or 90.0),
            beta=float(self.get_param("beta", 90.0) or 90.0),
            gamma=float(self.get_param("gamma", 90.0) or 90.0),
            wavelength=float(self.get_param("wavelength", 1.5406) or 1.5406),
            exe_path=str(self.get_param("exe_path", "") or ""),
            timeout=float(self.get_param("timeout_s", 1800.0)),
            force_internal=bool(self.get_param("force_internal", False)),
            workdir=Path(ctx.run_dir) if ctx is not None else None,
        )
        self.log(f"{self.node_type()} -> {result.engine}")
        return result.ports


@register_node
class VASPNode(SolidStateNode):
    """VASP SCF / relaxation / band / DOS / XRD wrapper."""

    name = "VASP"
    category = "Simulation/Materials"
    description = "生成 VASP/POSCAR 输入并运行；未安装时使用内置紧束缚引擎。"
    version = "0.7.1"
    tags = ["simulation", "materials", "vasp", "dft"]
    aliases = ["VASP"]
    icon = "VA"
    executable = "vasp_std"
    backend_name = "vasp"


@register_node
class QuantumESPRESSONode(SolidStateNode):
    """Quantum ESPRESSO (pw.x) wrapper."""

    name = "Quantum ESPRESSO"
    category = "Simulation/Materials"
    description = "生成 Quantum ESPRESSO 输入并运行；未安装时使用内置紧束缚引擎。"
    version = "0.7.1"
    tags = ["simulation", "materials", "quantum-espresso", "pw"]
    aliases = ["QuantumESPRESSO", "QE", "pw.x"]
    icon = "QE"
    executable = "pw.x"
    backend_name = "quantum_espresso"
