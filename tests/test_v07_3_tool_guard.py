"""Regression tests for the agent tool guard (v0.7.3).

Adapted from the tool-guard idea in Tencent's `Octop
<https://github.com/TencentCloud/Octop>`_.  The properties locked here are the
ones whose failure is silent:

1. **A refusal must stop the run.**  Recording "denied" next to an execution
   that went ahead is worse than having no guard, so the scheduler has to fail
   the task rather than annotate it.
2. **First match wins, not most-specific match.**  A user prepending a rule to
   ``config/tool_guard.json`` expects it to override the shipped defaults; a
   specificity ordering would quietly ignore it.
3. **No match means deny.**  A user-supplied policy file that happens to lack a
   catch-all must fail closed, not open.
4. **A malformed policy file falls back to the shipped rules** -- not to an
   empty rule set, which would allow everything.
"""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

import pytest

from agent_runtime.tool_guard import (
    DEFAULT_RULES,
    ToolGuard,
    ToolRule,
    check_tool_call,
)


# --------------------------------------------------------------------------- #
# Rule mechanics
# --------------------------------------------------------------------------- #
def test_unknown_verdict_is_rejected_at_construction():
    with pytest.raises(ValueError):
        ToolRule("*", "maybe", "")


def test_rules_match_both_class_name_and_type_id():
    """A rule author should not have to know which spelling a caller passes."""
    guard = ToolGuard([ToolRule("quantum.orca", "deny", "no")])
    assert guard.check("quantum.orca").verdict == "deny"
    assert ToolGuard([ToolRule("ORCANode", "deny", "no")]).check("ORCANode").verdict == "deny"


def test_extra_names_are_considered():
    guard = ToolGuard([ToolRule("export-results", "deny", "no")])
    assert guard.check("SomeNode", extra_names=["export-results"]).verdict == "deny"


def test_first_matching_rule_wins():
    """Documented, load-bearing ordering: a user rule at the top overrides."""
    guard = ToolGuard(
        [
            ToolRule("SMILESNode", "deny", "user rule"),
            ToolRule("*", "allow", "default"),
        ]
    )
    decision = guard.check("SMILESNode")
    assert decision.verdict == "deny"
    assert decision.matched_rule == "SMILESNode"
    assert "user rule" in decision.reason


def test_no_match_denies_rather_than_allows():
    guard = ToolGuard([ToolRule("OnlyThis", "allow", "")])
    decision = guard.check("SomethingElse")
    assert decision.verdict == "deny"
    assert decision.allowed is False


def test_approval_is_satisfied_by_an_explicit_flag():
    guard = ToolGuard([ToolRule("Export*", "approval", "writes files")])
    assert guard.check("ExportNode").verdict == "approval"
    assert guard.check("ExportNode").requires_approval is True
    allowed = guard.check("ExportNode", approved=True)
    assert allowed.verdict == "allow"
    assert allowed.allowed is True


def test_decision_carries_a_reason_and_a_rule_name():
    """A bare boolean leaves the caller guessing; the answer has to travel."""
    decision = check_tool_call("ExportNode")
    assert decision.reason
    assert decision.matched_rule
    payload = decision.to_dict()
    assert payload["verdict"] == decision.verdict
    assert payload["requires_approval"] is decision.requires_approval


# --------------------------------------------------------------------------- #
# Shipped defaults
# --------------------------------------------------------------------------- #
def test_defaults_end_in_a_catch_all():
    assert DEFAULT_RULES[-1].pattern == "*"
    assert DEFAULT_RULES[-1].verdict == "allow"


def test_read_only_compute_is_allowed():
    """Nodes that touch neither disk, the network nor external software.

    ``ORCANode`` is deliberately *not* in this list even though it computes a
    spectrum: it launches a third-party binary, and the module's own promise is
    that anything shelling out needs an explicit decision.  Calling it
    "read-only compute" was the gap that let nine external-program nodes and
    fifteen network nodes through ungraded.
    """
    for node_type in ("SMILESNode", "MoleculeNode", "BETNode", "AFMNode"):
        assert check_tool_call(node_type).verdict == "allow", node_type


def test_external_program_and_network_nodes_need_approval():
    """Graded by capability, so a renamed or newly added node inherits the rule."""
    for node_type in ("ORCANode", "VASPNode", "GROMACSNode", "LAMMPSNode"):
        assert check_tool_call(node_type).verdict == "approval", node_type
        assert (
            check_tool_call(node_type).matched_rule == "*requires_external_software*"
        ), node_type
    for node_type in ("PubChemNode", "PDBNode", "LLMNode", "MaterialsProjectNode"):
        assert check_tool_call(node_type).verdict == "approval", node_type
        assert check_tool_call(node_type).matched_rule == "*requires_network*", node_type


def test_an_unknown_node_type_still_falls_through_to_the_catch_all():
    """Capability lookup must not raise for a name the registry has never seen."""
    decision = check_tool_call("TotallyMadeUpNode")
    assert decision.verdict == "allow"


def test_destructive_and_outward_facing_nodes_are_refused():
    for node_type in ("ControlledExecutionNode", "DeleteRunNode", "StorageUploadNode"):
        assert check_tool_call(node_type).verdict == "deny", node_type


def test_writing_nodes_need_approval():
    for node_type in ("ExportNode", "ReportExportNode", "SeismicSubmissionNode"):
        assert check_tool_call(node_type).verdict == "approval", node_type


