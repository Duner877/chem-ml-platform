"""Provenance collector -- bridges the workflow engine to the schema.

The collector offers two integration levels:

* :func:`build_node_record` turns a completed :class:`NodeExecutionRecord`
  plus the node instance into a :class:`ProvenanceRecord` (used by tests and
  by the engine integration hook);
* :class:`ProvenanceCollector` is an engine event listener that accumulates
  records for a run and writes ``provenance.json`` when the run finishes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import (
    EnvironmentInfo,
    ProvenanceRecord,
    collect_environment,
    utc_now_iso,
)

__all__ = ["ProvenanceCollector", "build_node_record"]


def build_node_record(
    record: Any,
    node_instance: Any = None,
    environment: Optional[EnvironmentInfo] = None,
    run_id: str = "",
) -> ProvenanceRecord:
    """Create a :class:`ProvenanceRecord` from an engine execution record.

    ``record`` is a :class:`workflow_engine.engine.NodeExecutionRecord`;
    ``node_instance`` (optional) contributes node version, params, provider /
    model and fallback information when the node exposes them.
    """
    prov = ProvenanceRecord(
        run_id=run_id or "",
        node_id=getattr(record, "node_id", ""),
        node_type=getattr(record, "node_type", ""),
        started_at=getattr(record, "started_at", ""),
        finished_at=getattr(record, "finished_at", ""),
        duration_ms=float(getattr(record, "duration_ms", 0.0) or 0.0),
        cache_hit=bool(getattr(record, "cached", False)),
        status=getattr(record, "status", ""),
    )
    if getattr(record, "error", ""):
        prov.errors.append(str(record.error))
    prov.warnings.extend(
        line for line in getattr(record, "logs", []) if str(line).lower().startswith("[warn")
    )

    if node_instance is not None:
        prov.node_version = str(getattr(node_instance, "version", "") or "")
        prov.params = dict(getattr(node_instance, "params", {}) or {})
        prov.provider = str(getattr(node_instance, "last_provider", "") or "")
        prov.model = str(getattr(node_instance, "last_model", "") or "")
        prov.fallback_used = bool(getattr(node_instance, "fallback_used", False))
        prov.fallback_reason = str(getattr(node_instance, "fallback_reason", "") or "")
        prov.device = str(getattr(node_instance, "last_device", "") or "")
        prov.random_seed = getattr(node_instance, "random_seed", None)
        prov.deterministic = bool(getattr(node_instance, "deterministic", True))
        external = getattr(node_instance, "external_software", None)
        if isinstance(external, dict):
            prov.external_software = {str(k): str(v) for k, v in external.items()}

    env = environment or getattr(build_node_record, "_env_cache", None)
    if env is None:
        env = collect_environment()
        build_node_record._env_cache = env  # type: ignore[attr-defined]
    prov.environment = env.to_dict()
    return prov


class ProvenanceCollector:
    """Event-bus listener that records provenance for a whole run."""

    def __init__(self, run_id: str, environment: Optional[EnvironmentInfo] = None):
        self.run_id = run_id
        self.environment = environment or collect_environment()
        self.records: Dict[str, ProvenanceRecord] = {}
        self.started_at = utc_now_iso()
        self.finished_at = ""
        self.run_status = "running"

    # -- engine event hook --------------------------------------------------- #
    def __call__(self, event: Any) -> None:
        etype = getattr(event, "type", "")
        payload = getattr(event, "payload", {}) or {}
        node_id = str(getattr(event, "node_id", "") or "")
        if not node_id:
            if etype in {"run_completed", "run_failed"}:
                self.finished_at = utc_now_iso()
                self.run_status = "completed" if etype == "run_completed" else "failed"
            return
        record = self.records.get(node_id)
        if record is None:
            record = ProvenanceRecord(
                run_id=self.run_id,
                node_id=node_id,
                node_type=str(getattr(event, "node_type", "") or ""),
                environment=self.environment.to_dict(),
            )
            self.records[node_id] = record
        if etype == "node_started":
            record.started_at = utc_now_iso()
            params = payload.get("params")
            if isinstance(params, dict):
                record.params = dict(params)
        elif etype in {"node_completed", "node_cached"}:
            record.finished_at = utc_now_iso()
            record.status = "completed"
            record.cache_hit = etype == "node_cached"
        elif etype == "node_failed":
            record.finished_at = utc_now_iso()
            record.status = "failed"
            message = str(getattr(event, "message", "") or "")
            if message:
                record.errors.append(message)
        elif etype == "node_skipped":
            record.status = "skipped"

    # -- persistence ----------------------------------------------------------- #
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.records_default_schema(),
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.run_status,
            "environment": self.environment.to_dict(),
            "nodes": {k: v.to_dict() for k, v in self.records.items()},
        }

    def records_default_schema(self) -> str:
        from .schema import PROVENANCE_SCHEMA_VERSION

        return PROVENANCE_SCHEMA_VERSION

    def write(self, run_dir: str | Path) -> Path:
        """Write ``provenance.json`` into ``run_dir`` (atomically replaced)."""
        target = Path(run_dir) / "provenance.json"
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        target.write_text(payload, encoding="utf-8")
        tmp.unlink(missing_ok=True)
        return target
