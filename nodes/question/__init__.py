"""Top level scientific question nodes.

The two nodes of this package are the *intent* layer of the platform: instead
of describing how to process data ("baseline correct, then pick peaks") the
user states the scientific question -- "what is this compound?" or "which
material should we synthesise?" -- and the node orchestrates the evidence.
"""

from __future__ import annotations

from nodes.question.identification import (
    CANDIDATE_WEIGHTS,
    UnknownCompoundIdentificationNode,
)
from nodes.question.discovery import (
    ATOMIC_DATA,
    PROPERTY_TARGETS,
    MaterialDiscoveryNode,
)

__all__ = [
    "UnknownCompoundIdentificationNode",
    "CANDIDATE_WEIGHTS",
    "MaterialDiscoveryNode",
    "PROPERTY_TARGETS",
    "ATOMIC_DATA",
]
