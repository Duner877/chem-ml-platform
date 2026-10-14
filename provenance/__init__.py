"""Scientific provenance system (v0.7 -- spec section 11).

Every node execution produces a :class:`ProvenanceRecord` capturing *what
exactly* produced a result: inputs and their digests, node version, parameter
snapshot, provider/model, environment, timings, seeds, cache and fallback
status, warnings and output artefact references.  Records are serialised to
``provenance.json`` inside the run directory so any reported conclusion can be
audited later.
"""

from .schema import (
    PROVENANCE_SCHEMA_VERSION,
    EnvironmentInfo,
    ProvenanceRecord,
    collect_environment,
    content_digest,
    key_dependency_versions,
    platform_identity,
)
from .collector import (
    ProvenanceCollector,
    build_node_record,
    measure_resources,
    workflow_identity,
)

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "EnvironmentInfo",
    "ProvenanceRecord",
    "collect_environment",
    "content_digest",
    "key_dependency_versions",
    "platform_identity",
    "ProvenanceCollector",
    "build_node_record",
    "measure_resources",
    "workflow_identity",
]
