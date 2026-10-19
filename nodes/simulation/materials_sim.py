"""Solid-state / plane-wave DFT nodes backed by :mod:`simulation_runtime`.

``VASP`` and Quantum ESPRESSO are driven through their command line interface when
installed; otherwise the runtime falls back to the built-in **tight-binding**
engine (:mod:`simulations.tight_binding`) plus a powder XRD pattern
(:func:`models.materials.simulate_xrd`).  The engine that answered is recorded in
``Text.data["engine"]``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from simulation_runtime import run
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Material, Molecule, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import build_material, first_of

__all__ = ["SolidStateNode", "VASPNode", "QuantumESPRESSONode", "ABACUSNode"]

CALCULATIONS = ["scf", "relax", "cell_relax", "bands", "dos", "pdos", "xrd"]
FUNCTIONALS = ["pbe", "pbesol", "lda", "scan", "hse06"]
LATTICE_KEYS = ("sc", "bcc", "fcc", "hcp")


class SolidStateNode(ScientificNode):
    """Shared behaviour of the solid state simulation nodes."""

    category = "Simulation/Materials"
    capabilities = ["requires_external_software", "experimental"]
    implementation_status = "experimental"
    # -- v0.7.2 task P0-05: execution provenance ------------------------ #
    capability_status = "experimental"
    execution_mode = "internal_approximation"
    required_dependencies = ["vasp (vasp_std)", "quantum_espresso (pw.x)", "abacus", "cp2k"]
    input_constraints = (
        "需要 Material 或带晶格的 Molecule；支持 sc/bcc/fcc/hcp 四种晶格语义，"
        "默认取原胞。不接受实验测量的非理想结构（缺陷、表面、非晶）。"
    )
    validation_evidence = []
    limitations = [
        "内置 Slater-Koster 紧束缚 / 近自由电子模型，能带与态密度反映元素、晶格常数与"
        "压缩的正确趋势；晶格常数弛豫对 Al fcc 误差约 1%，过渡金属约 10%，属定性结果。",
        "未安装 VASP / Quantum ESPRESSO / ABACUS / CP2K 时结果必须视为近似，"
        "engine 字段会标注 internal:tight-binding。",
        "两中心模型每个晶胞只处理一种元素；多元素化合物按过渡金属优先取一种计算，属已知近似。",
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
        ParameterSpec("formula", "string", "Al", "化学式（无上游时使用）"),
        ParameterSpec("element", "string", "", "元素符号（留空从化学式推断，如 Al）",
                      advanced=True),
        ParameterSpec("calculation", "enum", "scf", "计算类型", options=CALCULATIONS),
        ParameterSpec("functional", "enum", "pbe", "泛函", options=FUNCTIONALS),
        ParameterSpec("cutoff_ev", "number", 520.0, "平面波截断能", unit="eV", min=50.0),
        ParameterSpec("kpoints", "integer", 4, "k 点网格", min=1, max=32),
        ParameterSpec("lattice", "enum", "fcc", "Bravais 格子", options=list(LATTICE_KEYS)),
        ParameterSpec(
            "a", "number", 0.0,
            "晶格常数 a（Å）。0 = 用材料自带值或实验值；例如 Al fcc 为 4.05",
            unit="Å",
        ),
        ParameterSpec("hopping", "number", 0.0,
                      "跃迁积分整体缩放（eV，0 = 用元素表默认值）", advanced=True),
        ParameterSpec("band_points", "integer", 40, "能带路径每段取点数", min=8, max=200,
                      advanced=True),
        ParameterSpec("relax_steps", "integer", 25, "晶格弛豫最大步数", min=1, max=200,
                      advanced=True),
        ParameterSpec("b", "number", 0.0, "晶胞参数 b（XRD 用）", unit="Å", advanced=True),
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
        return self._run(inputs, ctx)

    def _run(
        self, inputs: Dict[str, Any], ctx: Any = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Shared body of every solid-state node.

        ``extra`` lets a subclass add back-end specific parameters without
        copying the whole call -- duplicating this dispatch is how the ABACUS
        node would have ended up forwarding a different default for ``a`` than
        VASP does, which is the exact class of drift this method exists to stop.
        """
        material = self._resolve_material(inputs)
        # Per-node output directory.  Every solid-state node writes a file with
        # a *fixed* name -- ``tb.in``, ``INPUT``, ``Al_primitive.STRU`` -- so two
        # of them sharing one directory overwrite each other.  That is invisible
        # while the engine runs generation by generation with one worker, and
        # becomes a real data race the moment independent calculations (bands,
        # pdos) run concurrently: both write `Al_primitive.STRU`, and which one
        # survives is decided by thread timing.  Keying the directory on the
        # node id also matches the platform rule that products are named by id
        # and never overwrite.
        workdir = None
        if ctx is not None:
            workdir = Path(ctx.run_dir) / str(self.node_id or self.node_type())
        # ``a`` used to be forwarded as ``get_param("a", 10.33) or 10.33``, which
        # meant the node never passed 0 and the back-end could not tell "user set
        # 10.33" from "user set nothing" -- so every solid-state run silently used
        # a 10.33 Å cell whatever the element.  Passing the real value lets the
        # back-end resolve it (parameter -> material -> measured) and say which
        # one it used.
        result = run(
            "materials",
            material,
            backend=self.backend_name,
            calculation=str(self.get_param("calculation", "scf")),
            functional=str(self.get_param("functional", "pbe")),
            cutoff_ev=float(self.get_param("cutoff_ev", 520.0)),
            kpoints=int(self.get_param("kpoints", 4) or 4),
            lattice=str(self.get_param("lattice", "fcc")),
            element=str(self.get_param("element", "") or ""),
            hopping=float(self.get_param("hopping", 0.0) or 0.0),
            band_points=int(self.get_param("band_points", 40) or 40),
            relax_steps=int(self.get_param("relax_steps", 25) or 25),
            a=float(self.get_param("a", 0.0) or 0.0),
            b=float(self.get_param("b", 0.0) or 0.0),
            c=float(self.get_param("c", 0.0) or 0.0),
            alpha=float(self.get_param("alpha", 90.0) or 90.0),
            beta=float(self.get_param("beta", 90.0) or 90.0),
            gamma=float(self.get_param("gamma", 90.0) or 90.0),
            wavelength=float(self.get_param("wavelength", 1.5406) or 1.5406),
            exe_path=str(self.get_param("exe_path", "") or ""),
            timeout=float(self.get_param("timeout_s", 1800.0)),
            force_internal=bool(self.get_param("force_internal", False)),
            workdir=workdir,
            **(extra or {}),
        )
        text = result.ports.get("text")
        self.log(f"{self.node_type()} -> {result.engine}")
        if text is not None and getattr(text, "text", ""):
            # Surface the headline result in the node log too: a user reading the
            # console should not have to open the inspector to learn whether the
            # run was a metal.
            self.log(str(text.text)[:200])
        return result.ports


