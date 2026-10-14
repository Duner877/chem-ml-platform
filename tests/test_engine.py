"""Workflow engine tests: DAG execution, validation, caching, events."""

from __future__ import annotations

import pytest

from workflow_engine.engine import WorkflowEngine
from workflow_engine.errors import WorkflowValidationError
from workflow_engine.events import (
    NODE_COMPLETED,
    NODE_FAILED,
    RUN_COMPLETED,
    RUN_STARTED,
)
from workflow_engine.objects import Text
from workflow_engine.workflow import Workflow


def _graph(edges, nodes=None):
    node_list = nodes or [
        {"id": "a", "type": "TextInputNode", "params": {"text": "hello", "language": "en"}},
        {"id": "b", "type": "TextInputNode", "params": {"text": "world", "language": "en"}},
        {"id": "c", "type": "ExportNode", "params": {"filename": "out", "format": "txt"}},
    ]
    return {"name": "test graph", "nodes": node_list, "edges": edges}


def test_single_node_run(registry):
    engine = WorkflowEngine(registry=registry, use_cache=False)
    result = engine.run(
        {
            "name": "single",
            "nodes": [
                {"id": "t", "type": "TextInputNode", "params": {"text": "hi", "language": "en"}}
            ],
            "edges": [],
        }
    )
    assert result.ok
    assert result.records["t"].status == "completed"
    assert isinstance(result.output("t", "text"), Text)


def test_linear_chain(registry):
    """a -> b -> c executes in topological order and passes data along."""
    engine = WorkflowEngine(registry=registry, use_cache=False)
    result = engine.run(
        {
            "name": "chain",
            "nodes": [
                {"id": "a", "type": "TextInputNode", "params": {"text": "seed"}},
                {"id": "b", "type": "ReportBuilderNode", "params": {"title": "chain"}},
                {"id": "c", "type": "ReportExportNode", "params": {"format": "markdown", "filename": "chain"}},
            ],
            "edges": [
                {"source": "a", "source_port": "text", "target": "b", "target_port": "text"},
                {"source": "b", "source_port": "report", "target": "c", "target_port": "report"},
            ],
        }
    )
    assert result.ok, result.errors
    assert result.records["a"].status == "completed"
    assert result.records["b"].status == "completed"
    assert result.records["c"].status == "completed"


def test_diamond_graph(registry):
    """A diamond DAG runs every node exactly once."""
    engine = WorkflowEngine(registry=registry, max_workers=4, use_cache=False)
    result = engine.run(
        {
            "name": "diamond",
            "nodes": [
                {"id": "root", "type": "TextInputNode", "params": {"text": "r"}},
                {"id": "left", "type": "ReportBuilderNode", "params": {"title": "l"}},
                {"id": "right", "type": "ReportBuilderNode", "params": {"title": "r"}},
                {"id": "join", "type": "ReportExportNode", "params": {"format": "markdown", "filename": "diamond"}},
            ],
            "edges": [
                {"source": "root", "source_port": "text", "target": "left", "target_port": "text"},
                {"source": "root", "source_port": "text", "target": "right", "target_port": "text"},
                {"source": "left", "source_port": "report", "target": "join", "target_port": "report"},
                {"source": "right", "source_port": "text", "target": "join", "target_port": "text"},
            ],
        }
    )
    assert result.ok, result.errors
    assert len(result.records) == 4


def test_failure_skips_downstream(registry):
    """A failing node skips its descendants but the run still finishes."""
    engine = WorkflowEngine(registry=registry, use_cache=False)
    result = engine.run(
        {
            "name": "failing",
            "nodes": [
                {"id": "bad", "type": "SpectrumFileNode", "params": {"path": "nope.xy"}},
                {"id": "after", "type": "ExportNode", "params": {"format": "txt"}},
            ],
            "edges": [{"source": "bad", "target": "after"}],
        }
    )
    assert not result.ok
    assert result.records["bad"].status == "failed"
    assert result.records["after"].status == "skipped"
    assert result.errors


def test_cycle_is_rejected(registry):
    engine = WorkflowEngine(registry=registry)
    with pytest.raises(WorkflowValidationError):
        engine.run(
            {
                "name": "cycle",
                "nodes": [
                    {"id": "a", "type": "TextInputNode", "params": {"text": "a"}},
                    {"id": "b", "type": "TextInputNode", "params": {"text": "b"}},
                ],
                "edges": [
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "a"},
                ],
            }
        )


def test_unknown_node_type_is_rejected(registry):
    engine = WorkflowEngine(registry=registry)
    issues = engine.validate(
        {"name": "bad", "nodes": [{"id": "x", "type": "NoSuchNode"}], "edges": []}
    )
    assert any("unknown node type" in issue for issue in issues)


def test_events_are_emitted(registry):
    """The event bus reports run and node lifecycle transitions."""
    seen: list[str] = []
    engine = WorkflowEngine(registry=registry, use_cache=False)
    engine._listeners.append(
        lambda event: seen.append(getattr(event, "type", str(event)))
    )
    engine.run(
        {
            "name": "events",
            "nodes": [
                {"id": "t", "type": "TextInputNode", "params": {"text": "hi"}}
            ],
            "edges": [],
        }
    )
    assert RUN_STARTED in seen
    assert NODE_COMPLETED in seen
    assert RUN_COMPLETED in seen
    assert NODE_FAILED not in seen


def test_cache_avoids_recomputation(registry):
    """With caching enabled an identical node is served from the cache."""
    engine = WorkflowEngine(registry=registry, use_cache=True)
    workflow = {
        "name": "cached",
        "nodes": [
            {"id": "t", "type": "TextInputNode", "params": {"text": "memo"}}
        ],
        "edges": [],
    }
    first = engine.run(workflow)
    second = engine.run(workflow)
    assert first.ok and second.ok
    # The very first execution computes, the identical re-run is a cache hit.
    assert first.records["t"].status == "completed"
    assert second.records["t"].cached


def test_workflow_serialisation_roundtrip():
    workflow = Workflow.from_dict(_graph([{"source": "a", "target": "b"}]))
    payload = workflow.to_dict()
    clone = Workflow.from_dict(payload)
    assert clone.name == workflow.name
    assert len(clone.nodes) == len(workflow.nodes)
    assert len(clone.edges) == len(workflow.edges)
