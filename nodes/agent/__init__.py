"""Agent nodes: the AI scientist as a first class workflow citizen.

Layout
------
=========================  ===================================================
``nodes.agent.agent``           :class:`ScientificAgentNode` + ``AgentPlanNode``
``nodes.agent.planner``         question -> :class:`Plan` (rules or LLM)
``nodes.agent.tools``           :class:`AgentToolRegistry` (``call_node``)
``nodes.agent.workflow_generator`` plan -> executable workflow JSON
``nodes.agent.reasoning``       run result -> findings with confidence
=========================  ===================================================

Importing this package registers the agent nodes, so
``nodes.load_nodes()`` picks them up like any other node.
"""

from __future__ import annotations

from nodes.agent.agent import (
    AgentPlanNode,
    ScientificAgentNode,
    execute_plan,
    finalise,
    plan_only,
    plan_question,
    run_question,
    summarise,
)
from nodes.agent.planner import INTENT_KEYWORDS, RECIPES, Plan, PlanStep, Planner, detect_intent
from nodes.agent.reasoning import Finding, Reasoner, reason
from nodes.agent.tools import AgentTool, AgentToolRegistry, tool_registry
from nodes.agent.workflow_generator import WorkflowGenerator, generate_workflow

#: Package version follows the platform version (v0.7.2 fix, ISSUE-18).
try:  # pragma: no cover - the fallback only triggers outside the monorepo
    from chemml_version import VERSION as __version__
except ImportError:  # pragma: no cover
    __version__ = "0.7.2"

__all__ = [
    "ScientificAgentNode",
    "AgentPlanNode",
    "run_question",
    "plan_question",
    "summarise",
    "plan_only",
    "execute_plan",
    "finalise",
    "Planner",
    "Plan",
    "PlanStep",
    "detect_intent",
    "INTENT_KEYWORDS",
    "RECIPES",
    "AgentToolRegistry",
    "AgentTool",
    "tool_registry",
    "WorkflowGenerator",
    "generate_workflow",
    "Reasoner",
    "Finding",
    "reason",
    "__version__",
]