@register_node
class ABACUSNode(SolidStateNode):
    """ABACUS SCF / relaxation / band / DOS / XRD wrapper.

    Writes a complete ``INPUT`` + ``STRU`` deck whether or not ABACUS is
    installed, so the files can be taken to a cluster that has it.
    """

    name = "ABACUS"
    category = "Simulation/Materials"
    description = (
        "生成 ABACUS 输入（INPUT/STRU）并运行；未安装时使用内置 Slater-Koster "
        "紧束缚引擎，输出 STRU、能带、态密度与分轨道态密度。"
    )
    tags = ["simulation", "materials", "abacus", "dft", "bands", "dos"]
    aliases = ["ABACUS", "abacus"]
    icon = "AB"
    executable = "abacus"
    backend_name = "abacus"

    parameters = list(SolidStateNode.parameters) + [
        ParameterSpec("orbital", "enum", "lcao", "轨道基组类型",
                      options=["lcao", "pw", "lcao_in_pw", "lialc"], advanced=True),
        ParameterSpec("ecutwfc", "number", 100.0,
                      "平面波截断能（Ry）。LCAO 基组下同样写入 INPUT",
                      unit="Ry", min=10.0, advanced=True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        return self._run(inputs, ctx, extra={
            "orbital": str(self.get_param("orbital", "lcao")),
            "ecutwfc": float(self.get_param("ecutwfc", 100.0) or 100.0),
        })


@register_node
class VASPNode(SolidStateNode):
    """VASP SCF / relaxation / band / DOS / XRD wrapper."""

    name = "VASP"
    category = "Simulation/Materials"
    description = "生成 VASP/POSCAR 输入并运行；未安装时使用内置紧束缚引擎。"
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
    tags = ["simulation", "materials", "quantum-espresso", "pw"]
    aliases = ["QuantumESPRESSO", "QE", "pw.x"]
    icon = "QE"
    executable = "pw.x"
    backend_name = "quantum_espresso"
