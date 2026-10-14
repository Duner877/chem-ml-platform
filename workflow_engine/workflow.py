"""Workflow graph model, serialisation and validation.

The on-disk format follows section 11 of the specification::

    {
      "name": "Battery Discovery",
      "nodes": [{"id": 1, "type": "XRDNode"}],
      "edges": [[1, 2]]
    }

The extended form (used by the GUI) adds ``params``/``position`` on nodes and
``source_port``/``target_port`` on edges.  Both are accepted by
:meth:`Workflow.from_dict`; ``to_dict`` always emits the extended form which is
a strict superset of the specification.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import networkx as nx

from .errors import WorkflowValidationError
from .ports import port_by_name, types_compatible
from .utils import json_safe, new_id

__all__ = ["WorkflowNode", "WorkflowEdge", "Workflow"]


@dataclass
class WorkflowNode:
    """A node instance inside a workflow."""

    id: str
    type: str
    params: Dict[str, Any] = field(default_factory=dict)
    position: Dict[str, float] = field(default_factory=dict)
    label: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowNode":
        return cls(
            id=str(data.get("id") or new_id("n_")),
            type=str(data.get("type") or ""),
            params=dict(data.get("params") or data.get("parameters") or {}),
            position=dict(data.get("position") or {}),
            label=str(data.get("label") or ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"id": self.id, "type": self.type}
        if self.params:
            payload["params"] = json_safe(self.params)
        if self.position:
            payload["position"] = json_safe(self.position)
        if self.label:
            payload["label"] = self.label
        return payload


@dataclass
class WorkflowEdge:
    """A directed connection between two nodes."""

    source: str
    target: str
    source_port: Optional[str] = None
    target_port: Optional[str] = None
    id: str = ""

    @classmethod
    def from_dict(cls, data: Any) -> "WorkflowEdge":
        if isinstance(data, (list, tuple)):
            if len(data) < 2:
                raise WorkflowValidationError(f"Invalid edge {data!r}")
            return cls(source=str(data[0]), target=str(data[1]))
        if isinstance(data, dict):
            source = data.get("source", data.get("from", data.get("source_node")))
            target = data.get("target", data.get("to", data.get("target_node")))
            if source is None or target is None:
                raise WorkflowValidationError(f"Invalid edge {data!r}")
            return cls(
                source=str(source),
                target=str(target),
                source_port=data.get("source_port")
                or data.get("sourceHandle")
                or data.get("source_handle"),
                target_port=data.get("target_port")
                or data.get("targetHandle")
                or data.get("target_handle"),
                id=str(data.get("id") or ""),
            )
        raise WorkflowValidationError(f"Invalid edge {data!r}")

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"source": self.source, "target": self.target}
        if self.source_port:
            payload["source_port"] = self.source_port
        if self.target_port:
            payload["target_port"] = self.target_port
        if self.id:
            payload["id"] = self.id
        return payload


@dataclass
class Workflow:
    """A directed acyclic graph of scientific nodes."""

    name: str = "Untitled Workflow"
    description: str = ""
    version: str = "1.0"
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # -- construction ------------------------------------------------------- #
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        data = dict(data or {})
        nodes = [WorkflowNode.from_dict(n) for n in data.get("nodes") or []]
        edges = [WorkflowEdge.from_dict(e) for e in data.get("edges") or []]
        return cls(
            name=str(data.get("name") or "Untitled Workflow"),
            description=str(data.get("description") or ""),
            version=str(data.get("version") or "1.0"),
            nodes=nodes,
            edges=edges,
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_file(cls, path: str | Path) -> "Workflow":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        workflow = cls.from_dict(data)
        workflow.metadata.setdefault("source_path", str(path))
        return workflow

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "metadata": json_safe(self.metadata),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def clone(self) -> "Workflow":
        return Workflow.from_dict(self.to_dict())

    # -- graph helpers ------------------------------------------------------ #
    def node_ids(self) -> List[str]:
        return [n.id for n in self.nodes]

    def get_node(self, node_id: str) -> Optional[WorkflowNode]:
        for node in self.nodes:
            if node.id == str(node_id):
                return node
        return None

    def incoming(self, node_id: str) -> List[WorkflowEdge]:
        return [e for e in self.edges if e.target == str(node_id)]

    def outgoing(self, node_id: str) -> List[WorkflowEdge]:
        return [e for e in self.edges if e.source == str(node_id)]

    def roots(self) -> List[WorkflowNode]:
        targets = {e.target for e in self.edges}
        return [n for n in self.nodes if n.id not in targets]

    def to_networkx(self) -> nx.DiGraph:
        graph = nx.DiGraph()
        for node in self.nodes:
            graph.add_node(node.id, type=node.type, label=node.label or node.type)
        for edge in self.edges:
            graph.add_edge(edge.source, edge.target, edge=edge)
        return graph

    # -- validation --------------------------------------------------------- #
    def validate(self, registry: Any = None) -> List[str]:
        """Return a list of problems.  An empty list means the graph is valid."""
        issues: List[str] = []

        if not self.nodes:
            issues.append("workflow contains no nodes")

        seen: Dict[str, int] = {}
        for node in self.nodes:
            if node.id in seen:
                issues.append(f"duplicate node id {node.id!r}")
            seen[node.id] = seen.get(node.id, 0) + 1
            if not node.type:
                issues.append(f"node {node.id!r} has no type")

        if registry is not None:
            for node in self.nodes:
                if node.type and not registry.has(node.type):
                    issues.append(f"node {node.id!r}: unknown node type {node.type!r}")

        ids = set(self.node_ids())
        for edge in self.edges:
            if edge.source not in ids:
                issues.append(f"edge references unknown source {edge.source!r}")
            if edge.target not in ids:
                issues.append(f"edge references unknown target {edge.target!r}")
            if edge.source == edge.target:
                issues.append(f"node {edge.source!r} is connected to itself")

        graph = self.to_networkx()
        if not nx.is_directed_acyclic_graph(graph):
            for cycle in nx.simple_cycles(graph):
                issues.append("cycle detected: " + " -> ".join(map(str, cycle)))

        # Port level checks (only possible when the registry is available).
        if registry is not None:
            for edge in self.edges:
                if edge.source not in ids or edge.target not in ids:
                    continue
                try:
                    src_cls = registry.get(self.get_node(edge.source).type)
                    dst_cls = registry.get(self.get_node(edge.target).type)
                except Exception:  # pragma: no cover - already reported above
                    continue
                # ``port_by_name`` returns the first port when the handle is
                # omitted (``None``); an *empty* port list simply means the
                # node declares no such side, which is reported separately.
                src_port = port_by_name(src_cls.output_ports, edge.source_port)
                dst_port = port_by_name(dst_cls.input_ports, edge.target_port)
                if src_port is None and src_cls.output_ports:
                    issues.append(
                        f"{edge.source} -> {edge.target}: unknown output port "
                        f"{edge.source_port!r}"
                    )
                if dst_port is None and dst_cls.input_ports:
                    issues.append(
                        f"{edge.source} -> {edge.target}: unknown input port "
                        f"{edge.target_port!r}"
                    )
                elif dst_port is None and not dst_cls.input_ports:
                    # A node without input ports cannot receive anything.
                    issues.append(
                        f"{edge.source} -> {edge.target}: {edge.target!r} "
                        f"({dst_cls.__name__}) declares no input ports"
                    )
                if src_port and dst_port and not types_compatible(
                    src_port.data_type, dst_port.data_type
                ):
                    issues.append(
                        f"{edge.source} -> {edge.target}: cannot connect "
                        f"{src_port.data_type} to {dst_port.data_type}"
                    )

            for node in self.nodes:
                try:
                    cls = registry.get(node.type)
                except Exception:  # pragma: no cover
                    continue
                connected = set()
                for edge in self.incoming(node.id):
                    port = port_by_name(cls.input_ports, edge.target_port)
                    # An unknown handle falls back to the raw edge key; an
                    # omitted handle (``None``) defaults to the first port.
                    connected.add(port.name if port else (edge.target_port or ""))
                for port in cls.input_ports:
                    if not port.optional and port.name not in connected:
                        issues.append(
                            f"node {node.id!r} ({node.type}): input "
                            f"{port.name!r} is not connected"
                        )
        return issues

    def assert_valid(self, registry: Any = None) -> None:
        """Raise :class:`WorkflowValidationError` when the graph is invalid."""
        issues = self.validate(registry)
        if issues:
            raise WorkflowValidationError(
                f"Workflow {self.name!r} is invalid:\n"
                + "\n".join(f"  - {i}" for i in issues)
            )
