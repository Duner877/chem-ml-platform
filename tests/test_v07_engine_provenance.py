"""v0.7 tests -- engine-level provenance integration (spec sections 11, 22-I)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_engine.engine import WorkflowEngine


SIMPLE_WF = {
    "name": "prov-test",
    "nodes": [
        {"id": "t_in", "type": "TextInputNode", "label": "text",
         "position": {"x": 0, "y": 0}, "params": {"text": "hello provenance"}},
        {"id": "t_out", "type": "ExportNode", "label": "export",
         "position": {"x": 120, "y": 0}, "params": {"filename": "prov_out.txt"}},
    ],
    "edges": [["t_in", "t_out"]],
}


@pytest.fixture()
def engine(tmp_path: Path):
    from nodes.loader import get_registry

    return WorkflowEngine(registry=get_registry(), workdir=tmp_path / "output")


class TestEngineProvenance:
    def test_provenance_json_written(self, engine, tmp_path):
        result = engine.run(SIMPLE_WF)
        assert result.ok
        assert result.provenance_path, "engine must record provenance_path"
        path = Path(result.provenance_path)
        assert path.is_file()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["run_id"] == result.run_id
        assert data["status"] == "completed"
        nodes = data["nodes"]
        assert set(nodes) >= {"t_in", "t_out"}
        assert nodes["t_in"]["status"] == "completed"
        assert nodes["t_in"]["started_at"]
        # environment snapshot is recorded
        assert data["environment"]["python_version"]

    def test_provenance_records_params(self, engine):
        result = engine.run(SIMPLE_WF)
        data = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))
        assert data["nodes"]["t_in"]["params"] == {"text": "hello provenance"}

    def test_provenance_on_failure(self, engine):
        wf = {
            "name": "prov-fail",
            "nodes": [
                {"id": "bad", "type": "NoSuchNode", "label": "bad",
                 "position": {"x": 0, "y": 0}, "params": {}},
            ],
            "edges": [],
        }
        with pytest.raises(Exception):
            engine.run(wf)  # invalid node type -> validation error

    def test_failed_node_recorded_in_provenance(self, engine, tmp_path):
        wf = {
            "name": "prov-node-fail",
            "nodes": [
                {"id": "t_in", "type": "TextInputNode", "label": "text",
                 "position": {"x": 0, "y": 0}, "params": {"text": "x"}},
                {"id": "boom", "type": "FailingProbeNode", "label": "boom",
                 "position": {"x": 120, "y": 0}, "params": {}},
            ],
            "edges": [],
        }
        # register a failing probe node locally
        from workflow_engine.errors import NodeExecutionError
        from workflow_engine.node_base import ScientificNode
        from workflow_engine.registry import register_node

        @register_node
        class FailingProbeNode(ScientificNode):  # noqa: N801 - registry style
            name = "Failing Probe"
            category = "Test"
            version = "0.7.0"

            input_ports = []
            output_ports = []

            def execute(self, inputs, ctx=None):
                raise RuntimeError("intentional probe failure")

        result = engine.run(wf)
        assert not result.ok
        data = json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))
        assert data["nodes"]["boom"]["status"] == "failed"
        assert any("intentional probe failure" in e for e in data["nodes"]["boom"]["errors"])
