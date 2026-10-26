"""Agent planner: natural language question -> execution plan.

The planner is the first stage of the agent pipeline::

    User Question -> Planner -> Plan(steps) -> Tool Selector -> Workflow Generator

It works in two modes:

* **rule based** (always available): intent detection over a scientific
  vocabulary, plus reusable *recipes* that describe an explicit DAG of node
  types with verified port wiring.
* **LLM assisted** (when a provider is configured): the question and the node
  catalogue are sent to the model, which returns a plan as JSON.  Anything the
  model cannot parse falls back to the rule based planner, so the agent never
  becomes useless because an API key is missing.

Recipes are plain data -- adding a new scientific capability is a matter of
appending a recipe, not of touching the planner logic.  Every recipe mirrors a
hand verified workflow, which is why the generated graphs always validate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow_engine.utils import new_id

__all__ = ["PlanStep", "Plan", "Planner", "RECIPES", "detect_intent"]


# --------------------------------------------------------------------------- #
# Plan model
# --------------------------------------------------------------------------- #
@dataclass
class PlanStep:
    """One step of a plan: a node to run, its inputs and why it was chosen."""

    node_type: str
    node_id: str = ""
    inputs: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "node_id": self.node_id,
            "inputs": dict(self.inputs),
            "params": dict(self.params),
            "reason": self.reason,
        }


@dataclass
class Plan:
    """An ordered list of steps plus the intent that produced it."""

    intent: str
    question: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    engine: str = "rule-based"
    notes: List[str] = field(default_factory=list)

    @property
    def node_types(self) -> List[str]:
        return [step.node_type for step in self.steps]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": new_id("plan_"),
            "intent": self.intent,
            "question": self.question,
            "engine": self.engine,
            "notes": list(self.notes),
            "steps": [step.to_dict() for step in self.steps],
        }


# --------------------------------------------------------------------------- #
# Intent detection
# --------------------------------------------------------------------------- #
#: Keyword -> intent.  Chinese and English scientific vocabulary.
INTENT_KEYWORDS: Dict[str, List[str]] = {
    "unknown_compound": [
        "未知", "鉴定", "identif", "unknown", "what is this", "这是什么",
        "结构解析", "elucidat", "compound analysis",
    ],
    "material_discovery": [
        "材料", "电池", "正极", "负极", "催化", "material", "battery", "cathode",
        "anode", "discover", "发现", "筛选",
    ],
    "spectrum_analysis": [
        "谱图", "平滑", "基线", "峰", "spectrum", "smooth", "baseline", "peak",
        "处理", "process",
    ],
    "property_prediction": [
        "预测", "性质", "predict", "property", "logp", "溶解度", "solubility",
        "毒性", "toxicity",
    ],
    "similarity_search": [
        "相似", "检索", "similar", "search", "库", "library", "匹配", "match",
    ],
    "quantum_chemistry": [
        "量化", "量子", "dft", "orca", "gaussian", "单点能", "优化",
        "optimis", "optimiz", "energy",
    ],
    "solid_state_dft": [
        "能带", "带隙", "态密度", "能带态密度", "原胞", "晶格常数", "晶胞",
        "弛豫", "几何优化", "费米", "金属", "半导体",
        "band structure", "band gap", "density of states", "dos", "pdos",
        "primitive cell", "lattice constant", "relax", "geometry opt",
        "fermi", "metal", "semiconductor", "work function",
    ],
    "report": ["报告", "report", "总结", "summary", "导出"],
}


def detect_intent(question: str) -> str:
    """Return the intent whose keywords best match ``question``."""
    text = (question or "").lower()
    if not text.strip():
        return "general"
    best_intent = "general"
    best_score = 0
    for intent, keywords in INTENT_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score > best_score:
            best_intent, best_score = intent, score
    return best_intent


# --------------------------------------------------------------------------- #
# Recipes -- explicit DAGs mirroring hand verified workflows
# --------------------------------------------------------------------------- #
#: ``inputs`` maps a target port to ``"<step_id>"`` (first output port) or
#: ``"<step_id>.<port>"``.  ``data_key`` names the planner extracted value
#: (a file path, a formula, a SMILES) that should be injected into ``params``.
RECIPES: Dict[str, Dict[str, Any]] = {
    "unknown_compound": {
        "description": "未知化合物鉴定：MS + NMR + IR 多证据融合",
        "steps": [
            {
                "id": "ms_file",
                "type": "SpectrumFileNode",
                "data_key": "path",
                "params": {"mode": "MS"},
                "why": "读取质谱原始数据（通用格式或厂商格式）",
            },
            {
                "id": "library",
                "type": "TableFileNode",
                "params": {"path": "datasets/demo/molecule_library.csv"},
                "why": "载入本地分子库作为候选池",
            },
            {
                "id": "ms_peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "ms_file.spectrum"},
                "params": {"prominence": 0.03, "max_peaks": 100},
                "why": "提取分子离子与碎片峰",
            },
            {
                "id": "ms_smooth",
                "type": "SmoothingNode",
                "inputs": {"spectrum": "ms_peaks.spectrum"},
                "params": {"method": "savitzky_golay", "window": 9, "polyorder": 3},
                "why": "Savitzky-Golay 平滑去噪",
            },
            {
                "id": "nmr",
                "type": "NMRNode",
                "params": {"smiles": "CCO", "nucleus": "1H", "frequency_mhz": 400.0},
                "why": "由候选结构模拟 1H NMR 化学位移",
            },
            {
                "id": "ir",
                "type": "IRNode",
                "params": {"smiles": "CCO", "points": 1800, "noise": 0.004},
                "why": "模拟红外官能团谱带",
            },
            {
                "id": "identify",
                "type": "UnknownCompoundIdentificationNode",
                "inputs": {
                    "ms": "ms_smooth.spectrum",
                    "nmr": "nmr.spectrum",
                    "ir": "ir.spectrum",
                    "candidates": "library.table",
                },
                "params": {"adduct": "[M+H]+", "mass_tolerance_ppm": 20.0, "top_k": 5},
                "why": "多证据融合（MS + NMR + IR + 库）给出候选结构",
            },
            {
                "id": "candidates",
                "type": "ExportNode",
                "inputs": {"data": "identify.table"},
                "params": {"filename": "identification_candidates", "format": "csv"},
                "why": "导出候选结构 CSV",
            },
            {
                "id": "report",
                "type": "ReportBuilderNode",
                "inputs": {
                    "molecule": "identify.molecule",
                    "table": "identify.table",
                    "text": "identify.text",
                },
                "params": {"title": "未知化合物结构鉴定报告"},
                "why": "汇总证据链生成报告",
            },
            {
                "id": "report_md",
                "type": "ReportExportNode",
                "inputs": {"report": "report.report"},
                "params": {"format": "html", "filename": "identification_report"},
                "why": "导出 HTML 报告",
            },
        ],
    },
    "material_discovery": {
        "description": "材料发现：XRD + SEM + XPS + 数据库 + 排序",
        "steps": [
            {
                "id": "material",
                "type": "MaterialInputNode",
                "data_key": "formula",
                "params": {"formula": "LiFePO4"},
                "why": "提供候选材料（化学式或晶胞）",
            },
            {
                "id": "xrd",
                "type": "XRDNode",
                "inputs": {"sample": "material.material"},
                "params": {"two_theta_max": 90.0},
                "why": "粉末衍射模拟物相",
            },
            {
                "id": "xrd_peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "xrd.spectrum"},
                "params": {"prominence": 0.03, "max_peaks": 100},
                "why": "XRD 峰检索与指标化",
            },
            {
                "id": "sem",
                "type": "SEMNode",
                "inputs": {"sample": "material.material"},
                "params": {"magnification": 20000},
                "why": "形貌与粒径统计",
            },
            {
                "id": "xps",
                "type": "XPSNode",
                "inputs": {"sample": "material.material"},
                "why": "表面元素与价态",
            },
            {
                "id": "discover",
                "type": "MaterialDiscoveryNode",
                "inputs": {
                    "xrd": "xrd.spectrum",
                    "sem": "sem.image",
                    "xps": "xps.spectrum",
                    "candidates": "material.material",
                },
                "params": {"target_property": "capacity_gravimetric", "top_k": 5},
                "why": "按目标性质（比容量/电压/带隙）排序候选",
            },
            {
                "id": "summary",
                "type": "SummaryTableNode",
                "inputs": {
                    "material": "discover.material",
                    "table": "discover.table",
                },
                "why": "候选性质汇总表",
            },
            {
                "id": "export",
                "type": "ReportExportNode",
                "inputs": {"text": "discover.text"},
                "params": {"format": "html", "filename": "material_discovery_report"},
                "why": "导出决策报告",
            },
        ],
    },
    "spectrum_analysis": {
        "description": "谱图处理：基线 -> 平滑 -> 峰提取 -> 归一化",
        "steps": [
            {
                "id": "ingest",
                "type": "SpectrumFileNode",
                "data_key": "path",
                "params": {"mode": "Generic"},
                "why": "读取谱图",
            },
            {
                "id": "baseline",
                "type": "BaselineCorrectionNode",
                "inputs": {"spectrum": "ingest.spectrum"},
                "params": {"method": "als"},
                "why": "基线校正",
            },
            {
                "id": "smooth",
                "type": "SmoothingNode",
                "inputs": {"spectrum": "baseline.spectrum"},
                "params": {"method": "savitzky_golay", "window": 9, "polyorder": 3},
                "why": "平滑去噪",
            },
            {
                "id": "peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "smooth.spectrum"},
                "params": {"prominence": 0.03, "max_peaks": 100},
                "why": "峰提取",
            },
            {
                "id": "normalize",
                "type": "NormalizeNode",
                "inputs": {"spectrum": "peaks.spectrum"},
                "params": {"method": "max"},
                "why": "归一化强度",
            },
        ],
    },
    "property_prediction": {
        "description": "分子性质预测：描述符 -> 预测",
        "steps": [
            {
                "id": "molecule",
                "type": "MoleculeInputNode",
                "data_key": "smiles",
                "params": {"smiles": "CCO"},
                "why": "输入分子（SMILES）",
            },
            {
                "id": "descriptors",
                "type": "MolecularDescriptorsNode",
                "inputs": {"molecule": "molecule.molecule"},
                "why": "计算分子描述符",
            },
            {
                "id": "predict",
                "type": "PropertyPredictionNode",
                "inputs": {"molecule": "descriptors.molecule"},
                "params": {},
                "why": "预测目标性质",
            },
        ],
    },
    "similarity_search": {
        "description": "相似性检索：指纹比对",
        "steps": [
            {
                "id": "query",
                "type": "MoleculeInputNode",
                "data_key": "smiles",
                "params": {"smiles": "CCO"},
                "why": "查询分子",
            },
            {
                "id": "library",
                "type": "TableFileNode",
                "params": {"path": "datasets/demo/molecule_library.csv"},
                "why": "载入分子库",
            },
            {
                "id": "search",
                "type": "SimilaritySearchNode",
                "inputs": {"query": "query.molecule", "library": "library.table"},
                "params": {"top_k": 10},
                "why": "指纹相似性检索",
            },
        ],
    },
    "quantum_chemistry": {
        "description": "量子化学：ORCA 输入生成 + 内置 EHT 求解",
        "steps": [
            {
                "id": "molecule",
                "type": "MoleculeInputNode",
                "data_key": "smiles",
                "params": {"smiles": "CCO"},
                "why": "输入分子",
            },
            {
                "id": "quantum",
                "type": "ORCANode",
                "inputs": {"molecule": "molecule.molecule"},
                "params": {"method": "b3lyp", "basis": "def2-SVP"},
                "why": "生成 ORCA 输入并用内置 EHT 求解",
            },
            {
                "id": "report",
                "type": "ReportBuilderNode",
                "inputs": {"molecule": "quantum.molecule", "text": "quantum.text"},
                "params": {"title": "电子结构报告"},
                "why": "整理电子结构结论",
            },
        ],
    },
    # Reproduces the reference case end to end: relax the primitive cell, then
    # compute the band structure and the orbital-resolved density of states from
    # the *relaxed* cell, and report.  The ordering matters -- running bands at
    # the unrelaxed ``a`` is the single most common way to report a band
    # structure that does not correspond to the crystal under discussion.
    "solid_state_dft": {
        "description": "固态 DFT：原胞弛豫 -> 能带 / 态密度 / 投影态密度 -> 6 张产物图 -> 报告",
        "steps": [
            {
                "id": "material",
                "type": "MaterialInputNode",
                "data_key": "formula",
                "params": {"formula": "Al", "a": 0.0},
                "why": "给出目标元素/化学式；a=0 表示后续按晶格类型取实验值",
            },
            {
                "id": "relax",
                "type": "ABACUSNode",
                "inputs": {"material": "material.material"},
                "params": {
                    "calculation": "cell_relax",
                    "lattice": "fcc",
                    "relax_steps": 25,
                },
                "why": "晶胞弛豫，扫描晶格常数取总能量极小（内部 Slater-Koster 引擎）",
            },
            {
                "id": "bands",
                "type": "ABACUSNode",
                "inputs": {"material": "relax.material"},
                "params": {
                    "calculation": "bands",
                    "lattice": "fcc",
                    "band_points": 40,
                },
                "why": "在弛豫后的晶胞上沿高对称点路径 Γ-X-W-K-Γ-L-W-X 求能带",
            },
            {
                "id": "dos",
                "type": "ABACUSNode",
                "inputs": {"material": "relax.material"},
                "params": {
                    "calculation": "dos",
                    "lattice": "fcc",
                },
                "why": "总态密度：E_F 处是否非零是判断金属性的直接依据",
            },
            {
                "id": "pdos",
                "type": "ABACUSNode",
                "inputs": {"material": "relax.material"},
                "params": {
                    "calculation": "pdos",
                    "lattice": "fcc",
                },
                "why": "分轨道态密度：Al 的 s-p 杂化在 E_F 处非零，即金属性的来源",
            },
            {
                "id": "fig_bands",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "bands.spectrum"},
                "params": {"kind": "band_structure", "filename": "Al_能带图"},
                "why": "产物图 1/6：能带结构（含高对称点刻度与 E_F 参考线）",
            },
            {
                "id": "fig_dos",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "dos.spectrum"},
                "params": {"kind": "dos", "filename": "Al_态密度_DOS"},
                "why": "产物图 2/6：总态密度",
            },
            {
                "id": "fig_pdos",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "pdos.spectrum"},
                "params": {"kind": "pdos", "filename": "Al_投影态密度_PDOS"},
                "why": "产物图 3/6：s / px / py / pz 四通道投影态密度",
            },
            {
                "id": "fig_relax_energy",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "relax.spectrum"},
                "params": {
                    "kind": "relax_convergence",
                    "filename": "Al_弛豫能量收敛",
                    "trace": 1,
                },
                "why": "产物图 4/6：弛豫能量收敛（线性轴）",
            },
            {
                "id": "fig_relax_force",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "relax.spectrum"},
                "params": {
                    "kind": "relax_convergence",
                    "filename": "Al_弛豫力收敛",
                    "trace": 2,
                },
                "why": "产物图 5/6：残余力收敛（对数轴）——弛豫是否真的收敛要看它，不看能量",
            },
            {
                "id": "fig_relax_stress",
                "type": "FigureExportNode",
                "inputs": {"spectrum": "relax.spectrum"},
                "params": {
                    "kind": "relax_convergence",
                    "filename": "Al_弛豫应力收敛",
                    "trace": 3,
                },
                "why": "产物图 6/6：残余应力收敛（对数轴）",
            },
            {
                "id": "summary",
                "type": "SummaryTableNode",
                "inputs": {
                    "material": "relax.material",
                    "table": "bands.table",
                },
                "params": {"max_rows": 40},
                "why": "把弛豫结果与能带指标汇成一张表",
            },
            {
                "id": "report",
                "type": "ReportBuilderNode",
                "inputs": {
                    "material": "relax.material",
                    "table": "summary.table",
                    "text": "bands.text",
                    "spectrum": "pdos.spectrum",
                },
                "params": {"title": "原胞弛豫与能带态密度计算报告"},
                "why": "汇总弛豫、能带与态密度结论",
            },
            {
                "id": "export",
                "type": "ReportExportNode",
                "inputs": {"report": "report.report"},
                "params": {"format": "html", "filename": "solid_state_dft_report"},
                "why": "导出 HTML 报告",
            },
        ],
    },
    "report": {
        "description": "报告生成",
        "steps": [
            {
                "id": "report",
                "type": "ReportBuilderNode",
                "params": {"title": "科学报告"},
                "why": "构建报告",
            },
            {
                "id": "export",
                "type": "ReportExportNode",
                "inputs": {"report": "report.report"},
                "params": {"format": "html", "filename": "report"},
                "why": "导出 MD/HTML",
            },
        ],
    },
    "general": {
        "description": "通用：读取 -> 处理 -> 报告",
        "steps": [
            {
                "id": "ingest",
                "type": "SpectrumFileNode",
                "data_key": "path",
                "params": {"mode": "Generic"},
                "why": "读取谱图",
            },
            {
                "id": "peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "ingest.spectrum"},
                "params": {"prominence": 0.03, "max_peaks": 100},
                "why": "峰提取",
            },
            {
                "id": "report",
                "type": "ReportBuilderNode",
                "inputs": {"table": "peaks.table", "text": "peaks.text"},
                "params": {"title": "谱图分析报告"},
                "why": "生成报告",
            },
        ],
    },
}

#: Data the planner looks for in the question.  Each entry maps a regular
#: expression to the recipe parameter it feeds.
_DATA_PATTERNS: List[Dict[str, str]] = [
    {"pattern": r"([A-Za-z0-9_./-]+\.(?:mzml|mzxml|mgf|msp|jdx|dx|xy|txt|csv))", "key": "path"},
    {"pattern": r"([A-Za-z0-9_./-]+\.raw)", "key": "path"},
    {"pattern": r"(LiFePO4|LiCoO2|NMC811|LiMn2O4|Si|Graphite)", "key": "formula"},
    {"pattern": r"\b([A-Za-z]{1,3}(?:=[O,S,N,P]|#[N]|@)?[CcNnOoSsPp\(\)\[\]0-9@+\-]{4,})\b", "key": "smiles"},
]


def extract_data(question: str) -> Dict[str, str]:
    """Pull a file path / formula / SMILES out of the question."""
    found: Dict[str, str] = {}
    for entry in _DATA_PATTERNS:
        match = re.search(entry["pattern"], question or "", flags=re.IGNORECASE)
        if match and entry["key"] not in found:
            found[entry["key"]] = match.group(1)
    return found


# --------------------------------------------------------------------------- #
# Planner
# --------------------------------------------------------------------------- #
#: Prompt asking an LLM to emit a plan as JSON.  ``{catalog}`` is replaced with
#: the registered node types **and their parameter schemas** so the model can
#: only pick real nodes *and* only set real parameters.
#:
#: The parameter schema used to be missing entirely -- the catalogue showed one
#: truncated description per node type, so the model had no way to learn that
#: ``ABACUSNode`` takes ``calculation``/``lattice``/``a``.  It therefore emitted
#: plans with an empty ``params`` on every step, which validate cleanly and then
#: run the wrong calculation on default settings: the plan looked planned while
#: the artefact was still wrong.  Prompting a planner without the parameter
#: names produces exactly that failure.
_PLAN_PROMPT = (
    "You are the planner of the Chem ML Platform, a node based scientific "
    "workflow engine.  Given a scientific question, choose the minimal chain "
    "of nodes that answers it.\n\n"
    "Available node types (each with the parameters it accepts):\n{catalog}\n\n"
    "Rules:\n"
    "- Use only the node types listed above, spelled exactly as listed.\n"
    "- Use only the parameter names listed for that node.\n"
    "- For an enum parameter use one of the listed values verbatim.\n"
    "- Wire inputs as \"<step_id>.<output_port>\", using the listed ports.\n"
    "- Set parameters whenever the question implies a value: an element, "
    "a lattice, a calculation type, or a numeric setting.\n\n"
    'Answer ONLY with JSON: {{"intent": "<short intent>", "steps": '
    '[{{"node_type": "<registered type>", "id": "<short id>", '
    '"inputs": {{"<port>": "<step_id>.<port>"}}, "params": {{}}, '
    '"reason": "<why>"}}]}}\n\n'
    "Question: {question}\n"
)

def _enum_values(raw: Any) -> List[str]:
    """Flatten a parameter's option list into the values a caller may pass.

    Options are ``(value, label)`` tuples in the node registry but bare strings
    in some hand-built specs, so both shapes are accepted.  Labels are dropped:
    the prompt must show the value to use, and showing both invites the model
    to emit the Chinese label into a field that expects the English token.
    """
    values: List[str] = []
    for item in raw or []:
        if isinstance(item, (list, tuple)) and item:
            values.append(str(item[0]))
        elif item is not None:
            values.append(str(item))
    return values


def _catalog_entry(node_type: str, spec: Dict[str, Any]) -> str:
    """One catalogue line: what the node is, what it consumes and accepts.

    The parameter list is the point of this function.  A planner shown only a
    prose description cannot set ``calculation="pdos"``, because nothing in the
    description says that parameter exists -- so it emits ``params: {}`` and the
    plan runs on defaults while looking correct.
    """
    lines = [f"- {node_type}: {str(spec.get('description', ''))[:110]}"]
    ports = [str(port.get("name", "")) for port in spec.get("inputs") or []]
    ports = [name for name in ports if name]
    if ports:
        lines.append(f"    in: {', '.join(ports)}")
    outputs = [str(port.get("name", "")) for port in spec.get("outputs") or []]
    outputs = [name for name in outputs if name]
    if outputs:
        lines.append(f"    out: {', '.join(outputs)}")
    parameters = spec.get("parameters") or []
    if parameters:
        parts: List[str] = []
        for parameter in parameters:
            name = str(parameter.get("name", ""))
            if not name:
                continue
            kind = str(parameter.get("type", "string"))
            options = _enum_values(parameter.get("options"))
            if options:
                shown = ", ".join(options[:12])
                if len(options) > 12:
                    shown += ", ..."
                parts.append(f"{name}({kind}: {shown})")
            else:
                default = parameter.get("default")
                if default in (None, "", 0, 0.0, False):
                    parts.append(f"{name}({kind})")
                else:
                    parts.append(f"{name}({kind}, default {default!r})")
        if parts:
            lines.append(f"    params: {'; '.join(parts)}")
    return "\n".join(lines)


#: Node type -> the parameter that carries the ingested datum.
_INPUT_PARAM = {
    "MoleculeInputNode": "smiles",
    "MaterialInputNode": "formula",
    "SpectrumFileNode": "path",
    "TableFileNode": "path",
}


def _apply_context_data(plan: "Plan", context: Optional[Dict[str, Any]]) -> None:
    """Seed input nodes with the data the caller already knows about."""
    data = dict((context or {}).get("data") or {})
    if not data:
        return
    for step in plan.steps:
        parameter = _INPUT_PARAM.get(step.node_type)
        if parameter and not step.params.get(parameter) and data.get(parameter):
            step.params[parameter] = data[parameter]


class Planner:
    """Turns a question into a :class:`Plan`."""

    def __init__(self, catalog: Optional[List[Dict[str, Any]]] = None) -> None:
        #: ``{node_type: spec}`` of everything the platform can run.
        #:
        #: The key is read as ``type`` **or** ``node_type``.  Only the second
        #: spelling is what the tool registry actually emits, and reading just
        #: ``type`` produced an empty catalogue for every real agent run -- the
        #: prompt then said "(no node catalogue available)" and the model, quite
        #: correctly, could not plan a workflow out of nothing.  It failed
        #: quietly: the planner fell back to the recipe and reported success, so
        #: the cause was invisible from the outside.
        self.catalog: Dict[str, Dict[str, Any]] = {}
        for spec in catalog or []:
            if not isinstance(spec, dict):
                continue
            node_type = str(spec.get("type") or spec.get("node_type") or "").strip()
            if node_type:
                self.catalog[node_type] = spec

    # -- public API --------------------------------------------------------- #
    def plan(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        *,
        use_llm: bool = False,
    ) -> Plan:
        """Build a plan for ``question``.

        ``context`` may carry ``data`` (``{"path": ..., "formula": ...}``
        supplied by the caller) and ``available`` (an explicit list of node
        types the agent is allowed to use).

        When ``use_llm`` is set the LLM is asked first (through
        :func:`ai_runtime.complete`, so it honours the cloud / local / offline
        mode); an unavailable or unparseable answer transparently falls back to
        the rule based recipe and the fallback is recorded in ``plan.notes``.
        """
        context = dict(context or {})
        intent = detect_intent(question)
        data: Dict[str, str] = dict(context.get("data") or {})
        for key, value in extract_data(question).items():
            data.setdefault(key, value)

        available = context.get("available")
        recipe = RECIPES.get(intent) or RECIPES["general"]
        plan = Plan(intent=intent, question=question)

        llm_note = ""
        if use_llm:
            llm_plan = self.plan_with_llm(question, context)
            if llm_plan is not None and llm_plan.steps:
                return llm_plan
            llm_note = "LLM 规划不可用或无法解析，已回退规则规划器"

        for entry in recipe["steps"]:
            node_type = str(entry["type"])
            if available and node_type not in available:
                plan.notes.append(f"skipped {node_type}: not available in this run")
                continue
            params = dict(entry.get("params") or {})
            data_key = entry.get("data_key")
            if data_key and data.get(data_key):
                params[data_key] = data[data_key]
            # ``context['params']`` lets a caller override a specific step.
            overrides = context.get("params") or {}
            if node_type in overrides:
                params.update(overrides[node_type])
            plan.steps.append(
                PlanStep(
                    node_type=node_type,
                    node_id=str(entry.get("id") or node_type),
                    inputs=dict(entry.get("inputs") or {}),
                    params=params,
                    reason=str(entry.get("why", "")),
                )
            )

        if not plan.steps:
            plan.notes.append(f"no recipe produced steps for intent {intent!r}")
        for step in plan.steps:
            if self.catalog and step.node_type not in self.catalog:
                plan.notes.append(
                    f"{step.node_type} is not registered in this installation"
                )
        if llm_note:
            plan.notes.append(llm_note)
        plan.engine = "rule-based"
        return plan

    def plan_with_llm(
        self,
        question: str,
        context: Optional[Dict[str, Any]] = None,
        complete: Optional[Any] = None,
    ) -> Optional[Plan]:
        """Ask an LLM for a plan; ``None`` when it is unavailable or unparseable.

        ``complete`` defaults to :func:`ai_runtime.complete`, which honours the
        configured AI mode.  An answer produced by the *offline* engine is
        rejected on purpose: the offline engine is a keyword reasoner, not a
        planner, so the deterministic rule recipe is the better fallback.
        """
        if complete is None:
            try:
                from ai_runtime import complete as _complete

                complete = _complete
            except Exception:  # pragma: no cover - ai_runtime always importable
                return None

        catalog_lines = "\n".join(
            _catalog_entry(node_type, spec)
            for node_type, spec in sorted(self.catalog.items())
        ) or "(no node catalogue available)"
        prompt = _PLAN_PROMPT.format(catalog=catalog_lines, question=question)

        try:
            result = complete(prompt, family="auto")
        except Exception:
            return None
        if getattr(result, "family", "") == "offline":
            return None
        plan = self.plan_from_llm(question, getattr(result, "text", "") or "")
        if plan is None:
            return None
        if self.catalog:
            plan.steps = [step for step in plan.steps if step.node_type in self.catalog]
        _apply_context_data(plan, context)
        plan.engine = f"llm:{getattr(result, 'engine', 'llm')}"
        return plan if plan.steps else None

    def plan_from_llm(self, question: str, completion: str) -> Optional[Plan]:
        """Parse a plan out of an LLM completion (``None`` when unparseable).

        Model-emitted parameters are **checked against the node spec**, not
        trusted.  A parameter the node does not declare is dropped and recorded
        in ``plan.notes`` rather than passed through: nodes store unknown
        params in ``self.params`` and never read them, so a hallucinated name
        looks accepted, survives validation, and quietly does nothing.  The
        note is what turns "my plan did not take effect" into a diagnosis.

        Enum values are validated the same way, except that a value matching a
        declared option's *label* is rewritten to its value -- a model asked for
        the Chinese label of an option has not made a mistake worth discarding a
        whole plan over.
        """
        payload = _extract_json(completion)
        if not isinstance(payload, dict):
            return None
        steps = payload.get("steps")
        if not isinstance(steps, list) or not steps:
            return None
        plan = Plan(
            intent=str(payload.get("intent") or detect_intent(question)),
            question=question,
            engine="llm",
        )
        for index, raw in enumerate(steps):
            if not isinstance(raw, dict):
                continue
            node_type = str(raw.get("node_type") or raw.get("type") or "").strip()
            if not node_type:
                continue
            params = self._clean_params(node_type, raw.get("params"), plan)
            plan.steps.append(
                PlanStep(
                    node_type=node_type,
                    node_id=str(raw.get("id") or f"llm_{index}"),
                    inputs=dict(raw.get("inputs") or {}),
                    params=params,
                    reason=str(raw.get("reason", "") or ""),
                )
            )
        return plan if plan.steps else None

    def _clean_params(
        self, node_type: str, raw: Any, plan: Plan
    ) -> Dict[str, Any]:
        """Drop parameters the node does not declare; record what was dropped."""
        if not isinstance(raw, dict):
            return {}
        spec = self.catalog.get(node_type) or {}
        declared = {
            str(parameter.get("name", "")): parameter
            for parameter in (spec.get("parameters") or [])
            if parameter.get("name")
        }
        if not declared:
            # No schema available (empty catalogue): pass through untouched
            # rather than deleting parameters the platform may well accept.
            return dict(raw)

        cleaned: Dict[str, Any] = {}
        for key, value in raw.items():
            parameter = declared.get(str(key))
            if parameter is None:
                plan.notes.append(
                    f"{node_type}: dropped unknown parameter {key!r}"
                )
                continue
            options = _enum_values(parameter.get("options"))
            if options and value is not None:
                text = str(value)
                if text not in options:
                    labels = {}
                    for item in parameter.get("options") or []:
                        if isinstance(item, (list, tuple)) and len(item) > 1:
                            labels[str(item[1])] = str(item[0])
                    if text in labels:
                        value = labels[text]
                    else:
                        plan.notes.append(
                            f"{node_type}.{key}: dropped {text!r}, "
                            f"not one of {options[:8]}"
                        )
                        continue
            cleaned[str(key)] = value
        return cleaned


def _extract_json(text: str) -> Any:
    """Pull the first JSON object out of a model completion."""
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
