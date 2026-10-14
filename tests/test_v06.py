"""v0.6 Scientific Foundation Model Edition -- unit + API tests.

Covers the four new runtimes (foundation models, AI configuration, data
catalog, simulation jobs) and the agent surface.  Every test that touches a
persistent document (``config/ai.json``, ``output/catalog/catalog.json``) is
redirected to a temporary directory so the developer's own state is untouched.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEMO_SPECTRUM = ROOT / "datasets" / "demo" / "caffeine_ms.xy"


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ai_config(tmp_path, monkeypatch):
    """Redirect the AI configuration to a temp file and clear the cache."""
    path = tmp_path / "ai.json"
    monkeypatch.setenv("CHEMML_AI_CONFIG", str(path))
    monkeypatch.delenv("CHEMML_AI_MODE", raising=False)
    import ai_runtime.config as config

    config._CACHE = None
    yield path
    config._CACHE = None


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    """A data catalog backed by a temp document."""
    monkeypatch.setenv("CHEMML_CATALOG", str(tmp_path / "catalog.json"))
    from data_layer.catalog import DataCatalog

    return DataCatalog()


# --------------------------------------------------------------------------- #
# foundation runtime
# --------------------------------------------------------------------------- #
def test_foundation_models_registered():
    import foundation

    keys = {row["key"] for row in foundation.catalog()}
    assert {"chemberta", "grover", "graphormer", "uni-mol", "morgan", "physchem"} <= keys
    assert {"spectrum-bin", "spectrum-summary"} <= keys
    assert all(row["dimension"] for row in foundation.catalog())


def test_foundation_embed_shape_and_determinism():
    import foundation

    first = foundation.embed(["CCO", "c1ccccc1"])
    assert len(first) == 2
    assert len(first[0]) == 384
    # unit length
    assert sum(value * value for value in first[0]) == pytest.approx(1.0, abs=1e-6)
    # deterministic
    assert first == foundation.embed(["CCO", "c1ccccc1"])


def test_foundation_similarity_orders_chemistry():
    import foundation

    close = foundation.similarity("CCO", "CCCO")
    far = foundation.similarity("CCO", "c1ccccc1")
    assert close > far
    # the interpretable fingerprint model stays in 0..1
    assert 0.0 <= foundation.similarity("CCO", "CCCO", model="morgan") <= 1.0


def test_foundation_predict_properties():
    import foundation

    rows = foundation.predict(["CCO"], property="logp")
    assert rows[0]["value"] == pytest.approx(0.58, abs=0.05)
    assert rows[0]["model"] == "Physchem"
    qed = foundation.predict(["c1ccccc1"], property="qed")
    assert 0.0 < qed[0]["value"] <= 1.0
    with pytest.raises(Exception):
        foundation.predict(["CCO"], property="not_a_property")


def test_foundation_spectrum_modality():
    import foundation
    from workflow_engine.objects import Spectrum

    first = Spectrum.from_arrays([100, 200, 300], [0.1, 1.0, 0.2], mode="MS")
    second = Spectrum.from_arrays([100, 200, 300], [0.1, 0.9, 0.2], mode="MS")
    vectors = foundation.embed([first], model="spectrum-bin", modality="spectrum")
    assert len(vectors[0]) == 128
    assert (
        foundation.similarity(first, second, model="spectrum-bin", modality="spectrum")
        > 0.9
    )


# --------------------------------------------------------------------------- #
# AI configuration / switching
# --------------------------------------------------------------------------- #
def test_ai_config_roundtrip(ai_config):
    from ai_runtime.config import get_config, set_mode

    assert get_config().mode == "auto"
    set_mode("offline")
    assert ai_config.exists()
    assert json.loads(ai_config.read_text(encoding="utf-8"))["mode"] == "offline"
    # env override wins
    import os

    os.environ["CHEMML_AI_MODE"] = "cloud"
    from ai_runtime.config import load_config

    assert load_config(force=True).mode == "cloud"
    os.environ.pop("CHEMML_AI_MODE", None)


def test_ai_family_order_falls_back_to_offline(ai_config):
    from ai_runtime.config import family_order

    assert family_order("auto")[-1] == "offline"
    assert family_order("cloud") == ["cloud", "offline"]
    assert family_order("local") == ["local", "offline"]
    assert family_order("offline") == ["offline"]


def test_ai_complete_records_engine_and_skips(ai_config):
    import ai_runtime

    ai_runtime.set_mode("cloud")
    completion = ai_runtime.complete("say hello")
    # no cloud key is configured, so the offline engine answers -- and says so
    assert completion.family == "offline"
    assert "openai" in (completion.metadata.get("skipped") or {})
    ai_runtime.set_mode("offline")
    assert ai_runtime.complete("say hello").engine == "built-in"


# --------------------------------------------------------------------------- #
# data catalog
# --------------------------------------------------------------------------- #
def test_catalog_ingest_search_stats(catalog):
    records = catalog.ingest(str(DEMO_SPECTRUM), tags=["demo", "ms"])
    assert records and records[0]["type"] == "Spectrum"
    assert records[0]["embedding_model"] == "spectrum-bin"
    assert catalog.search("caffeine")
    assert catalog.search(tag="ms")
    assert catalog.get(records[0]["id"])["type"] == "Spectrum"
    stats = catalog.stats()
    assert stats["count"] == 1 and stats["embedded"] == 1


def test_catalog_molecule_embedding(catalog):
    from data_layer import wrap
    from nodes._helpers import build_molecule

    record = catalog.add(
        wrap(build_molecule("CCO", name="ethanol"), source="synthetic"),
        tags=["molecule"],
    )
    assert record["embedding_model"] == "morgan"
    assert len(record["embedding"]) == 256


# --------------------------------------------------------------------------- #
# simulation jobs
# --------------------------------------------------------------------------- #
def test_simulation_job_manager():
    from nodes._helpers import build_molecule
    from simulation_runtime.jobs import JobManager

    manager = JobManager(max_workers=1)
    try:
        job = manager.run_now(
            "quantum", build_molecule("CCO"), backend="orca", force_internal=True
        )
        assert job.status == "completed"
        assert job.engine.startswith("internal:")
        assert manager.get(job.id)["status"] == "completed"
        jobs = manager.list()
        assert len(jobs) == 1 and jobs[0]["family"] == "quantum"
    finally:
        manager.shutdown()


# --------------------------------------------------------------------------- #
# agent
# --------------------------------------------------------------------------- #
def test_agent_plans_and_summarises():
    from nodes.agent import plan_question, run_question, summarise

    outputs = run_question(
        "请分析这个未知化合物 C8H10N4O2", use_llm=False, remember=False
    )
    data = summarise(outputs)
    assert data["intent"]
    assert data["nodes"]
    assert data["conclusion"]
    assert data["engine"] == "rule-based"

    planned = plan_question("设计一个锂离子电池正极材料")
    assert "workflow" in planned and getattr(planned["workflow"], "text", "")


def test_agent_llm_fallback_is_recorded(ai_config):
    import ai_runtime
    from nodes.agent.planner import Planner

    ai_runtime.set_mode("offline")
    planner = Planner([])
    plan = planner.plan("分析未知化合物", use_llm=True)
    assert plan.engine == "rule-based"
    assert any("LLM" in note for note in plan.notes)


# --------------------------------------------------------------------------- #
# REST API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client(ai_config, tmp_path, monkeypatch):
    monkeypatch.setenv("CHEMML_CATALOG", str(tmp_path / "catalog.json"))
    from fastapi.testclient import TestClient

    from backend.app import create_app

    return TestClient(create_app())


def test_api_health_version(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    # v0.7 migration: the API version moved to 0.7.x; accept every released
    # 0.6/0.7 line so this regression test keeps guarding "a real version is
    # reported", not a specific marketing number.
    assert body["version"] in {"0.6.0", "0.7.0", "0.7.1", "0.7.2"}
    assert body["nodes"] >= 85


def test_api_ai_endpoints(client):
    modes = [row["mode"] for row in client.get("/api/ai/modes").json()]
    assert "auto" in modes and "offline" in modes
    state = client.get("/api/ai/providers").json()
    assert state["providers"]
    updated = client.put("/api/ai/config", json={"mode": "offline"})
    assert updated.status_code == 200 and updated.json()["mode"] == "offline"
    completion = client.post("/api/ai/complete", json={"prompt": "hello"})
    assert completion.status_code == 200 and completion.json()["engine"] == "built-in"


def test_api_foundation_endpoints(client):
    models = client.get("/api/foundation/models").json()
    assert models["count"] >= 8
    embed = client.post("/api/foundation/embed", json={"items": ["CCO"]}).json()
    assert embed["dimension"] == 384
    similarity = client.post(
        "/api/foundation/similarity", json={"a": "CCO", "b": "CCCO"}
    ).json()
    assert similarity["similarity"] > 0.5
    predict = client.post(
        "/api/foundation/predict", json={"items": ["CCO"], "property": "mw"}
    ).json()
    assert predict["rows"][0]["value"] == pytest.approx(46.07, abs=0.1)


def test_api_simulation_endpoints(client):
    backends = client.get("/api/simulations/backends").json()
    assert backends["count"] >= 3
    assert "eht" in backends["available"]
    job = client.post(
        "/api/simulations/run",
        json={"family": "quantum", "smiles": "CCO", "backend": "orca", "force_internal": True},
    ).json()
    assert job["status"] == "completed"
    assert job["engine"].startswith("internal:")
    listed = client.get("/api/simulations/jobs").json()
    assert listed["count"] >= 1


def test_api_data_endpoints(client):
    ingested = client.post(
        "/api/data/ingest",
        json={"path": str(DEMO_SPECTRUM), "tags": ["api"]},
    )
    assert ingested.status_code == 200 and ingested.json()["count"] == 1
    listing = client.get("/api/data/catalog?query=caffeine").json()
    assert listing["count"] >= 1
    entry_id = listing["entries"][0]["id"]
    assert client.get(f"/api/data/catalog/{entry_id}").json()["id"] == entry_id


def test_api_agent_plan_endpoint(client):
    response = client.post(
        "/api/agent/plan", json={"question": "请分析这个未知化合物 C8H10N4O2"}
    )
    assert response.status_code == 200
    assert len(response.json()["workflow"]) > 10
