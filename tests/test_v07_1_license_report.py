"""v0.7.1 licence / SBOM / NOTICE tests (task K).

The report is generated from *real* dependency metadata, not a hardcoded list,
so these tests assert the inventory is populated, the SBOM is well formed and
the cleanliness scan actually detects an injected problem.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def lic():
    spec = importlib.util.spec_from_file_location(
        "license_report", ROOT / "scripts" / "license_report.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestInventories:
    def test_python_dependencies_are_resolved(self, lic):
        components = lic.python_components()
        assert components, "requirements.txt should declare dependencies"
        resolved = [c for c in components if c["installed"]]
        assert resolved, "at least one declared dependency must be installed"
        # licences are read from real metadata, so they must not all be UNKNOWN
        known = [c for c in resolved if c["license"] and c["license"] != "UNKNOWN"]
        assert len(known) >= len(resolved) // 2

    def test_frontend_dependencies_come_from_the_lockfile(self, lic):
        components = lic.frontend_components()
        assert len(components) > 50, "the locked npm graph is large"
        assert all(c["license"] for c in components), "every locked package has a licence field"

    def test_external_tools_are_never_bundled(self, lic):
        components = lic.external_components()
        assert components
        for component in components:
            assert component["ecosystem"] == "external"
            assert "never bundled" in component["note"].lower()

    def test_datasets_carry_licence_and_source(self, lic):
        components = lic.dataset_components()
        assert components
        for component in components:
            assert component["license"]
            assert "datasets/" in component["note"]


class TestSbom:
    def test_sbom_is_well_formed(self, lic):
        data = lic.collect()
        sbom = lic.build_sbom(data["python"], data["npm"], data["external"], data["datasets"])
        assert sbom["bomFormat"] == "CycloneDX"
        assert sbom["metadata"]["component"]["version"] == lic.PROJECT_VERSION
        for component in sbom["components"]:
            assert component["name"]
            assert component["licenses"]
            assert any(p["name"] == "chemml:ecosystem" for p in component["properties"])

    def test_notice_lists_bundled_and_external_separately(self, lic):
        data = lic.collect()
        notice = lic.build_notice(data["python"], data["npm"], data["external"])
        assert "BUNDLED SOFTWARE" in notice
        assert "NOT distributed with this product" in notice


class TestCleanliness:
    def test_detects_injected_pyc(self, lic, tmp_path, monkeypatch):
        monkeypatch.setattr(lic, "ROOT", tmp_path)
        (tmp_path / "module.pyc").write_bytes(b"\x00")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "__pycache__").mkdir()
        problems = lic.cleanliness_scan()
        assert problems["pyc"]
        assert problems["pycache"]

    def test_secret_scan_skips_test_fixtures(self, lic):
        # the repository's own tests intentionally embed fake keys
        problems = lic.cleanliness_scan()
        assert not any("tests/" in item for item in problems["secrets"])


class TestPackagingRule:
    """P2-04: the packager must never ship caches, keys or runtime data."""

    @pytest.fixture(scope="class")
    def packager(self):
        spec = importlib.util.spec_from_file_location("packager", ROOT / "scripts" / "package.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    @pytest.mark.parametrize(
        "rel",
        [
            "memory/__pycache__/store.cpython-313.pyc",
            "memory/__pycache__/__init__.cpython-313.pyc",
            "nodes/__pycache__/report.cpython-313.pyc",
            "backend/app.pyc",
            "memory/agent_memory.json",
            "output/runs/run_x/events.jsonl",
            "config/ai.json",
            "node_modules/react/index.js",
            "desktop/dist/Chem ML Platform Setup 0.7.1.exe",
            "desktop/out/mac/Chem ML Platform.dmg",
        ],
    )
    def test_forbidden_paths_are_skipped(self, packager, rel):
        assert packager.should_skip(Path(rel)) is True

    @pytest.mark.parametrize(
        "rel",
        [
            "frontend/dist/assets/index.js",
            "desktop/src/main.js",
            "desktop/package.json",
            "output/.gitkeep",
            "memory/store.py",
            "config/ai.example.json",
            "backend/app.py",
        ],
    )
    def test_required_paths_are_shipped(self, packager, rel):
        assert packager.should_skip(Path(rel)) is False

