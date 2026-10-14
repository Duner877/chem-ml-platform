"""HTTP client for the Chem ML Platform REST API.

Usage
-----
>>> from chemml_sdk import ChemMLClient
>>> client = ChemMLClient("http://127.0.0.1:8000")
>>> client.health()
{'status': 'ok', 'version': '0.7.2', 'nodes': 89}
>>> result = client.run_workflow("01_unknown_compound_identification.json")
>>> result.status
'completed'
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from chemml_sdk.node import load_nodes

__all__ = ["ChemMLClient"]


class ChemMLClient:
    """Minimal, dependency free REST client (``urllib`` only)."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    # -- transport ----------------------------------------------------------- #
    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        import urllib.error
        import urllib.request

        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                detail = json.loads(body).get("detail", body)
            except json.JSONDecodeError:
                detail = body
            raise RuntimeError(f"{method} {path} failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(
                f"cannot reach {self.base_url} -- is the backend running? ({exc.reason})"
            ) from exc

    # -- endpoints ----------------------------------------------------------- #
    def health(self) -> Dict[str, Any]:
        return self._request("GET", "/api/health")

    def categories(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/nodes/categories")

    def nodes(self, category: str = "", query: str = "") -> List[Dict[str, Any]]:
        params = []
        if category:
            params.append(f"category={category}")
        if query:
            params.append(f"query={query}")
        suffix = f"?{'&'.join(params)}" if params else ""
        return self._request("GET", f"/api/nodes{suffix}")

    def node(self, node_type: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/nodes/{node_type}")

    def workflows(self) -> List[Dict[str, Any]]:
        return self._request("GET", "/api/workflows")

    def workflow(self, filename: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/workflows/{filename}")

    def validate(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("POST", "/api/workflows/validate", workflow)

    def save_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and persist a workflow; returns the stored document."""
        return self._request("POST", "/api/workflows", workflow)

    def run_workflow(
        self, filename: str, inputs: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Execute a stored workflow and return the run result."""
        return self._request(
            "POST", f"/api/workflows/{filename}/run", {"inputs": inputs or {}}
        )

    def run(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an inline workflow definition."""
        return self._request("POST", "/api/workflows/run", workflow)

    def runs(self) -> List[Dict[str, Any]]:
        """Run history known to the backend, newest first."""
        return self._request("GET", "/api/runs")

    def run_events(self, run_id: str) -> List[Dict[str, Any]]:
        """Replay the event stream of a finished run."""
        return self._request("GET", f"/api/workflows/runs/{run_id}/events")

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        """The full record of a single run, including artefacts."""
        return self._request("GET", f"/api/workflows/runs/{run_id}")

    def artifact_url(self, path: str) -> str:
        """Download URL for a run artefact (CSV, JSON, MD, HTML, PNG...)."""
        return f"{self.base_url}/api/runs/artifacts/{path}"

    # -- local execution ----------------------------------------------------- #
    def run_local(
        self,
        workflow: Dict[str, Any],
        plugins_directory: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run a workflow in-process, without the HTTP backend.

        Useful for CI and for notebooks: the same node implementations and the
        same engine are used, only the transport is skipped.
        """
        from workflow_engine.engine import WorkflowEngine
        from workflow_engine.workflow import Workflow

        load_nodes(plugins_directory)
        engine = WorkflowEngine(max_workers=1, use_cache=False)
        result = engine.run(Workflow.from_dict(workflow))
        return result.to_dict()

    def summary(self, result: Dict[str, Any]) -> str:
        """One-line human readable summary of a run result."""
        records = result.get("records", {})
        failed = [rid for rid, rec in records.items() if rec.get("status") == "failed"]
        return (
            f"{result.get('workflow', 'workflow')}: {result.get('status')} "
            f"({len(records)} nodes, {result.get('duration_ms', 0):.0f} ms, "
            f"{len(failed)} failed)"
        )

    def node_types(self) -> List[str]:
        """Every node type known to the local installation."""
        load_nodes()
        from chemml_sdk.node import get_registry

        return get_registry().types()

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<ChemMLClient {self.base_url}>"


def run_many(client: ChemMLClient, files: Iterable[str]) -> List[Dict[str, Any]]:
    """Execute several stored workflows, returning one result per file."""
    return [client.run_workflow(name) for name in files]
