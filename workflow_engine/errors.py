"""Exception hierarchy of the Chem ML workflow engine."""

from __future__ import annotations

from typing import Any, Iterable


class ChemMLError(Exception):
    """Base class for every error raised by the platform."""


class WorkflowValidationError(ChemMLError):
    """Raised when a workflow graph is structurally invalid."""


class NodeNotFoundError(ChemMLError):
    """Raised when a node type is not present in the registry."""

    def __init__(self, node_type: str, available: Iterable[str] | None = None):
        self.node_type = node_type
        self.available = list(available or [])
        hint = ""
        if self.available:
            close = [a for a in self.available if a.lower() == node_type.lower()]
            hint = f" Did you mean {close[0]!r}?" if close else ""
        super().__init__(f"Unknown node type {node_type!r}.{hint}")


class NodeInputError(ChemMLError):
    """Raised when the data arriving on a node input is not usable."""


class NodeExecutionError(ChemMLError):
    """Raised when a node raises while executing."""

    def __init__(self, node_id: str, node_type: str, message: str):
        self.node_id = node_id
        self.node_type = node_type
        super().__init__(f"[{node_id}:{node_type}] {message}")


class PortError(ChemMLError):
    """Raised for invalid port connections."""


class ObjectParseError(ChemMLError):
    """Raised when a scientific object payload cannot be reconstructed."""


class ExternalToolError(ChemMLError):
    """Raised when a wrapped third-party program fails or is unavailable."""


def format_validation_issues(issues: Iterable[Any]) -> str:
    """Render a list of validation issues as a human readable bullet list."""
    issues = list(issues)
    if not issues:
        return "no issues"
    return "\n".join(f"  - {issue}" for issue in issues)
