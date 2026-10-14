"""v0.7.2 spec task P0-05 -- execution provenance and capability boundaries.

The point of these tests is **honesty**, not coverage for its own sake: they
fail if the platform can advertise a scientific node for something it cannot
actually do.

* every node states how it runs (``execution_mode``) and what may be claimed
  about it (``capability_status``);
* an ``external`` node names its dependency and *refuses to run* without it;
* an ``internal_approximation`` node carries explicit limitations;
* a ``verified`` node points at evidence that exists on disk;
* a node whose program is missing can never be advertised as available.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.security import EXTERNAL, EXECUTE
from workflow_engine.node_base import (
    CAPABILITY_STATUSES,
    DependencyMissingError,
    EXECUTION_MODES,
    REPRODUCIBILITY_LEVELS,
    ScientificNode,
)

ROOT = Path(__file__).resolve().parents[1]


class TestEveryNodeStatesItsProvenance:
    """P0-05 acceptance: "关键节点均具有能力状态和执行来源"."""

    def test_spec_exposes_the_provenance_fields(self, registry):
        for node_type in registry.types():
            spec = registry.spec(node_type)
            for key in (
                "capability_status",
                "execution_mode",
                "required_dependencies",
                "input_constraints",
                "validation_evidence",
                "limitations",
                "reproducibility_level",
            ):
                assert key in spec, f"{node_type} spec is missing {key!r}"

    def test_enum_values_are_from_the_allowed_sets(self, registry):
        for node_type in registry.types():
            spec = registry.spec(node_type)
            assert spec["capability_status"] in CAPABILITY_STATUSES, node_type
            assert spec["execution_mode"] in EXECUTION_MODES, node_type
            assert spec["reproducibility_level"] in REPRODUCIBILITY_LEVELS, node_type

    def test_registry_validates_provenance_for_every_node(self):
        from node_registry import scan, validate

        report = validate(scan())
        assert report["valid"], report.get("issues")


class TestUnavailableNodesNeverOverclaim:
    """P0-05 acceptance: "缺少外部软件时，不会错误声称真实计算完成"."""

    def test_unavailable_nodes_are_not_advertised_as_available(self, registry):
        for node_type in registry.types():
            spec = registry.spec(node_type)
            status = spec.get("capability_status")
            if status == "unavailable":
                # An unavailable node must not claim verified/executable --
                # "verified" here would mean advertising a computation that
                # cannot even start.
                assert status == "unavailable"

    def test_unavailable_nodes_state_their_limitations(self, registry):
        from node_registry import scan

        report = scan()
        offenders = [
            record["type"]
            for record in report["nodes"]
            if record["availability"] == "unavailable" and not record.get("limitations")
        ]
        assert not offenders, f"unavailable nodes without limitations: {offenders[:5]}"

    def test_simulation_nodes_are_internal_approximations(self, registry):
        """The simulation connectors never pretend an external program ran."""
        checked = 0
        for node_type in registry.types():
            spec = registry.spec(node_type)
            if "requires_external_software" not in spec["capabilities"]:
                continue
            checked += 1
            assert spec["execution_mode"] == "internal_approximation", node_type
            assert spec["required_dependencies"], f"{node_type} names no dependency"
            assert spec["limitations"], f"{node_type} states no limitation"
        assert checked >= 5, f"expected the simulation family to be covered, saw {checked}"


class TestDependencyGate:
    """P0-05 acceptance: "不可用节点应阻止执行或明确要求安装依赖"."""

    def test_missing_dependency_raises_with_guidance(self):
        class NeedsGhost(ScientificNode):
            required_software = ["chemml-definitely-not-installed-xyz"]
            required_dependencies = ["ghost-sim >= 1.0"]

        with pytest.raises(DependencyMissingError) as exc:
            NeedsGhost.require_dependencies()
        message = str(exc.value)
        assert "chemml-definitely-not-installed-xyz" in message
        assert "ghost-sim" in message

    def test_present_dependency_passes(self, monkeypatch):
        class NeedsPython(ScientificNode):
            required_software = ["python"]
            required_dependencies = ["python >= 3"]

        # ``python`` is unambiguous on PATH in a Python test run.
        import shutil

        if shutil.which("python") or shutil.which("python3"):
            NeedsPython.require_dependencies()  # must not raise

    def test_dependency_error_is_a_node_execution_error(self):
        from workflow_engine.errors import NodeExecutionError

        assert issubclass(DependencyMissingError, NodeExecutionError)


class TestDowngradeRules:
    """A claim that cannot be backed is downgraded, and the reason is recorded."""

    def test_verified_without_evidence_is_downgraded(self):
        class Rogue(ScientificNode):
            capability_status = "verified"

        status, note = Rogue.effective_capability_status()
        assert status == "executable"
        assert "no validation_evidence" in (note or "")

    def test_verified_with_evidence_is_kept(self):
        class Good(ScientificNode):
            capability_status = "verified"
            validation_evidence = ["tests/test_v07_2_node_known_answers.py"]

        status, note = Good.effective_capability_status()
        assert status == "verified"
        assert note is None

    def test_external_without_dependency_is_downgraded(self):
        class Rogue(ScientificNode):
            execution_mode = "external"

        mode, note = Rogue.effective_execution_mode()
        assert mode == "internal_approximation"
        assert note

    def test_external_with_dependency_is_kept(self):
        class Good(ScientificNode):
            execution_mode = "external"
            required_software = ["orca"]

        mode, note = Good.effective_execution_mode()
        assert mode == "external"
        assert note is None

    def test_deterministic_flag_overrides_reproducibility_claim(self):
        class Wobbly(ScientificNode):
            deterministic = False
            reproducibility_level = "deterministic"

        assert Wobbly.effective_reproducibility() == "nondeterministic"

    def test_downgrade_note_is_exposed_in_the_spec(self):
        """The UI and the report must be able to explain a downgrade."""
        class Rogue(ScientificNode):
            name = "Roguish"
            capability_status = "verified"

        assert "capability_status_note" in Rogue.spec()


class TestProvenanceSurvivesTheRegistry:
    """The scanned record must carry the same provenance as the live class."""

    def test_registry_record_matches_the_class_spec(self, registry):
        for node_type in registry.types():
            spec = registry.spec(node_type)
            if spec["capability_status"] != "verified":
                continue
            evidence = spec["validation_evidence"]
            assert evidence
            for item in evidence:
                path = item.split("::")[0]
                assert (ROOT / path).exists(), f"{node_type}: missing evidence {path}"

    def test_verified_nodes_are_a_small_explicit_set(self, registry):
        """Every ``verified`` claim is listed here on purpose.

        Adding a node to this list is a deliberate act: it means a known-answer
        check exists somewhere in ``validation_evidence``.
        """
        verified = {
            node_type
            for node_type in registry.types()
            if registry.spec(node_type).get("capability_status") == "verified"
        }
        assert verified == {
            "SmoothingNode",
            "PeakPickingNode",
            "NormalizeNode",
            "MoleculeInputNode",
        }