def test_guard_patterns_are_checked_against_the_real_node_names():
    """A rule written from intuition can silently match nothing.

    ``*Submit*`` looks like it covers "submission" -- it does not:
    ``Submission`` is s-u-b-m-i-s-s-i-o-n.  The rule therefore matched nothing
    and let deliverable-overwriting nodes run unguarded.

    A rule that guards a category with no node *today* (``*Controlled*``,
    ``*Delete*``, ``*Upload*``) is legitimate, but it has to say so via
    ``forward_looking``; a pattern that merely looks right is dead policy.
    """
    from nodes.loader import get_registry

    registry = get_registry()
    registry.discover_package("nodes")
    specs = registry.specs()
    types = [spec["type"] for spec in specs]

    for rule in DEFAULT_RULES:
        if rule.pattern == "*":
            continue
        by_name = [t for t in types if fnmatch.fnmatch(t, rule.pattern)]
        # Capability rules are matched against ``extra_names``, so "does this
        # rule have real members" has to be asked of the catalogue, not of the
        # class names -- that is precisely what makes them survive a rename.
        by_capability = [
            spec["type"]
            for spec in specs
            if any(fnmatch.fnmatch(str(c), rule.pattern) for c in (spec.get("capabilities") or []))
        ]
        if by_name or by_capability:
            continue
        assert rule.forward_looking, (
            f"rule {rule.pattern!r} matches neither a node name nor any "
            f"declared capability across the {len(types)} registered nodes and "
            f"is not declared forward_looking -- that is dead policy"
        )

    # The classification has to be stable, not merely non-empty.
    assert check_tool_call("SeismicSubmissionNode").verdict == "approval"
    assert check_tool_call("ExportNode").verdict == "approval"
    assert check_tool_call("BETNode").verdict == "allow"


def test_forward_looking_flag_survives_a_file_round_trip(tmp_path: Path):
    path = tmp_path / "tool_guard.json"
    ToolGuard([ToolRule("Future*", "deny", "r", forward_looking=True)]).to_file(path)
    assert ToolGuard.from_file(path).rules[0].forward_looking is True


def test_the_refusal_reasons_are_bilingual():
    """A user sees these strings; a half-translated reason is a bug report."""
    for rule in DEFAULT_RULES:
        if rule.reason:
            assert "/" in rule.reason, f"{rule.pattern}: {rule.reason}"


# --------------------------------------------------------------------------- #
# Persistence
# --------------------------------------------------------------------------- #
def test_rules_round_trip_through_a_file(tmp_path: Path):
    path = tmp_path / "tool_guard.json"
    ToolGuard([ToolRule("X*", "deny", "理由 / reason")]).to_file(path)
    reloaded = ToolGuard.from_file(path)
    assert reloaded.rules[0].pattern == "X*"
    assert reloaded.rules[0].verdict == "deny"


def test_a_malformed_file_falls_back_to_the_shipped_rules(tmp_path: Path):
    """Not to an empty rule set, which would allow everything."""
    path = tmp_path / "tool_guard.json"
    path.write_text("{ this is not json", encoding="utf-8")
    assert len(ToolGuard.from_file(path).rules) == len(DEFAULT_RULES)


def test_a_rule_missing_its_pattern_is_rejected_not_ignored(tmp_path: Path):
    path = tmp_path / "tool_guard.json"
    path.write_text(json.dumps({"rules": [{"verdict": "deny"}]}), encoding="utf-8")
    assert len(ToolGuard.from_file(path).rules) == len(DEFAULT_RULES)


def test_a_missing_file_falls_back_to_the_shipped_rules(tmp_path: Path):
    assert len(ToolGuard.from_file(tmp_path / "absent.json").rules) == len(DEFAULT_RULES)


def test_a_file_with_no_rules_array_falls_back(tmp_path: Path):
    path = tmp_path / "tool_guard.json"
    path.write_text(json.dumps({"rules": "nope"}), encoding="utf-8")
    assert len(ToolGuard.from_file(path).rules) == len(DEFAULT_RULES)


# --------------------------------------------------------------------------- #
# The scheduler actually stops
# --------------------------------------------------------------------------- #
def test_task_snapshot_exposes_the_guard_fields():
    """Without these the GUI cannot show why a plan was refused."""
    from agent_runtime.tasks import AgentTask

    snapshot = AgentTask(task_id="t-1", question="q").snapshot()
    assert snapshot["blocked_nodes"] == []
    assert snapshot["gated_nodes"] == []


def test_guard_records_land_in_the_task_record():
    from agent_runtime.tasks import AgentTask

    task = AgentTask(task_id="t-1", question="q")
    task.blocked_nodes = [{"node": "DeleteRunNode", "verdict": "deny"}]
    task.records["guard"] = {"blocked": task.blocked_nodes}
    assert task.snapshot()["records"]["guard"]["blocked"][0]["node"] == "DeleteRunNode"


def test_refusal_is_not_silently_allowed():
    """The end-to-end property: a denied node never reaches execution.

    Exercised through the guard directly rather than by running a real task,
    because the scheduler's own state transitions are already covered by the
    agent state-machine tests; what is new here is that the deny verdict is
    *terminal*.
    """
    decision = check_tool_call("ControlledExecutionNode")
    assert decision.allowed is False
    assert decision.verdict == "deny"
    # An approval flag must not be able to unlock a hard deny.
    forced = ToolGuard([ToolRule("ControlledExecutionNode", "deny", "no")]).check(
        "ControlledExecutionNode", approved=True
    )
    assert forced.verdict == "deny"