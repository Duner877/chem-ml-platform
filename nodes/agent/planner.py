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
                "params": {"technique": "MS", "mode": "EI-MS"},
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
                "params": {"height": 5.0, "prominence": 2.0, "limit": 40},
                "why": "提取分子离子与碎片峰",
            },
            {
                "id": "ms_smooth",
                "type": "SmoothingNode",
                "inputs": {"spectrum": "ms_peaks.spectrum"},
                "params": {"method": "savitzky_golay", "window": 9, "order": 3},
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
                "params": {"smiles": "CCO", "resolution_cm": 4.0},
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
                "params": {"height": 5.0, "prominence": 2.0, "limit": 40},
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
                "params": {"target": "capacity", "top_k": 5},
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
                "params": {"technique": "Generic"},
                "why": "读取谱图",
            },
            {
                "id": "baseline",
                "type": "BaselineCorrectionNode",
                "inputs": {"spectrum": "ingest.spectrum"},
                "params": {"method": "asls"},
                "why": "基线校正",
            },
            {
                "id": "smooth",
                "type": "SmoothingNode",
                "inputs": {"spectrum": "baseline.spectrum"},
                "params": {"method": "savitzky_golay", "window": 9, "order": 3},
                "why": "平滑去噪",
            },
            {
                "id": "peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "smooth.spectrum"},
                "params": {"height": 5.0, "prominence": 2.0, "limit": 40},
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
                "params": {"property": "logp"},
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
                "params": {"method": "B3LYP", "basis": "def2-SVP"},
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
                "params": {"technique": "Generic"},
                "why": "读取谱图",
            },
            {
                "id": "peaks",
                "type": "PeakPickingNode",
                "inputs": {"spectrum": "ingest.spectrum"},
                "params": {"height": 5.0, "prominence": 2.0, "limit": 40},
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
#: the registered node types so the model can only pick real nodes.
_PLAN_PROMPT = (
    "You are the planner of the Chem ML Platform, a node based scientific "
    "workflow engine.  Given a scientific question, choose the minimal chain "
    "of nodes that answers it.\n\n"
    "Available node types:\n{catalog}\n\n"
    'Answer ONLY with JSON: {{"intent": "<short intent>", "steps": '
    '[{{"node_type": "<registered type>", "id": "<short id>", '
    '"params": {{}}, "reason": "<why>"}}]}}\n\n'
    "Question: {question}\n"
)

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
        self.catalog: Dict[str, Dict[str, Any]] = {
            spec.get("type", ""): spec for spec in (catalog or []) if spec.get("type")
        }

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
            f"- {node_type}: {str(spec.get('description', ''))[:90]}"
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
        """Parse a plan out of an LLM completion (``None`` when unparseable)."""
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
            plan.steps.append(
                PlanStep(
                    node_type=node_type,
                    node_id=str(raw.get("id") or f"llm_{index}"),
                    inputs=dict(raw.get("inputs") or {}),
                    params=dict(raw.get("params") or {}),
                    reason=str(raw.get("reason", "") or ""),
                )
            )
        return plan if plan.steps else None


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
