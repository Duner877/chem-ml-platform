"""v0.7.2 regression tests for the ``?workflow=`` deep link.

The UI documents ``?workflow=<name>`` but the demo drawer lists bare file names
(``07_mzml_mass_spec_analysis.json``).  The endpoint used to demand the exact
file name, so the documented deep link 404'd -- and the frontend then reported
the whole backend as offline, blanking the UI.  Both halves are pinned here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: A workflow that ships with the platform, named by its stem.
STEM = "07_mzml_mass_spec_analysis"


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from backend.app import create_app

    return TestClient(create_app())


class TestWorkflowDeepLink:
    def test_loads_by_bare_stem(self, client):
        """``?workflow=07_mzml_mass_spec_analysis`` must resolve."""
        response = client.get(f"/api/workflows/{STEM}")
        assert response.status_code == 200, response.text
        assert response.json()["nodes"]

    def test_loads_by_file_name(self, client):
        """The drawer's own ``*.json`` spelling keeps working."""
        response = client.get(f"/api/workflows/{STEM}.json")
        assert response.status_code == 200, response.text
        assert response.json()["nodes"]

    def test_both_spellings_return_the_same_workflow(self, client):
        by_stem = client.get(f"/api/workflows/{STEM}").json()
        by_file = client.get(f"/api/workflows/{STEM}.json").json()
        assert by_stem == by_file

    def test_unknown_workflow_still_404s(self, client):
        assert client.get("/api/workflows/no_such_workflow").status_code == 404

    def test_traversal_is_refused(self, client):
        """The bare-stem fallback must not weaken the containment check."""
        for probe in ("..%2Fchemml_version", "..%2F..%2Fetc%2Fpasswd"):
            response = client.get(f"/api/workflows/{probe}")
            assert response.status_code == 404, probe


class TestDeepLinkDoesNotFakeOffline:
    def test_app_tsx_does_not_report_offline_on_a_bad_deep_link(self):
        """A missing workflow is a bad URL, not a dead backend.

        The online/offline state belongs to the health poll; a rejected
        ``?workflow=`` must not flip it and blank the whole interface.
        """
        source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        workflow_call = source.split("api\n            .workflow(requested)")[1]
        catch = workflow_call.split(".catch(")[1].split(");")[0]
        assert "setBackend" not in catch, catch




class TestArtifactPathsAreUsableUrls:
    """Artefact paths travel to the browser as URL path segments.

    ``str(Path(...))`` yields Windows separators, which produces a link that
    404s the moment it is clicked, so the API must emit POSIX separators and
    the download endpoint must accept exactly what it emitted.
    """

    def test_relative_artifacts_uses_forward_slashes(self):
        from backend.routers import workflows as wf_router

        artefact = wf_router.ROOT / "output" / "api_runs" / "runs" / "x" / "a b.html"
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text("<html></html>", encoding="utf-8")
        try:
            result = wf_router._relative_artifacts([str(artefact)])
        finally:
            artefact.unlink()

        assert result, "artefact should resolve relative to the repo root"
        assert "\\" not in result[0], result
        assert result[0].startswith("output/"), result

    def test_download_endpoint_accepts_posix_relative_path(self, client):
        import urllib.parse

        from backend.routers.runs import ARTIFACT_ROOTS

        # Must sit under a registered artefact root: the containment check that
        # rejects anything else is the endpoint's job, not an obstacle here.
        artefact = ARTIFACT_ROOTS[0] / "pytest_deeplink" / "report name.html"
        artefact.parent.mkdir(parents=True, exist_ok=True)
        artefact.write_text("<html>ok</html>", encoding="utf-8")
        try:
            relative = artefact.relative_to(
                Path(__file__).resolve().parents[1]
            ).as_posix()
            response = client.get(
                "/api/runs/artifacts/" + urllib.parse.quote(relative)
            )
        finally:
            artefact.unlink()
        assert response.status_code == 200, response.text
