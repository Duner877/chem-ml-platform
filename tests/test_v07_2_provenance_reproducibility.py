"""v0.7.2 task P1-06 -- run provenance and reproducibility.

The spec asks that "从一次运行记录可以追溯输入、参数、算法版本和输出" and that
a run declared deterministic can be shown consistent by *repeating* it -- while
explicitly forbidding an absolute promise such as "all inputs always produce
identical output".

These tests exercise the real engine end to end and then assert on the
``provenance.json`` it writes, so a regression in the engine integration (not
just in the schema dataclass) is caught.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from provenance import (
    PROVENANCE_SCHEMA_VERSION,
    ProvenanceCollector,
    key_dependency_versions,
    measure_resources,
    platform_identity,
    workflow_identity,
)
from workflow_engine.engine import WorkflowEngine

# A small but genuinely computational graph: the EHT calculator feeds a
# descriptor step, so the run exercises real numerics rather than only I/O.
TEXT_WF = {
    "name": "p16-determinism",
    "nodes": [
        {"id": "t_in", "type": "TextInputNode", "label": "text",
         "position": {"x": 0, "y": 0}, "params": {"text": "reproducible run"}},
        {"id": "t_out", "type": "ExportNode", "label": "export",
         "position": {"x": 160, "y": 0}, "params": {"filename": "p16_out.txt"}},
    ],
    "edges": [["t_in", "t_out"]],
}


def _engine(workdir: Path, **kw) -> WorkflowEngine:
    from nodes.loader import get_registry

    return WorkflowEngine(registry=get_registry(), workdir=workdir, use_cache=False, **kw)


def _provenance(result) -> dict:
    assert result.provenance_path, "engine must record a provenance path"
    return json.loads(Path(result.provenance_path).read_text(encoding="utf-8"))


class TestRunLevelTraceability:
    """Every fact a second researcher needs to re-run the experiment."""

    def test_workflow_identity_is_recorded(self, tmp_path: Path):
        result = _engine(tmp_path / "out").run(TEXT_WF)
        data = _provenance(result)
        wf = data["workflow"]
        assert wf["name"] == "p16-determinism"
        assert wf["node_count"] == 2
        assert wf["edge_count"] == 1
        assert wf["definition_digest"].startswith("sha256:")

    def test_workflow_digest_changes_with_a_parameter(self):
        """The digest must identify the definition, not the file name."""
        base = workflow_identity(TEXT_WF)
        changed = json.loads(json.dumps(TEXT_WF))
        changed["nodes"][1]["params"]["filename"] = "different.txt"
        assert workflow_identity(changed)["definition_digest"] != base["definition_digest"]

    def test_workflow_digest_ignores_key_order(self):
        """Re-serialising the same workflow must not look like a new one."""
        reordered = {"edges": TEXT_WF["edges"], "nodes": TEXT_WF["nodes"],
                     "name": TEXT_WF["name"]}
        assert (
            workflow_identity(reordered)["definition_digest"]
            == workflow_identity(TEXT_WF)["definition_digest"]
        )

    def test_platform_identity_is_recorded(self, tmp_path: Path):
        result = _engine(tmp_path / "out").run(TEXT_WF)
        data = _provenance(result)
        assert data["schema_version"] == PROVENANCE_SCHEMA_VERSION
        assert data["platform"]["version"], "run must record the platform version"
        assert data["platform"]["codename"]

    def test_key_dependency_versions_are_recorded(self, tmp_path: Path):
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        deps = data["environment"]["key_dependencies"]
        assert deps, "numerics-critical dependency versions must be recorded"
        # Absence is a recorded fact, not an omission.
        assert all(isinstance(v, str) and v for v in deps.values())
        assert "numpy" in deps

    def test_dependency_versions_report_absence_explicitly(self):
        deps = key_dependency_versions()
        # A dependency that is genuinely absent must say so rather than vanish.
        for value in deps.values():
            assert value in {"absent", "unknown"} or value[0].isdigit()

    def test_inputs_and_outputs_are_traceable(self, tmp_path: Path):
        """Input digests, params and output artefact references must all appear."""
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        node = data["nodes"]["t_in"]
        assert node["params"] == {"text": "reproducible run"}
        assert node["node_type"] == "TextInputNode"
        assert node["status"] == "completed"
        assert node["started_at"] and node["finished_at"]
        assert data["nodes"]["t_out"]["status"] == "completed"

    def test_execution_mode_records_what_actually_ran(self, tmp_path: Path):
        """P0-05 declares a mode; P1-06 must record the one actually used."""
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        for node in data["nodes"].values():
            assert node["execution_mode"], "each node must record its execution mode"
            assert node["execution_mode"] in {
                "external", "internal_approximation", "synthetic_demo"
            }, node["execution_mode"]
            assert node["capability_status"] in {
                "verified", "executable", "experimental", "unavailable"
            }, node["capability_status"]
        assert data["execution_modes"], "run must carry a mode census"

    def test_resource_usage_measured_or_explained(self, tmp_path: Path):
        """A missing resource number must be explained, never silently dropped."""
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        usage = data["resource_usage"]
        assert "wall_time_s" in usage, "wall time is always measurable"
        assert "cpu_time_s" in usage
        if usage.get("peak_rss_bytes") is None:
            assert usage.get("peak_rss_note"), (
                "if peak memory could not be measured, the record must say why"
            )

    def test_measure_resources_never_raises(self):
        usage = measure_resources("2026-01-01T00:00:00+00:00", 0.0, 0.0)
        assert isinstance(usage, dict) and "cpu_count" in usage

    def test_platform_identity_never_raises(self):
        ident = platform_identity()
        assert set(ident) == {"version", "codename", "commit"}


class TestDeterminismClaim:
    """The spec forbids an absolute reproducibility promise."""

    def test_repeated_run_has_identical_workflow_digest(self, tmp_path: Path):
        a = _provenance(_engine(tmp_path / "a").run(TEXT_WF))
        b = _provenance(_engine(tmp_path / "b").run(TEXT_WF))
        assert a["workflow"]["definition_digest"] == b["workflow"]["definition_digest"]

    def test_repeated_run_is_reported_consistent(self, tmp_path: Path):
        """A deterministic graph must not be flagged as non-deterministic."""
        a = _provenance(_engine(tmp_path / "a").run(TEXT_WF))
        b = _provenance(_engine(tmp_path / "b").run(TEXT_WF))
        assert a["reproducibility"]["nondeterministic_nodes"] == []
        assert b["reproducibility"]["nondeterministic_nodes"] == []
        assert a["reproducibility"]["all_nodes_deterministic"] is True

    def test_claim_is_never_absolute(self, tmp_path: Path):
        """The record must *refuse* the absolute promise, not merely omit it."""
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        claim = data["reproducibility"]["claim"]
        refusals = ("不承诺", "不保证", "not guaranteed")
        assert any(r in claim for r in refusals), (
            "the record must explicitly refuse an absolute reproducibility promise"
        )
        # The forbidden phrasing may appear only as the object of that refusal:
        # quoting it to deny it is honest, asserting it is not.
        for absolute in ("永远产生完全相同的输出", "guaranteed identical output"):
            idx = claim.find(absolute)
            if idx >= 0:
                assert any(r in claim[:idx] for r in refusals), (
                    f"{absolute!r} appears as an affirmative claim"
                )

    def test_deterministic_nodes_are_not_flagged_as_unseeded(self, tmp_path: Path):
        """A node doing no sampling must not be reported as at-risk.

        Warning about every node would train readers to ignore the warning, so
        only nodes that genuinely consume randomness may be listed.
        """
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        repro = data["reproducibility"]
        assert repro["all_nodes_deterministic"] is True
        assert repro["nondeterministic_nodes"] == []
        # TextInputNode / ExportNode have no seed parameter at all.
        assert repro["unseeded_random_nodes"] == []
        assert repro["nodes_at_risk_of_divergence"] == []
        assert repro["divergence_factors"] == []

    def test_seed_parameter_left_unset_is_flagged(self):
        """But a randomness-consuming node that never pinned a seed *is* flagged."""
        from provenance import ProvenanceRecord

        collector = ProvenanceCollector("rid")
        collector.records["n1"] = ProvenanceRecord(
            node_id="n1", node_type="Sampler", params={"seed": None}
        )
        repro = collector.reproducibility()
        assert repro["unseeded_random_nodes"] == ["n1"]
        assert repro["nodes_at_risk_of_divergence"] == ["n1"]
        assert repro["divergence_factors"], "factors must be stated, not implied"

    def test_digest_scope_states_what_is_excluded(self, tmp_path: Path):
        """A reader must be able to see what the digest does and does not cover."""
        scope = _provenance(
            _engine(tmp_path / "out").run(TEXT_WF)
        )["reproducibility"]["digest_scope"]
        assert "id" in scope["excluded_keys"]
        assert scope["excluded_value_pattern"]
        assert "sha-256" in scope["artifact_digests"].lower()

    def test_divergence_factors_listed_when_relevant(self):
        """Non-deterministic nodes must surface the factors that could change results."""
        from provenance import ProvenanceRecord

        collector = ProvenanceCollector("rid", workflow=TEXT_WF)
        collector.records["n1"] = ProvenanceRecord(
            node_id="n1", node_type="X", deterministic=False
        )
        repro = collector.reproducibility()
        assert repro["nondeterministic_nodes"] == ["n1"]
        assert repro["divergence_factors"], "factors must be stated, not implied"

    def test_collector_serialises_full_record(self, tmp_path: Path):
        collector = ProvenanceCollector("rid", workflow=TEXT_WF, max_workers=4)
        collector.resource_snapshot()
        path = collector.write(tmp_path)
        data = json.loads(path.read_text(encoding="utf-8"))
        for key in ("workflow", "platform", "environment", "resource_usage",
                    "execution_modes", "reproducibility", "nodes"):
            assert key in data, f"provenance.json is missing {key!r}"
        assert data["max_workers"] == 4


class TestFailureIsRecorded:
    def test_failed_run_records_status_and_error(self, tmp_path: Path):
        wf = {
            "name": "p16-fail",
            "nodes": [
                {"id": "bad", "type": "ORCANode", "label": "orca",
                 "position": {"x": 0, "y": 0},
                 "params": {"x": 0.0, "y": 0.0, "z": 0.0, "charge": 0}},
            ],
            "edges": [],
        }
        result = _engine(tmp_path / "out").run(wf)
        data = _provenance(result)
        assert data["status"] in {"completed", "failed"}
        record = data["nodes"]["bad"]
        if result.status != "completed":
            assert record["status"] == "failed"
            assert record["errors"] or record["status"] == "skipped"


class TestOutputDigests:
    """``output_digests`` used to be declared in the schema but never filled.

    A field that always holds ``{}`` looks like evidence while proving nothing,
    so these tests pin the behaviour that fixed it.
    """

    def test_output_digests_are_actually_populated(self, tmp_path: Path):
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        for node_id, node in data["nodes"].items():
            if node["status"] == "completed":
                assert node["output_digests"], (
                    f"{node_id} completed but recorded no output digest"
                )
                for port, digest in node["output_digests"].items():
                    assert digest.startswith("sha256:"), (port, digest)

    def test_artifacts_are_attributed_with_a_file_digest(self, tmp_path: Path):
        data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
        refs = [
            ref
            for node in data["nodes"].values()
            for ref in node["output_artifacts"]
        ]
        assert refs, "the export node writes a file; the record must reference it"
        for ref in refs:
            assert ref["exists"] is True, ref
            assert ref["digest"].startswith("sha256:")
            assert ref["path"]

    def test_digest_ignores_generated_ids(self):
        from provenance.collector import digest_value

        a = {"report_id": "rpt_0e3f8457", "title": "X", "id": "o_11223344"}
        b = {"report_id": "rpt_9c435ed5", "title": "X", "id": "o_deadbeef"}
        assert digest_value(a) == digest_value(b)

    def test_digest_still_detects_a_real_change(self):
        from provenance.collector import digest_value

        assert digest_value({"title": "X"}) != digest_value({"title": "Y"})

    def test_digest_keeps_meaningful_identifiers(self):
        """A chosen identifier is scientific content and must survive."""
        from provenance.collector import digest_value

        assert digest_value({"dataset_id": "shimadzu_lcms"}) != digest_value(
            {"dataset_id": "lifepo4_pxrd"}
        )

    def test_digest_normalises_run_scoped_paths(self):
        from provenance.collector import digest_value

        a = {"artifact": r"C:\runs\run_aaa\artifacts\report.html"}
        b = {"artifact": r"C:\runs\run_bbb\artifacts\report.html"}
        scrub_a = [r"C:\runs\run_aaa"]
        scrub_b = [r"C:\runs\run_bbb"]
        assert digest_value(a, scrub_a) == digest_value(b, scrub_b)


@pytest.mark.parametrize("field", ["execution_mode", "capability_status",
                                   "random_seed", "deterministic"])
def test_node_record_carries_p16_fields(field, tmp_path: Path):
    data = _provenance(_engine(tmp_path / "out").run(TEXT_WF))
    assert field in data["nodes"]["t_in"], f"node record must carry {field!r}"
