"""The tool guard must guard *every* entry point, not just the agent (v0.7.3 P0-3).

``agent_runtime/tool_guard.py`` opens by claiming that "every surface (agent
node, agent REST endpoint, workflow run) reaches the same check_tool_call".
Before this release only the agent runtime actually called it: a workflow
launched from the GUI's Run button, from ``POST /api/workflows/*/run``, or from
``scripts/run_demo_workflows.py`` never consulted the policy at all.  A guard
whose own documentation describes a boundary it does not enforce is worse than
one that is absent, because it is relied upon.

These tests pin the three paths separately.  The interesting assertion is
negative in each case: prove that a rule the agent path honours is *also*
honoured by the two paths that used to bypass it, using a node whose class
cannot be reasoned about from its name alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from workflow_engine.engine import WorkflowEngine
from workflow_engine.objects import Table, Text
from workflow_engine.registry import NodeRegistry
from workflow_engine.workflow import Workflow

ROOT = Path(__file__).resolve().parents[1]

#: A node whose *class name* matches the ``*Controlled*`` deny rule, so it can
#: only be classified by consulting the guard -- not by pattern-matching the
#: name in the test.  Its output carries a sentinel, so a successful (bad)
#: bypass is observable on the run result and not merely in a return code.
MARKER = "controlled-executed"


def _build_registry() -> NodeRegistry:
    """A registry holding one node whose class trips the deny rule."""
    from workflow_engine.node_base import ScientificNode
    from workflow_engine.ports import Port

    class ControlledProbeNode(ScientificNode):
        type_name = "ControlledProbeNode"
        category = "security"
        description = "Probe node for guard integration tests"
        capabilities = ("requires_external_software",)
        input_ports = ()
        output_ports = (Port(name="out", data_type="text", description="marker"),)
        parameters = ()

        def execute(self, inputs, ctx):
            self.log("probe executed")
            return {"out": Text(content=MARKER)}

    registry = NodeRegistry()
    registry.register(ControlledProbeNode)
    return registry


def _workflow() -> Dict[str, Any]:
    return {
        "name": "guard-probe",
        "nodes": [{"id": "n1", "type": "ControlledProbeNode", "params": {}}],
        "edges": [],
    }


class TestGuardAppliesToDirectEngineRuns:
    """Path 1: a programmatic run -- the one that used to bypass entirely."""

    def test_a_deny_class_node_is_refused(self, tmp_path):
        engine = WorkflowEngine(
            registry=_build_registry(),
            workdir=tmp_path,
            origin="manual",
        )
        result = engine.run(_workflow())
        assert result.status == "failed"
        assert result.errors, "a refused node must produce an error record"
        assert "tool guard" in result.errors[0]["error"]
        assert "denied" in result.errors[0]["error"]

    def test_the_error_names_the_rule_that_decided(self, tmp_path):
        engine = WorkflowEngine(registry=_build_registry(), workdir=tmp_path)
        result = engine.run(_workflow())
        message = result.errors[0]["error"]
        assert "ControlledProbeNode" in message
        assert "*Controlled*" in message, (
            "the operator must be able to see which rule fired, or they cannot "
            "decide between amending the rules and removing the node"
        )

    def test_approval_does_not_override_a_deny(self, tmp_path):
        """A deny is absolute -- no approval token may unlock it."""
        engine = WorkflowEngine(
            registry=_build_registry(),
            workdir=tmp_path,
            origin="agent",
            approved_node_types=["ControlledProbeNode"],
        )
        result = engine.run(_workflow())
        assert result.status == "failed", (
            "an approved_node_types entry must not turn a deny into an allow"
        )

    def test_the_probe_node_never_actually_runs(self, tmp_path):
        """The observable proof: the sentinel never reaches an output."""
        engine = WorkflowEngine(registry=_build_registry(), workdir=tmp_path)
        result = engine.run(_workflow())
        record = result.records["n1"]
        assert record.status == "failed"
        assert record.outputs == {}, "a denied node must produce no output"


class TestAgentAndManualOriginsDiffer:
    """The guard must be strict where it should be, and not nagging where it
    should not be -- a gate that fires on every report export gets clicked
    through, which is the failure it was built to prevent."""

    def _approval_class_registry(self) -> NodeRegistry:
        from workflow_engine.node_base import ParameterSpec, Port, ScientificNode

        class WriteProbeNode(ScientificNode):
            """Trips the ``*Write*`` rule, i.e. the ``approval`` class.

            The name has to contain "Write" for the same reason
            ``ControlledProbeNode`` contains "Controlled": the test is
            asserting the guard's *decision*, and a node the guard cannot
            recognise proves nothing about it.
            """
            type_name = "WriteProbeNode"
            category = "security"
            description = "Approval-class probe"
            capabilities = ()
            input_ports = ()
            output_ports = (Port(name="out", data_type="text", description="x"),)
            parameters = ()

            def execute(self, inputs, ctx):
                return {"out": Text(content="ran")}

        registry = NodeRegistry()
        registry.register(WriteProbeNode)
        return registry

    def _wf(self, node_type: str) -> Dict[str, Any]:
        return {
            "name": "approval-probe",
            "nodes": [{"id": "n1", "type": node_type, "params": {}}],
            "edges": [],
        }

    def test_the_probe_node_really_is_approval_class(self):
        """Fail loudly here rather than silently testing an ``allow`` node."""
        from agent_runtime.tool_guard import check_tool_call

        decision = check_tool_call("WriteProbeNode")
        assert decision.requires_approval and decision.allowed

    def test_a_manual_run_may_use_an_approval_class_node(self, tmp_path):
        engine = WorkflowEngine(
            registry=self._approval_class_registry(), workdir=tmp_path, origin="manual"
        )
        result = engine.run(self._wf("WriteProbeNode"))
        assert result.status == "completed", (
            "the local user pressing Run is the approval; re-prompting for every "
            "report export would train users to click through the dialog"
        )

    def test_an_agent_run_may_not_use_it_without_approval(self, tmp_path):
        engine = WorkflowEngine(
            registry=self._approval_class_registry(), workdir=tmp_path, origin="agent"
        )
        result = engine.run(self._wf("WriteProbeNode"))
        assert result.status == "failed"
        assert "tool guard" in result.errors[0]["error"]

    def test_an_agent_run_succeeds_once_the_node_is_approved(self, tmp_path):
        engine = WorkflowEngine(
            registry=self._approval_class_registry(),
            workdir=tmp_path,
            origin="agent",
            approved_node_types=["WriteProbeNode"],
        )
        result = engine.run(self._wf("WriteProbeNode"))
        assert result.status == "completed", (
            "approval must actually unlock the node, or the gate is a dead end"
        )

    def test_an_unknown_origin_is_treated_as_manual(self, tmp_path):
        """Missing information must not break the platform.

        A guard that refuses everything because it could not tell where the
        run came from would be a denial-of-service, not a security control.
        """
        engine = WorkflowEngine(registry=self._approval_class_registry(), workdir=tmp_path)
        assert engine.origin is None
        result = engine.run(self._wf("WriteProbeNode"))
        assert result.status == "completed"


class TestRestPathSharesTheSameDecision:
    """Path 2: the REST execute endpoint must not be a way around the guard."""

    @pytest.fixture(scope="class")
    def client(self):
        from fastapi.testclient import TestClient

        from backend.app import create_app

        return TestClient(create_app())

    def test_the_execute_endpoint_builds_a_guarded_engine(self):
        """Structural check: the endpoint's engine carries an origin.

        A behaviour test here would need a denied node registered in the
        global registry, which would mean shipping a deny-class node in the
        product.  Asserting the wiring is the honest version of the same
        claim, and it fails loudly if someone drops the argument.
        """
        source = (ROOT / "backend" / "routers" / "workflows.py").read_text(encoding="utf-8")
        assert "origin=origin" in source
        assert "approved_node_types=approved_node_types" in source

    def test_the_default_origin_is_manual(self):
        from backend.routers.workflows import _engine

        engine = _engine()
        assert engine.origin == "manual"
        assert engine.approved_node_types == set()


class TestGuardDegradesHonestly:
    """A missing guard must not pretend to have run."""

    def test_a_broken_guard_is_reported_not_swallowed(self, tmp_path, monkeypatch):
        """If the guard raises, the node is refused -- fail closed."""
        import agent_runtime.tool_guard as tg

        def boom(*args, **kwargs):
            raise RuntimeError("guard policy file is corrupt")

        monkeypatch.setattr(tg, "check_tool_call", boom)
        engine = WorkflowEngine(registry=_build_registry(), workdir=tmp_path)
        result = engine.run(_workflow())
        assert result.status == "failed"
        assert "could not classify" in result.errors[0]["error"]

    def test_an_absent_guard_module_logs_that_it_was_skipped(self, tmp_path, monkeypatch):
        """No guard at all is reported in the event stream.

        Silently running unguarded would make the run's provenance imply a
        check that never happened; refusing everything would make a partial
        install unusable.  Announcing the degradation is the honest third
        option.
        """
        import builtins

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name.startswith("agent_runtime.tool_guard"):
                raise ImportError("agent_runtime is not installed")
            return real_import(name, *args, **kwargs)

        events: list = []
        engine = WorkflowEngine(
            registry=_build_registry(),
            workdir=tmp_path,
            event_listeners=[events.append],
        )
        monkeypatch.setattr(builtins, "__import__", blocked)
        result = engine.run(_workflow())

        # The node runs (the platform stays usable) but says so.
        assert result.status == "completed", result.errors
        assert any(
            "tool guard unavailable" in str(getattr(e, "message", e)) for e in events
        ), "the run must announce that it executed without a policy check"
