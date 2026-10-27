"""v0.7.1 licence / SBOM / NOTICE tests (task K).

The report is generated from *real* dependency metadata, not a hardcoded list,
so these tests assert the inventory is populated, the SBOM is well formed and
the cleanliness scan actually detects an injected problem.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
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


class TestCheckModeDoesNotWrite:
    """v0.7.2 fix: ``main()`` used to write sbom.json / NOTICE /
    THIRD_PARTY_LICENSES.md *unconditionally*, including under ``--check``.

    A check that rewrites the artefacts it is supposed to verify can never
    detect a stale or tampered one -- it silently "repairs" it instead -- and it
    made the release manifest's recorded hashes drift on every gate run, so no
    released digest could be reproduced.  These tests pin the corrected
    contract: ``--check`` never writes, but it does detect drift.

    v0.7.4 fix: these tests used to exercise ``--write`` against the *real*
    artefacts in the repository.  That made the test suite a writer of the
    tree, and it is exactly what broke the release manifest on CI: pytest ran
    before the manifest stage, regenerated ``sbom.json`` / ``NOTICE`` /
    ``THIRD_PARTY_LICENSES.md`` with the runner's own dependency versions, and
    the manifest then compared the tree against digests recorded for different
    bytes.  The artefacts are now written into a temporary directory, and the
    repository's own copies are asserted to be untouched.
    """

    FILES = ("sbom.json", "NOTICE", "docs/THIRD_PARTY_LICENSES.md")

    def _rm(self, name: str, root: Path = ROOT) -> str:
        return (root / name).read_text(encoding="utf-8")

    @staticmethod
    def _write(lic, out_dir: Path) -> int:
        return lic.main(["--write", "--out-dir", str(out_dir)])

    @staticmethod
    def _rebaseline(lic, out_dir: Path) -> None:
        """Regenerate the artefacts so a test starts from a known-good state.

        Without this the tampering tests would silently depend on whatever the
        working tree happened to contain when the suite started (for example a
        ``frontend/dist`` left over from an earlier build), which is exactly the
        kind of hidden coupling the v0.7.2 gate is meant to eliminate.
        """
        assert TestCheckModeDoesNotWrite._write(lic, out_dir) == 0

    def test_check_leaves_artifacts_untouched(self, lic, tmp_path):
        out = tmp_path / "out"
        self._rebaseline(lic, out)
        before = {name: self._rm(name, out) for name in self.FILES}
        assert lic.main(["--check", "--out-dir", str(out)]) in (0, 1)
        after = {name: self._rm(name, out) for name in self.FILES}
        assert after == before, "--check must never modify the artefacts it verifies"

    def test_check_detects_a_tampered_artifact(self, lic, tmp_path):
        out = tmp_path / "out"
        self._rebaseline(lic, out)
        target = out / "NOTICE"
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(original + "\n# injected\n", encoding="utf-8")
            assert lic.main(["--check", "--out-dir", str(out)]) == 1, (
                "--check must fail on a stale artefact"
            )
        finally:
            target.write_text(original, encoding="utf-8")
        assert lic.main(["--check", "--out-dir", str(out)]) == 0, (
            "--check must pass once the artefact is restored"
        )

    def test_check_does_not_repair_the_tampered_artifact(self, lic, tmp_path):
        out = tmp_path / "out"
        self._rebaseline(lic, out)
        target = out / "NOTICE"
        original = target.read_text(encoding="utf-8")
        try:
            target.write_text(original + "\n# injected\n", encoding="utf-8")
            lic.main(["--check", "--out-dir", str(out)])
            assert target.read_text(encoding="utf-8") == original + "\n# injected\n", (
                "--check silently repaired the file it was asked to verify"
            )
        finally:
            target.write_text(original, encoding="utf-8")

    def test_write_flag_exists_and_is_idempotent(self, lic, tmp_path):
        """CI stage 8 and the release manifest both document ``--write``."""
        out = tmp_path / "out"
        assert self._write(lic, out) == 0
        first = {name: self._rm(name, out) for name in self.FILES}
        assert self._write(lic, out) == 0
        second = {name: self._rm(name, out) for name in self.FILES}
        assert first == second, "regeneration must be deterministic"

    def test_writing_does_not_touch_the_repository(self, lic, tmp_path):
        """The suite must never write the tree's own artefacts.

        This is the regression that made the release manifest drift on CI: the
        test suite regenerated the real ``sbom.json`` / ``NOTICE`` /
        ``THIRD_PARTY_LICENSES.md`` with the runner's dependency versions, and
        the manifest stage then compared those bytes against digests recorded
        for the committed ones.
        """
        before = {name: self._rm(name) for name in self.FILES}
        out = tmp_path / "out"
        assert self._write(lic, out) == 0
        after = {name: self._rm(name) for name in self.FILES}
        assert after == before, (
            "the test suite rewrote the repository's own licence artefacts; "
            "their digests are pinned in the release manifest"
        )

    def test_document_does_not_depend_on_the_local_build_output(self, lic, tmp_path):
        """Regression: the licence document must not vary with transient state.

        The document's SHA-256 is pinned in ``docs/RELEASE_MANIFEST.json``, so
        any content that depends on the *local* working tree -- the emitted
        ``frontend/dist`` bundle count, ``__pycache__`` presence -- makes the
        recorded digest impossible to re-derive.  That is exactly how the
        manifest came to report ``third-party-licences`` as drifted: an earlier
        gate stage rebuilt the frontend between manifest generation and the
        manifest check.  Licensing conclusions are a property of the release
        package and of the locked dependency graph, never of a build artefact
        that happens to sit in the tree.
        """
        out = tmp_path / "out"
        self._rebaseline(lic, out)
        baseline = {name: self._rm(name, out) for name in self.FILES}

        dist = ROOT / "frontend" / "dist"
        stashed = None
        if dist.exists():
            stashed = ROOT / "frontend" / "_dist_stashed_for_test"
            if stashed.exists():
                shutil.rmtree(stashed)
            dist.rename(stashed)
        try:
            assert self._write(lic, out) == 0
            without_dist = {name: self._rm(name, out) for name in self.FILES}
            assert without_dist == baseline, (
                "the licence document changed because frontend/dist was absent; "
                "its digest is pinned in the release manifest and must be "
                "reproducible from the locked dependency graph alone"
            )
        finally:
            if stashed is not None and stashed.exists():
                stashed.rename(dist)


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



class TestCopyrightHolder:
    """The copyright holder must name someone.

    Both the LICENSE and the NOTICE shipped unfilled placeholders until
    v0.7.3: ``LICENSE`` line 189 was Apache's own
    ``Copyright [yyyy] [name of copyright owner]`` and the NOTICE read
    ``Copyright (c) 2026 Chem ML Platform contributors`` -- a holder that names
    nobody.  For an Apache-2.0 project going public that is the one line that
    tells a reader who may redistribute it under what name, and it was the
    blankest possible value.

    The two files are generated from different sources (a static LICENSE file
    and ``license_report.COPYRIGHT_HOLDER``), so they can drift; these tests
    check both against each other rather than trusting either.
    """

    #: the Apache-2.0 appendix placeholder, verbatim
    PLACEHOLDER = "Copyright [yyyy] [name of copyright owner]"

    def test_holder_is_not_the_apache_template_placeholder(self, lic):
        assert lic.COPYRIGHT_HOLDER.strip(), "copyright holder must not be empty"
        assert "[yyyy]" not in lic.COPYRIGHT_HOLDER
        assert "[" not in lic.COPYRIGHT_HOLDER, (
            f"copyright holder still carries a placeholder: {lic.COPYRIGHT_HOLDER!r}"
        )

    def test_license_file_carries_the_real_holder(self, lic):
        licence_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        assert self.PLACEHOLDER not in licence_text, (
            "LICENSE still ships Apache's template placeholder; run the "
            "copyright-holder fixup so redistribution terms name a holder"
        )
        assert lic.COPYRIGHT_HOLDER in licence_text, (
            "LICENSE and license_report.COPYRIGHT_HOLDER disagree -- the "
            "Apache-2.0 appendix must name the same holder as the NOTICE"
        )

    def test_notice_and_license_agree(self, lic):
        notice = lic.build_notice([], [], [])
        assert f"Copyright (c) 2026 {lic.COPYRIGHT_HOLDER}" in notice
        assert "contributors" not in notice.splitlines()[1], (
            "NOTICE fell back to the anonymous 'contributors' holder"
        )

    def test_provenance_document_names_the_holder(self, lic):
        provenance = (ROOT / "docs" / "PROVENANCE.md").read_text(encoding="utf-8")
        assert lic.COPYRIGHT_HOLDER in provenance, (
            "docs/PROVENANCE.md must name the same copyright holder as LICENSE"
        )
