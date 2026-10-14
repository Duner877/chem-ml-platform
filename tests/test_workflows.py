"""Demo workflow and API tests."""

from __future__ import annotations

import pytest

from workflow_engine.workflow import Workflow


def test_demo_workflows_exist(workflow_files):
    assert len(workflow_files) >= 3, "expected the three official demo workflows"


@pytest.mark.parametrize("index", [0, 1, 2])
def test_demo_workflow_is_valid(registry, workflow_files, index):
    """Every demo workflow validates against the registry."""
    workflow = Workflow.from_file(workflow_files[index])
    assert not workflow.validate(registry), workflow.validate(registry)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_demo_workflow_executes(registry, workflow_files, index):
    """Every demo workflow runs to completion without node errors."""
    from workflow_engine.engine import WorkflowEngine

    workflow = Workflow.from_file(workflow_files[index])
    engine = WorkflowEngine(registry=registry, use_cache=False)
    result = engine.run(workflow)
    assert result.ok, result.errors
    assert all(
        record.status == "completed" for record in result.records.values()
    ), {k: v.status for k, v in result.records.items()}


def test_demo_workflow_produces_artifacts(registry, workflow_files):
    from workflow_engine.engine import WorkflowEngine

    workflow = Workflow.from_file(workflow_files[0])
    engine = WorkflowEngine(registry=registry, use_cache=False)
    result = engine.run(workflow)
    assert result.artifacts, "no artefacts were written"


# --------------------------------------------------------------------------- #
# REST API
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.app import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_health_endpoint(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["nodes"] >= 20


def test_node_catalogue_endpoint(client):
    response = client.get("/api/nodes/categories")
    assert response.status_code == 200
    categories = response.json()
    assert len(categories) >= 10
    assert sum(bucket["count"] for bucket in categories) >= 20


def test_node_detail_endpoint(client):
    response = client.get("/api/nodes/IRNode")
    assert response.status_code == 200
    spec = response.json()
    assert spec["type"] == "IRNode"
    assert spec["inputs"]
    assert spec["parameters"]


def test_node_detail_unknown_type(client):
    assert client.get("/api/nodes/DoesNotExist").status_code == 404


def test_workflow_listing_endpoint(client):
    response = client.get("/api/workflows")
    assert response.status_code == 200
    assert len(response.json()) >= 3


def test_workflow_validation_endpoint(client):
    response = client.post(
        "/api/workflows/validate",
        json={
            "name": "t",
            "nodes": [{"id": "a", "type": "IRNode", "params": {"smiles": "CCO"}}],
            "edges": [],
        },
    )
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_workflow_validation_reports_issues(client):
    response = client.post(
        "/api/workflows/validate",
        json={"name": "t", "nodes": [{"id": "a", "type": "NoSuchNode"}], "edges": []},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert payload["issues"]


def test_inline_run_endpoint(client):
    response = client.post(
        "/api/workflows/run",
        json={
            "name": "inline",
            "nodes": [
                {"id": "a", "type": "IRNode", "params": {"smiles": "CCO"}}
            ],
            "edges": [],
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["records"]["a"]["status"] == "completed"


def test_stored_workflow_run_endpoint(client):
    response = client.post(
        "/api/workflows/01_unknown_compound_identification.json/run", json={}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["errors"] == []
