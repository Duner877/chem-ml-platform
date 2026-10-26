"""Agent Tool Registry: the agent's hands on the node ecosystem.

The agent does not call Python functions directly -- it calls *nodes*, through
the same registry the workflow engine uses.  That is what makes an agent action
auditable and reproducible: every tool call is a node type plus parameters, and
therefore shows up in the generated workflow.

Usage::

    from custom_nodes.agent.tools import tool_registry

    tools = tool_registry()                       # every node as a tool
    tool = tools.get("PeakPickingNode")           # one tool
    result = tools.call("PeakPickingNode", {"spectrum": spectrum})
    print(tools.describe_for_llm())               # prompt friendly catalogue
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflow_engine.errors import NodeExecutionError
from workflow_engine.registry import registry

__all__ = ["AgentTool", "AgentToolRegistry", "tool_registry"]


class AgentTool:
    """A node exposed to the agent as a callable tool."""

    def __init__(self, node_type: str, spec: Optional[Dict[str, Any]] = None) -> None:
        self.node_type = node_type
        self.spec: Dict[str, Any] = dict(spec or {})

    # -- description -------------------------------------------------------- #
    @property
    def name(self) -> str:
        return str(self.spec.get("name", "") or self.node_type)

    @property
    def description(self) -> str:
        return str(self.spec.get("description", "") or "")

    @property
    def category(self) -> str:
        return str(self.spec.get("category", "") or "")

    def inputs(self) -> List[Dict[str, Any]]:
        return list(self.spec.get("inputs", []))

    def outputs(self) -> List[Dict[str, Any]]:
        return list(self.spec.get("outputs", []))

    def parameters(self) -> List[Dict[str, Any]]:
        return list(self.spec.get("parameters", []))

    # -- invocation --------------------------------------------------------- #
    def call(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        node_id: str = "",
    ) -> Dict[str, Any]:
        """Instantiate the node and run it once.

        Raises
        ------
        NodeExecutionError
            When the node is unknown or fails.
        """
        if not registry.has(self.node_type):
            raise NodeExecutionError(
                node_id, self.node_type, f"tool {self.node_type!r} is not registered"
            )
        node = registry.create(self.node_type, node_id=node_id or f"tool_{self.node_type}", params=params or {})
        return node.process(inputs or {})

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "name": self.name,
            "category": self.category,
            "description": self.description,
            "inputs": self.inputs(),
            "outputs": self.outputs(),
            "parameters": self.parameters(),
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AgentTool {self.node_type}>"


class AgentToolRegistry:
    """Every registered node, addressable as an agent tool."""

    def __init__(self, specs: Optional[List[Dict[str, Any]]] = None) -> None:
        self._specs: Dict[str, Dict[str, Any]] = {}
        self.refresh(specs)

    # -- population --------------------------------------------------------- #
    def refresh(self, specs: Optional[List[Dict[str, Any]]] = None) -> None:
        """(Re)load the catalogue from the node registry."""
        from nodes import load_nodes, node_specs

        load_nodes()
        payload = specs if specs is not None else node_specs()
        self._specs = {
            str(spec.get("type", "")): spec for spec in payload if spec.get("type")
        }

    # -- lookup ------------------------------------------------------------- #
    def get(self, node_type: str) -> Optional[AgentTool]:
        """The tool for ``node_type`` (``None`` when unknown)."""
        spec = self._specs.get(node_type)
        if spec is None:
            # fall back on aliases: the node registry knows them
            try:
                canonical = registry.resolve(node_type)
            except Exception:  # noqa: BLE001 - unknown tool
                return None
            spec = self._specs.get(canonical)
            if spec is None:
                return AgentTool(canonical)
        return AgentTool(str(spec.get("type", node_type)), spec)

    def has(self, node_type: str) -> bool:
        return self.get(node_type) is not None

    def types(self) -> List[str]:
        return sorted(self._specs)

    def categories(self) -> Dict[str, List[str]]:
        buckets: Dict[str, List[str]] = {}
        for node_type, spec in self._specs.items():
            buckets.setdefault(str(spec.get("category", "")), []).append(node_type)
        return {name: sorted(items) for name, items in sorted(buckets.items())}

    # -- invocation --------------------------------------------------------- #
    def call(
        self,
        node_type: str,
        inputs: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """``agent.call_node("LCMSParser")`` -- run one node right now."""
        tool = self.get(node_type)
        if tool is None:
            raise NodeExecutionError(
                "", node_type, f"unknown tool {node_type!r}"
            )
        return tool.call(inputs=inputs, params=params)

    #: Alias matching the specification's ``agent.call_node(...)`` wording.
    call_node = call

    # -- description for LLMs ----------------------------------------------- #
    def describe_for_llm(self, limit: int = 60) -> str:
        """Compact, prompt friendly catalogue of the available tools."""
        lines: List[str] = []
        for node_type in self.types()[: max(0, int(limit))]:
            tool = self.get(node_type)
            if tool is None:
                continue
            inputs = ", ".join(
                f"{port.get('name')}:{port.get('data_type')}" for port in tool.inputs()
            )
            outputs = ", ".join(
                f"{port.get('name')}:{port.get('data_type')}" for port in tool.outputs()
            )
            lines.append(
                f"- {node_type} ({tool.category}) inputs[{inputs}] outputs[{outputs}]: "
                f"{tool.description}"
            )
        return "\n".join(lines)

    def describe(self) -> List[Dict[str, Any]]:
        return [self.get(node_type).to_dict() for node_type in self.types()]

    def __len__(self) -> int:
        return len(self._specs)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<AgentToolRegistry {len(self._specs)} tools>"


#: Process wide tool registry.
_tools: Optional[AgentToolRegistry] = None


def tool_registry() -> AgentToolRegistry:
    """The process wide :class:`AgentToolRegistry`."""
    global _tools
    if _tools is None:
        _tools = AgentToolRegistry()
    return _tools
