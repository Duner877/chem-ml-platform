"""Declared execution mode is not the same thing as what ran (v0.7.3 P0-4).

``node_registry/registry.json`` reported 99/99 nodes as
``internal_approximation`` -- including the LLM nodes that declare
``requires_network`` and the ORCA/Gaussian wrappers that declare
``requires_external_software``.  A single static field cannot be both true:
those nodes genuinely run several ways.  An LLM node reaches the network when
a key is present and falls back to the built-in offline engine when it is not,
and both runs are the same node type.  Publishing only the declaration made
99/99 look like an approximation, which is simultaneously wrong for the network
nodes and useless for the ones that really do approximate.

The split this release makes:

* ``supported_execution_modes`` -- what the node may do;
* ``default_execution_mode``   -- what it does when nothing overrides it;
* ``execution_mode``           -- the declaration (kept, for compatibility);
* per run: ``actual_execution_mode`` / ``engine_name`` /
  ``engine_version`` / ``fallback_reason`` in provenance.

Only the run-level fields can honestly answer "what computed this number",
which is why they live in provenance and not in the registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "node_registry" / "registry.json"


@pytest.fixture(scope="module")
def registry() -> dict:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    nodes = data.get("nodes", data if isinstance(data, list) else [])
    return {record["type"]: record for record in nodes}


class TestTheRegistryDoesNotOverclaim:
    def test_every_node_separates_declaration_from_capability(self, registry):
        for name, record in registry.items():
            assert "supported_execution_modes" in record, (
                f"{name} still publishes only one execution-mode field"
            )
            assert record["supported_execution_modes"], (
                f"{name} declares no supported mode at all"
            )
            assert "default_execution_mode" in record, name
            assert record.get("execution_mode_source") == "declaration", name

    def test_the_supported_set_contains_the_declaration(self, registry):
        for name, record in registry.items():
            declared = record["execution_mode"]
            assert declared in record["supported_execution_modes"], (
                f"{name} declares {declared!r} but does not list it as supported"
            )

    def test_a_node_needing_the_network_can_reach_it(self, registry):
        """The claim the audit called out by name.

        If every node's supported set is exactly ``[internal_approximation]``,
        the new fields add nothing: the registry still cannot express "this
        node will use the network when a key is configured".
        """
        network_nodes = [
            name for name, r in registry.items()
            if "requires_network" in (r.get("capabilities") or [])
        ]
        assert network_nodes, "fixture assumption: the registry has network nodes"
        internal_only = [
            name for name in network_nodes
            if registry[name]["supported_execution_modes"] == ["internal_approximation"]
        ]
        assert not internal_only, (
            "nodes that require the network still claim only the internal "
            f"approximation: {internal_only[:5]}"
        )

    def test_external_software_nodes_advertise_the_external_mode(self, registry):
        external_nodes = [
            name for name, r in registry.items()
            if r.get("required_software") or "requires_external_software" in (r.get("capabilities") or [])
        ]
        assert external_nodes, "fixture assumption: the registry has external nodes"
        missing = [
            name for name in external_nodes
            if "external" not in registry[name]["supported_execution_modes"]
        ]
        assert not missing, (
            f"external-software nodes do not advertise 'external': {missing[:5]}"
        )

    def test_the_note_says_the_registry_is_not_a_run_record(self, registry):
        """A reader must not mistake the catalogue for a result."""
        sample = next(iter(registry.values()))
        assert "provenance" in (sample.get("execution_mode_note") or "").lower()


class TestProvenanceRecordsWhatActuallyRan:
    def test_the_record_carries_the_split_fields(self):
        from provenance.schema import ProvenanceRecord

        record = ProvenanceRecord(run_id="r", node_id="n", node_type="ORCANode")
        payload = record.to_dict()
        for field in (
            "execution_mode",
            "supported_execution_modes",
            "default_execution_mode",
            "engine_name",
            "engine_version",
        ):
            assert field in payload, f"provenance dropped {field}"

    def test_instance_facts_fill_the_modes_and_the_engine(self):
        from provenance.collector import apply_instance_facts
        from provenance.schema import ProvenanceRecord

        class FakeNode:
            execution_mode = "internal_approximation"
            supported_execution_modes = ["external", "internal_approximation"]
            default_execution_mode = "external"
            capability_status = "experimental"
            version = "0.7.3"
            deterministic = True
            # What a *run* would set on the live instance.
            last_engine = "internal:eht"
            engine_version = "1.0.0"

        record = ProvenanceRecord(run_id="r", node_id="n", node_type="FakeNode")
        apply_instance_facts(record, FakeNode())

        assert record.supported_execution_modes == ["external", "internal_approximation"]
        assert record.default_execution_mode == "external"
        assert record.execution_mode == "internal_approximation"
        assert record.engine_name == "internal:eht", (
            "the mode says which kind of computation ran; the engine name says "
            "which one -- a report without it cannot be checked"
        )
        assert record.engine_version == "1.0.0"

    def test_a_fallback_names_its_reason(self):
        """The most important single fact a degraded run can carry."""
        from provenance.collector import build_node_record

        class FallbackNode:
            execution_mode = "internal_approximation"
            capability_status = "experimental"
            version = "0.7.3"
            deterministic = True
            fallback_used = True
            fallback_reason = "ORCA is not installed; used the built-in EHT engine"
            last_engine = "internal:eht"

        class FakeRecord:
            node_id = "n"
            node_type = "ORCANode"
            started_at = ""
            finished_at = ""
            duration_ms = 0.0
            cached = False
            status = "completed"
            error = ""
            logs = []

        prov = build_node_record(FakeRecord(), FallbackNode())
        assert prov.fallback_used is True
        assert "ORCA is not installed" in prov.fallback_reason
        assert prov.engine_name == "internal:eht"

    def test_a_node_without_engine_metadata_still_records_a_mode(self):
        """Third-party / older nodes must not produce an empty record."""
        from provenance.collector import apply_instance_facts
        from provenance.schema import ProvenanceRecord

        class Bare:
            execution_mode = "synthetic_demo"

        record = ProvenanceRecord(run_id="r", node_id="n", node_type="Bare")
        apply_instance_facts(record, Bare())
        assert record.execution_mode == "synthetic_demo"
        assert record.supported_execution_modes == ["synthetic_demo"]
        assert record.engine_name == "", (
            "an unknown engine must stay empty rather than be guessed at"
        )


class TestTheTwoNeverDisagree:
    """The registry and provenance must use the same vocabulary."""

    def test_registry_modes_are_a_subset_of_the_schema_vocabulary(self, registry):
        from node_registry.capabilities import EXECUTION_MODES

        for name, record in registry.items():
            for mode in record["supported_execution_modes"]:
                assert mode in EXECUTION_MODES, (
                    f"{name} advertises {mode!r}, which is not a known mode"
                )

    def test_the_simulation_result_contract_matches(self):
        """``external:orca`` / ``internal:eht`` is what engine_name will hold."""
        from simulation_runtime.base import SimulationResult

        fields = SimulationResult.__dataclass_fields__
        assert "engine" in fields
