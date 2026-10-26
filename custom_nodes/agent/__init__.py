"""科学智能体节点分组。

自主规划、工具调用与推理。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.agent import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.agent.agent import (
    ScientificAgentNode,
    AgentPlanNode,
)
from custom_nodes.agent.agent import (
    execute_plan,
    finalise,
    plan_only,
    plan_question,
    run_question,
    summarise,
)
from custom_nodes.agent.planner import (
    INTENT_KEYWORDS,
    RECIPES,
    Plan,
    PlanStep,
    Planner,
    detect_intent,
)
from custom_nodes.agent.reasoning import (
    Finding,
    Reasoner,
    reason,
)
from custom_nodes.agent.tools import (
    AgentTool,
    AgentToolRegistry,
    tool_registry,
)
from custom_nodes.agent.workflow_generator import (
    WorkflowGenerator,
    generate_workflow,
)

try:  # pragma: no cover - 仅在脱离 monorepo 时触发
    from chemml_version import VERSION as __version__
except ImportError:  # pragma: no cover
    __version__ = "0.7.4"

__all__ = [
    "ScientificAgentNode",
    "AgentPlanNode",
    "execute_plan",
    "finalise",
    "plan_only",
    "plan_question",
    "run_question",
    "summarise",
    "INTENT_KEYWORDS",
    "RECIPES",
    "Plan",
    "PlanStep",
    "Planner",
    "detect_intent",
    "Finding",
    "Reasoner",
    "reason",
    "AgentTool",
    "AgentToolRegistry",
    "tool_registry",
    "WorkflowGenerator",
    "generate_workflow",
    "__version__",
]
