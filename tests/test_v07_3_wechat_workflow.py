"""Workflow 10: WeChat Official Account marketing copy.

The workflow is deliberately two LLM nodes rather than one.  A single call that
plans and drafts in one pass tends to produce a body that ignores its own
outline; splitting it makes the plan an explicit upstream input, so the draft can
be checked against it.  These tests pin the *structure* and the offline
behaviour.  They never call a network provider: a test that needs a paid key is
a test that will be skipped or fail in CI, and a skipped test verifies nothing.

The live run (NVIDIA NIM, ``openai/gpt-oss-20b``, 26.5 s, zero errors) is recorded
in ``docs/V07_3_RELEASE_REPORT.md``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from workflow_engine.engine import WorkflowEngine
from workflow_engine.workflow import Workflow

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "10_wechat_marketing_copy.json"


@pytest.fixture(scope="module")
def raw() -> dict:
    return json.loads(WORKFLOW.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def workflow() -> Workflow:
    from nodes.loader import get_registry

    get_registry()
    return Workflow.from_file(WORKFLOW)


# --------------------------------------------------------------------------- #
# structure
# --------------------------------------------------------------------------- #
def test_the_workflow_validates(workflow):
    errors = workflow.validate()
    assert not errors, f"workflow does not validate: {errors}"


def test_the_planner_feeds_the_writer(workflow):
    """The whole design rests on this edge; dropping it silently degrades it.

    Without it the writer still succeeds -- it just writes about nothing in
    particular, which is what happened before the truncation fix.
    """
    edges = {(e.source, e.target, e.target_port) for e in workflow.edges}
    assert ("plan", "write", "context") in edges


def test_the_brief_reaches_the_planner(workflow):
    edges = {(e.source, e.target, e.target_port) for e in workflow.edges}
    assert ("brief", "plan", "prompt") in edges


def test_the_draft_is_exported_as_markdown(workflow):
    exports = [n for n in workflow.nodes if n.type == "ExportNode"]
    assert exports, "the article has to leave the workflow somehow"
    assert exports[0].params.get("format") == "md"


def test_the_llm_nodes_name_a_reasoning_model_with_a_adequate_budget(raw):
    """Free-tier reasoning models return ``content: null`` below the threshold.

    Measured: 400 tokens produced an empty body, 3000 produced the article.  A
    workflow that ships with the node default (1024) looks fine until someone
    runs it and gets a blank document.
    """
    llms = [n for n in raw["nodes"] if n["type"] == "LLMNode"]
    assert llms, "the workflow needs LLM nodes to write anything"
    for node in llms:
        assert node["params"]["max_tokens"] >= 2000, (
            f"{node['id']} budgets {node['params']['max_tokens']} tokens, which "
            "produced an empty body for reasoning models"
        )
        assert node["params"]["timeout_s"] >= 60, (
            f"{node['id']} times out in {node['params']['timeout_s']}s; the "
            "measured cold start on this provider was 14 s and can be far more"
        )


def test_the_workflow_declares_its_own_limits(raw):
    """An honest workflow says what it cannot do."""
    meta = raw.get("metadata", {})
    assert meta.get("limitations_zh"), "a generated article needs a stated review step"
    assert "engine" in meta, "the executing engine must be named"
    assert "0.7.3" == raw.get("version")


# --------------------------------------------------------------------------- #
# behaviour, offline
# --------------------------------------------------------------------------- #
def _run_offline(tmp_path, monkeypatch):
    """Run with no key in the environment: the fallback must still deliver."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    from nodes.loader import get_registry

    registry = get_registry()
    wf = Workflow.from_file(WORKFLOW)
    return WorkflowEngine(registry=registry, workdir=str(tmp_path)).run(wf)


def test_it_completes_without_any_api_key(tmp_path, monkeypatch):
    result = _run_offline(tmp_path, monkeypatch)
    assert result.status == "completed", (
        f"offline run failed: "
        + "; ".join(
            f"{nid}: {rec.get('error')}"
            for nid, rec in result.records.items()
            if isinstance(rec, dict) and rec.get("error")
        )
    )


def test_the_offline_result_says_it_is_offline(tmp_path, monkeypatch):
    """A degraded result must not masquerade as a model-written article."""
    result = _run_offline(tmp_path, monkeypatch)
    text = result.output("plan", "text")
    assert text.data.get("engine") == "offline", (
        "without a key the node must flag engine=offline so the reader knows "
        "the prose is not model-generated"
    )


def test_the_markdown_artefact_is_written(tmp_path, monkeypatch):
    result = _run_offline(tmp_path, monkeypatch)
    assert result.status == "completed"
    written = list(tmp_path.rglob("wechat_marketing_copy.md"))
    assert written, f"no markdown written under {tmp_path}"
    assert written[0].read_text(encoding="utf-8").strip()


def test_exporting_a_report_as_markdown_actually_works(tmp_path, monkeypatch):
    """Regression: ``ExportNode``'s markdown branch used ``ScientificReport``
    without importing it, so it raised ``NameError`` on first use.

    Nothing caught it because every previously shipped workflow exported JSON or
    CSV.  The only thing that found it was this workflow running for real.
    """
    result = _run_offline(tmp_path, monkeypatch)
    record = result.records.get("publish")
    error = record.get("error") if isinstance(record, dict) else None
    assert not error, f"the markdown export branch failed: {error}"
