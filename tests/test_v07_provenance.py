"""v0.7 Phase A tests -- provenance schema and collector (spec section 11)."""

from __future__ import annotations

import json
from pathlib import Path

from provenance import (
    PROVENANCE_SCHEMA_VERSION,
    ProvenanceCollector,
    ProvenanceRecord,
    build_node_record,
    collect_environment,
)
from workflow_engine.engine import NodeExecutionRecord, STATUS_COMPLETED, STATUS_FAILED
from workflow_engine.events import Event


class TestSchema:
    def test_record_defaults_and_summary(self):
        rec = ProvenanceRecord(node_id="n1", node_type="FooNode", status="completed")
        d = rec.to_dict()
        # v0.7.2 (task P1-06) extended the schema: workflow definition digest,
        # platform identity, key dependency versions, per-node execution mode,
        # output digests and run-level resource usage.  The version therefore
        # moved off 0.7.0.
        #
        # Both assertions are deliberate.  The constant check keeps the test
        # about behaviour; the literal check is the only thing that *pins* the
        # value -- `scripts/version.py` intentionally does not track the
        # provenance schema version, because a schema bump is not a product
        # release.  A future bump must update this line consciously.
        assert d["schema_version"] == PROVENANCE_SCHEMA_VERSION
        assert d["schema_version"] == "0.7.2"
        assert "FooNode#n1" in rec.summary()

    def test_environment_snapshot(self):
        env = collect_environment()
        d = env.to_dict()
        assert d["python_version"]
        assert isinstance(d["cuda_available"], bool)


def _record(node_id="n1", node_type="FooNode", status=STATUS_COMPLETED, **kw):
    return NodeExecutionRecord(node_id=node_id, node_type=node_type, status=status, **kw)


class TestBuildNodeRecord:
    def test_basic_fields(self):
        rec = _record(duration_ms=12.5, cached=True)
        node = type(
            "FooNode",
            (),
            {"version": "1.2.0", "params": {"a": 1}, "last_provider": "openai",
             "last_model": "gpt-x", "fallback_used": True, "fallback_reason": "no key"},
        )()
        prov = build_node_record(rec, node, run_id="run_x")
        assert prov.node_version == "1.2.0"
        assert prov.params == {"a": 1}
        assert prov.provider == "openai"
        assert prov.model == "gpt-x"
        assert prov.fallback_used and prov.fallback_reason == "no key"
        assert prov.cache_hit
        assert prov.run_id == "run_x"
        assert prov.environment["python_version"]

    def test_error_captured(self):
        rec = _record(status=STATUS_FAILED, error="missing input")
        prov = build_node_record(rec)
        assert prov.status == "failed"
        assert any("missing input" in e for e in prov.errors)


class TestCollector:
    def test_event_lifecycle(self):
        collector = ProvenanceCollector("run_1")
        for etype, node in [
            ("node_started", "a"),
            ("node_completed", "a"),
            ("node_started", "b"),
            ("node_failed", "b"),
        ]:
            collector(
                Event(etype, run_id="run_1", node_id=node, node_type=f"T_{node}",
                      message="boom" if etype == "node_failed" else "",
                      payload={"params": {"x": 1}} if etype == "node_started" else {})
            )
        assert collector.records["a"].status == "completed"
        assert collector.records["b"].status == "failed"
        assert collector.records["b"].errors == ["boom"]
        assert collector.records["a"].params == {"x": 1}

    def test_write_json(self, tmp_path: Path):
        collector = ProvenanceCollector("run_1")
        collector(Event("node_started", node_id="a", node_type="T"))
        collector(Event("node_completed", node_id="a", node_type="T"))
        collector(Event("run_completed", run_id="run_1"))
        out = collector.write(tmp_path)
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["run_id"] == "run_1"
        assert data["status"] == "completed"
        assert data["nodes"]["a"]["status"] == "completed"
        assert data["environment"]["os_name"]
