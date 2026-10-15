"""ScientificAgentNode -- the agent as a first class workflow node.

The agent is **not** a chatbot.  It is a *Scientific Workflow Controller* that
owns the whole pipeline required by the specification::

    User Question
         |
         v
    +-------------------+     +----------------+     +--------------------+
    | Planner           | --> | Tool Selector  | --> | Workflow Generator |
    +-------------------+     +----------------+     +--------------------+
                                                                 |
                                                                 v
    +-------------------+     +----------------+     +--------------------+
    | Reasoning         | <-- | Node Execution | <-- |  generated DAG      |
    +-------------------+     +----------------+     +--------------------+
         |
         v
       Report

Everything runs offline: the rule based planner needs no API key, and the
built-in reasoner extracts the scientific content from the run result.  When an
LLM provider *is* configured the planner asks it for a plan first and falls
back to the rules when the answer cannot be parsed.

The node emits four ports so an agent can be dropped anywhere in a graph::

    question (Text)  -->  ScientificAgentNode  -->  report   (ScientificReport)
                                                 -->  workflow (Text, JSON)
                                                 -->  text     (Text, narrative)
                                                 -->  results  (Table, per node)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflow_engine.engine import WorkflowEngine
from workflow_engine.errors import NodeExecutionError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import ScientificObject, ScientificReport, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node
from workflow_engine.workflow import Workflow

from memory import get_memory
from nodes.agent.planner import Planner, detect_intent
from nodes.agent.reasoning import Reasoner
from nodes.agent.tools import tool_registry
from nodes.agent.workflow_generator import WorkflowGenerator

__all__ = [
    "ScientificAgentNode",
    "AgentPlanNode",
    "run_question",
    "plan_question",
    "summarise",
    "plan_only",
    "execute_plan",
    "finalise",
]


class _AgentBase(ScientificNode):
    """Shared plumbing: catalogue access, plan/run/reason."""

    category = "Agent"

    input_ports = [
        Port("question", "Text", "科学问题（自然语言）", optional=True),
        Port("context", "Any", "上游数据 / 上下文", optional=True, multi=True),
    ]
    output_ports = [
        Port("report", "ScientificReport", "结构化结论报告"),
        Port("workflow", "Text", "生成的工作流 JSON"),
        Port("text", "Text", "结论叙述"),
        Port("table", "Table", "逐节点执行结果"),
    ]
    parameters = [
        ParameterSpec("question", "text", "", "科学问题（也可由 question 端口传入）"),
        ParameterSpec("language", "enum", "zh", "报告语言",
                      options=[("zh", "中文"), ("en", "English")]),
        ParameterSpec("use_llm", "boolean", True, "允许调用 LLM 规划（不可用时自动回退）"),
        ParameterSpec("max_nodes", "integer", 12, "生成工作流的最大节点数", min=1, max=40),
        ParameterSpec("remember", "boolean", True, "把本次实验写入 Agent 记忆"),
    ]

    # -- catalogue ---------------------------------------------------------- #
    def _catalog(self) -> Dict[str, Dict[str, Any]]:
        tools = tool_registry()
        catalog: Dict[str, Dict[str, Any]] = {}
        for node_type in tools.types():
            tool = tools.get(node_type)
            if tool is not None:
                catalog[node_type] = tool.to_dict()
        return catalog

    def _question(self, inputs: Dict[str, Any]) -> str:
        value = inputs.get("question")
        if value is not None:
            text = getattr(value, "text", value)
            if isinstance(text, list):
                text = text[0] if text else ""
            if str(text).strip():
                return str(text).strip()
        return str(self.get_param("question", "") or "").strip()

    def _context_data(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """Turn upstream objects into planner data hints.

        v0.7.2 fix: the planner consumes *data-key* hints (``{"path": ...,
        "smiles": ..., "formula": ...}``, see ``Planner.plan`` /
        ``RECIPES[*].data_key``), not node-type keyed parameter maps.  The old
        node-type keyed dict was silently ignored, so a connected spectrum
        file never reached the generated sub-workflow and the plan failed on
        an empty ``path``.
        """
        data: Dict[str, Any] = {}
        # v0.7.2 fix: a single edge into the ``multi`` port arrives as *one*
        # object, not a list.  Pydantic models are iterable (field pairs), so
        # the old ``for item in context`` silently walked metadata instead of
        # the actual objects and every hint was lost.
        context = inputs.get("context")
        if context is None:
            branches: List[Any] = []
        elif isinstance(context, ScientificObject) or isinstance(context, (str, bytes)):
            branches = [context]
        elif isinstance(context, dict):
            branches = [context]
        else:
            branches = list(context)
        for item in branches:
            if isinstance(item, (list, tuple)):
                items = item
            else:
                items = [item]
            for entry in items:
                smiles = getattr(entry, "smiles", "")
                formula = getattr(entry, "formula", "")
                if smiles:
                    data.setdefault("smiles", str(smiles))
                if formula:
                    data.setdefault("formula", str(formula))
                pointer = getattr(entry, "data_pointer", "")
                if not pointer:
                    # Spectra loaded by SpectrumFileNode carry their origin in
                    # ``metadata["source_file"]`` -- reuse it so the planned
                    # sub-workflow reads the *same* measurement.
                    metadata = getattr(entry, "metadata", None) or {}
                    pointer = str(metadata.get("source_file", "") or "")
                if pointer:
                    data.setdefault("path", str(pointer))
        return data

    # -- pipeline ----------------------------------------------------------- #
    def _plan(self, question: str, data: Dict[str, Any]):
        planner = Planner(list(self._catalog().values()))
        use_llm = bool(self.get_param("use_llm", True))
        plan = planner.plan(question, context={"data": data}, use_llm=use_llm)
        max_nodes = int(self.get_param("max_nodes", 12) or 12)
        if len(plan.steps) > max_nodes:
            dropped = plan.steps[max_nodes:]
            plan.steps = plan.steps[:max_nodes]
            plan.notes.append(
                f"truncated to {max_nodes} nodes (dropped "
                + ", ".join(step.node_type for step in dropped)
                + ")"
            )
        return plan, planner

    def _run_plan(self, plan, planner: Planner) -> Dict[str, Any]:
        document = WorkflowGenerator(self._catalog()).generate(plan)
        workflow = Workflow.from_dict(document)
        issues = workflow.validate()
        if issues:
            # Retry with the linear chain only: drop steps that cannot be wired.
            plan.steps = [
                step for step in plan.steps if step.node_type in self._catalog()
            ]
            document = WorkflowGenerator(self._catalog()).generate(plan)
            workflow = Workflow.from_dict(document)
            issues = workflow.validate()
            if issues:
                raise NodeExecutionError(
                    self.node_id,
                    self.node_type(),
                    "generated workflow is invalid: " + "; ".join(issues),
                )
        engine = WorkflowEngine(max_workers=1, use_cache=False)
        return engine.run(workflow).to_dict()

    def _reason(self, result: Dict[str, Any]) -> Dict[str, Any]:
        language = str(self.get_param("language", "zh") or "zh")
        return Reasoner(language).reason(result)


@register_node
class ScientificAgentNode(_AgentBase):
    """Autonomous scientific agent: question -> plan -> workflow -> conclusion."""

    name = "Scientific Agent"
    description = (
        "AI 科学助手节点：理解自然语言科学问题，自动规划并生成工作流，"
        "调用节点执行，最后给出带置信度的结论与报告。"
    )
    tags = ["agent", "ai", "planner", "autonomous"]
    icon = "AG"

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        question = self._question(inputs)
        if not question:
            raise NodeExecutionError(
                self.node_id, self.node_type(), "no question provided"
            )
        memory = get_memory()
        memory.start_experiment(question, node_id=self.node_id)
        self.log(f"agent: question = {question!r}")

        data = self._context_data(inputs)
        plan, planner, _document = plan_only(self, question, data)
        intent = plan.intent
        self.log(
            f"planner ({plan.engine}): intent={intent}, "
            f"{len(plan.steps)} steps -> {', '.join(plan.node_types)}"
        )
        memory.record_step("plan", intent=intent, nodes=plan.node_types, engine=plan.engine)

        result = execute_plan(self, plan, planner)
        self.log(
            f"execution: {result.get('status')} "
            f"({len(result.get('records', {}))} nodes, "
            f"{float(result.get('duration_ms', 0) or 0):.0f} ms)"
        )
        memory.record_step("execute", status=result.get("status", ""))

        outputs = finalise(self, question, plan, result)
        analysis = outputs.pop("_analysis", {})
        memory.record_step("reason", findings=len(analysis.get("findings", [])))

        if self.get_param("remember", True):
            memory.remember_workflow(result)
            for finding in analysis.get("findings", [])[:5]:
                memory.record_finding(
                    finding["text"], confidence=finding.get("confidence", 0.0)
                )
            memory.end_experiment(result.get("status", "completed"))
            memory.save()

        return outputs

    # -- helpers ------------------------------------------------------------ #
    def _results_table(self, result: Dict[str, Any], plan) -> Table:
        records = result.get("records", {}) or {}
        columns = ["node", "type", "status", "duration_ms", "logs"]
        rows: List[List[Any]] = []
        for index, step in enumerate(plan.steps):
            node_id = step.node_id or f"{step.node_type}_{index}"
            record = records.get(node_id, {})
            rows.append(
                [
                    node_id,
                    step.node_type,
                    record.get("status", "skipped"),
                    round(float(record.get("duration_ms", 0) or 0), 2),
                    "; ".join(str(line) for line in (record.get("logs") or [])[:3]),
                ]
            )
        return Table(name="agent execution", columns=columns, rows=rows)


def _dump_workflow(result: Dict[str, Any]) -> str:
    """Pretty print the workflow the agent executed (best effort)."""
    import json

    payload = {
        "workflow": result.get("workflow", ""),
        "status": result.get("status", ""),
        "duration_ms": result.get("duration_ms", 0),
        "nodes": sorted((result.get("records", {}) or {}).keys()),
        "artifacts": result.get("artifacts", []),
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


@register_node
class AgentPlanNode(_AgentBase):
    """Plan only: emit the workflow the agent *would* run, without executing."""

    name = "Agent Planner"
    description = (
        "只做规划不执行：把自然语言问题转成工作流 JSON，"
        "便于人工审查后再运行。"
    )
    tags = ["agent", "planner", "dry-run"]
    icon = "AP"

    output_ports = [
        Port("workflow", "Text", "生成的工作流 JSON"),
        Port("text", "Text", "规划说明"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        question = self._question(inputs)
        if not question:
            raise NodeExecutionError(
                self.node_id, self.node_type(), "no question provided"
            )
        data = self._context_data(inputs)
        plan, _planner = self._plan(question, data)
        document = WorkflowGenerator(self._catalog()).generate(plan)
        self.log(f"planned {len(plan.steps)} nodes for intent {plan.intent!r}")
        explanation = Text(
            name="plan explanation",
            text=_explain(plan),
            language=str(self.get_param("language", "zh")),
        )
        return {
            "workflow": Text(name="planned workflow", text=_dump_document(document), language="json"),
            "text": explanation,
        }


def _dump_document(document: Dict[str, Any]) -> str:
    import json

    return json.dumps(document, ensure_ascii=False, indent=2, default=str)


def _explain(plan) -> str:
    lines = [f"识别意图：{plan.intent}", f"规划引擎：{plan.engine}", "执行步骤："]
    for index, step in enumerate(plan.steps, start=1):
        lines.append(f"  {index}. {step.node_type} — {step.reason}")
    if plan.notes:
        lines.append("备注：")
        lines.extend(f"  - {note}" for note in plan.notes)
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Pipeline stages (shared by the node, the CLI and the agent task runtime)      #
# --------------------------------------------------------------------------- #
def plan_only(node: "_AgentBase", question: str, data: Optional[Dict[str, Any]] = None):
    """Stage 1 -- plan.  Returns ``(plan, planner, workflow_document)``."""
    plan, planner = node._plan(question, data or {})
    document = WorkflowGenerator(node._catalog()).generate(plan)
    return plan, planner, document


def execute_plan(
    node: "_AgentBase",
    plan,
    planner: Planner,
    cancel_check: Optional[Any] = None,
) -> Dict[str, Any]:
    """Stage 2 -- execute a previously built plan (with cooperative cancel)."""
    document = WorkflowGenerator(node._catalog()).generate(plan)
    workflow = Workflow.from_dict(document)
    issues = workflow.validate()
    if issues:
        plan.steps = [step for step in plan.steps if step.node_type in node._catalog()]
        document = WorkflowGenerator(node._catalog()).generate(plan)
        workflow = Workflow.from_dict(document)
        issues = workflow.validate()
        if issues:
            raise NodeExecutionError(
                node.node_id,
                node.node_type(),
                "generated workflow is invalid: " + "; ".join(issues),
            )
    engine = WorkflowEngine(max_workers=1, use_cache=False, cancel_check=cancel_check)
    return engine.run(workflow).to_dict()


def finalise(
    node: "_AgentBase",
    question: str,
    plan,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    """Stage 3 -- reason over the run result and build the report ports."""
    language = str(node.get_param("language", "zh") or "zh")
    analysis = node._reason(result)
    report = Reasoner(language).to_report(
        analysis, title=f"AI 科学分析：{question[:60]}"
    )
    report.metadata["question"] = question
    report.metadata["intent"] = plan.intent
    report.metadata["plan"] = plan.to_dict()
    report.metadata["workflow"] = result.get("workflow", "")
    report.metadata["status"] = result.get("status", "")
    report.metadata["duration_ms"] = result.get("duration_ms", 0)
    report.metadata["errors"] = result.get("errors", [])
    report.metadata["records"] = {
        node_id: {
            "status": record.get("status", ""),
            "duration_ms": record.get("duration_ms", 0),
        }
        for node_id, record in (result.get("records", {}) or {}).items()
    }
    report.metadata["provenance_path"] = result.get("provenance_path", "")

    table = node._results_table(result, plan)
    narrative = Text(name="agent conclusion", text=analysis.get("narrative", ""), language=language)
    workflow_json = Text(name="generated workflow", text=_dump_workflow(result), language="json")
    return {
        "report": report,
        "workflow": workflow_json,
        "text": narrative,
        "table": table,
        "_analysis": analysis,
    }


# --------------------------------------------------------------------------- #
# Convenience entry points (shared by scripts/run_agent.py and the REST API)
# --------------------------------------------------------------------------- #
def run_question(
    question: str,
    *,
    language: str = "zh",
    use_llm: bool = True,
    max_nodes: int = 12,
    remember: bool = False,
) -> Dict[str, Any]:
    """Run the agent on ``question`` once and return its raw output ports.

    ``nodes.loader`` is imported lazily so this helper can live next to the node
    without creating an import cycle.
    """
    from nodes.loader import get_registry

    node = get_registry().create("ScientificAgentNode")
    node.params.update(
        {
            "question": question,
            "language": language,
            "use_llm": use_llm,
            "max_nodes": max_nodes,
            "remember": remember,
        }
    )
    return node.process({}, ctx=None)


def plan_question(
    question: str, *, language: str = "zh", max_nodes: int = 12
) -> Dict[str, Any]:
    """Plan only (no execution) and return the generated workflow + explanation."""
    from nodes.loader import get_registry

    node = get_registry().create("AgentPlanNode")
    node.params.update(
        {"question": question, "language": language, "max_nodes": max_nodes}
    )
    return node.process({}, ctx=None)


def _section(section: Any) -> Dict[str, Any]:
    """Normalise a report section (pydantic model or plain mapping)."""
    if isinstance(section, dict):
        return {
            "heading": section.get("heading", section.get("title", "")),
            "body": section.get("body", section.get("content", "")),
        }
    return {
        "heading": getattr(section, "heading", getattr(section, "title", "")),
        "body": getattr(section, "body", getattr(section, "content", "")),
    }


def summarise(outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Condense the agent output ports into a JSON serialisable summary."""
    report = outputs.get("report")
    metadata = dict(getattr(report, "metadata", {}) or {})
    plan = dict(metadata.get("plan", {}) or {})
    table = outputs.get("table")
    records: List[List[Any]] = list(getattr(table, "rows", []) or [])
    return {
        "question": metadata.get("question", ""),
        "intent": metadata.get("intent", ""),
        "engine": plan.get("engine", ""),
        "nodes": [step.get("node_type") for step in plan.get("steps", [])],
        "notes": plan.get("notes", []),
        "status": metadata.get("status", ""),
        "duration_ms": metadata.get("duration_ms", 0),
        "errors": metadata.get("errors", []),
        "conclusion": getattr(outputs.get("text"), "text", ""),
        "findings": [
            {"text": row[0] if row else "", "status": row[2] if len(row) > 2 else ""}
            for row in records
        ],
        "report_title": getattr(report, "title", ""),
        "sections": [_section(section) for section in getattr(report, "sections", []) or []],
    }
