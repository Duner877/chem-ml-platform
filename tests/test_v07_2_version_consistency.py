"""v0.7.2 version-consistency tests (task P0-04 regression, ISSUE-18).

The v0.7.2 package shipped with three *user-visible* stale version strings --
``v0.6.0`` on the launcher banner, ``v0.7.1`` in the browser tab title, and
``0.7.1`` on all 86 node records -- while ``scripts/version.py --check`` still
reported ``OK``.  The check was not wrong, it was *incomplete*: it only swept the
files somebody remembered to list.

These tests pin the property that matters, in two directions:

* the live tree really is consistent (including the places that were missed), and
* the detector really does fail when one of those places goes stale.

The second half is the important one.  A consistency check that cannot be shown
to fail is not evidence of anything.
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ver():
    spec = importlib.util.spec_from_file_location(
        "version_tool", ROOT / "scripts" / "version.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestLiveTreeIsConsistent:
    def test_check_reports_no_drift(self, ver):
        assert ver.collect_drift() == []

    def test_user_visible_targets_all_match(self, ver):
        """Every file that shows a version to a human must agree with VERSION."""
        seen = 0
        for label, rel, pattern, required in ver.ALL_TEXT_TARGETS:
            path = ROOT / rel
            if not path.exists():
                assert not required, f"{label}: required file {rel} is missing"
                continue
            found = re.findall(pattern, path.read_text(encoding="utf-8"), re.M)
            assert found, f"{label}: pattern matched nothing in {rel}"
            assert set(found) == {ver.VERSION}, f"{label}: {sorted(set(found))} in {rel}"
            seen += 1
        assert seen >= 8, "the sweep should cover the launchers, the tab title and docker"

    def test_node_catalogue_agrees(self, ver):
        reg = json.loads((ROOT / "node_registry" / "registry.json").read_text(encoding="utf-8"))
        assert reg["nodes"], "the catalogue must not be empty"
        assert {n["version"] for n in reg["nodes"]} == {ver.VERSION}

    def test_no_node_module_restates_the_platform_version(self):
        """Nodes inherit the version; a literal here is the bug that shipped."""
        offenders = []
        for path in sorted((ROOT / "nodes").rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            if re.search(r'^\s+version\s*=\s*"\d+\.\d+\.\d+"', path.read_text(encoding="utf-8"), re.M):
                offenders.append(str(path.relative_to(ROOT)))
        assert offenders == [], f"nodes must not hard-code a version: {offenders}"

    def test_node_base_defaults_to_the_platform_version(self):
        from chemml_version import VERSION
        from workflow_engine.node_base import ScientificNode

        assert ScientificNode.version == VERSION


class TestDetectorActuallyFails:
    """Each historical defect must be *detectable*, not merely absent."""

    def _minimal_tree(self, tmp_path, name: str, text: str) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return tmp_path

    def test_stale_launcher_banner_is_detected(self, ver, tmp_path, monkeypatch):
        self._minimal_tree(
            tmp_path, "start-platform.bat", "echo   Chem ML Platform v0.6.0  -  Old\n"
        )
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        drift = ver.collect_drift()
        assert any("launcher banner (browser)" in d and "0.6.0" in d for d in drift), drift

    def test_stale_browser_tab_title_is_detected(self, ver, tmp_path, monkeypatch):
        self._minimal_tree(
            tmp_path,
            "frontend/index.html",
            "<title>Chem ML Platform v0.7.1</title>\n",
        )
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        drift = ver.collect_drift()
        assert any("browser tab title" in d and "0.7.1" in d for d in drift), drift

    def test_stale_node_catalogue_version_is_detected(self, ver, tmp_path, monkeypatch):
        target = tmp_path / "node_registry"
        target.mkdir()
        (target / "registry.json").write_text(
            json.dumps({"nodes": [{"version": "0.7.1"}, {"version": ver.VERSION}]}),
            encoding="utf-8",
        )
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        drift = ver.collect_drift()
        assert any("registry.json" in d and "0.7.1" in d for d in drift), drift

    def test_stale_compose_image_tag_is_detected(self, ver, tmp_path, monkeypatch):
        self._minimal_tree(
            tmp_path,
            "docker-compose.yml",
            "# Chem ML Platform v0.7.1 -- compose stack.\n"
            "    image: chem-ml-platform:0.7.1\n",
        )
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        drift = ver.collect_drift()
        assert any("root compose header" in d for d in drift), drift
        assert any("root compose image tag" in d for d in drift), drift

    def test_write_repairs_a_stale_banner_and_preserves_prose(self, ver, tmp_path, monkeypatch):
        path = tmp_path / "start-platform.bat"
        path.write_text(
            "echo   Chem ML Platform v0.6.0  -  Scientific Foundation Model Edition\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        ver.stamp()
        text = path.read_text(encoding="utf-8")
        assert ver.VERSION in text
        assert "0.6.0" not in text
        # only the version token is rewritten; the rest of the banner survives
        assert "Scientific Foundation Model Edition" in text


class TestAncestorGitRepoIsNotClaimedAsProvenance:
    """ISSUE-21 follow-up: an ancestor checkout is not this tree's provenance.

    ``git rev-parse`` answers for *any* parent repository.  Before the guard, a
    distributed copy extracted inside an unrelated checkout reported that
    repository's HEAD as its own build commit -- a fabricated provenance, the
    one failure this module exists to prevent.  The guard: only a tree whose
    root *is* the Git top level may answer from Git.
    """

    PROBE = "import chemml_version;print(chemml_version.git_commit(), chemml_version.commit_source())"

    def _nested_copy(self, tmp_path):
        """A copy of the version module inside a *different* Git checkout."""
        foreign = tmp_path / "someone-elses-repo"
        nested = foreign / "extracted" / "chemml"
        nested.mkdir(parents=True)
        shutil.copy2(ROOT / "chemml_version.py", nested / "chemml_version.py")
        # Every git call is pinned to the foreign repo with -C: a bare
        # ``git commit`` would run against whatever cwd the test happens to
        # have -- which once silently created a stray commit in THIS repo.
        subprocess.run(
            ["git", "init", "-q", str(foreign)], capture_output=True, timeout=60
        )
        subprocess.run(
            ["git", "-C", str(foreign),
             "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
             "commit", "-q", "--allow-empty", "-m", "unrelated"],
            capture_output=True, timeout=60,
        )
        return nested

    def test_live_checkout_still_answers_from_git(self):
        """The guard must not disable provenance for the real repository."""
        from chemml_version import commit_source, git_commit

        assert commit_source() == "git"
        assert git_commit() != "unknown"

    def test_nested_copy_reports_unknown_without_a_stamp(self, tmp_path):
        nested = self._nested_copy(tmp_path)
        proc = subprocess.run(
            [sys.executable, "-c", self.PROBE],
            cwd=str(nested), capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-1000:]
        commit, source = proc.stdout.split()
        assert commit == "unknown", "an ancestor repo's HEAD must never be adopted"
        assert source == "unknown"

    def test_nested_copy_prefers_its_own_build_stamp(self, tmp_path):
        nested = self._nested_copy(tmp_path)
        (nested / "BUILD_INFO.json").write_text(
            json.dumps({"commit": "abcdef1234567890", "commit_short": "abcdef1"}),
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, "-c", self.PROBE],
            cwd=str(nested), capture_output=True, text=True, timeout=120,
        )
        assert proc.returncode == 0, proc.stderr[-1000:]
        commit, source = proc.stdout.split()
        assert commit == "abcdef1"
        assert source == "BUILD_INFO.json"


class TestBuildOutputIsRegeneratedNotStamped:
    def test_write_skips_optional_build_output(self, ver, tmp_path, monkeypatch):
        """``frontend/dist`` is produced by vite; stamping it would be a lie."""
        dist = tmp_path / "frontend" / "dist"
        dist.mkdir(parents=True)
        built = dist / "index.html"
        built.write_text("<title>Chem ML Platform v0.7.1</title>\n", encoding="utf-8")
        monkeypatch.setattr(ver, "ROOT", tmp_path)
        changed = ver.stamp()
        assert not any("dist/index.html" in c for c in changed), changed
        assert "v0.7.1" in built.read_text(encoding="utf-8")


class TestArchiveDoesNotShipItsOwnChecksum:
    """ISSUE-20: the archive must not contain the manifest that hashes it.

    ``SHA256SUMS`` records the archive's own SHA-256 plus machine-local absolute
    paths.  Shipped inside the archive it is *always* one generation stale, and
    it makes the archive hash depend on a file that describes that hash.  The
    manifest is published beside the archive instead, where it is verifiable.
    """

    @pytest.fixture(scope="class")
    def pkg(self):
        spec = importlib.util.spec_from_file_location(
            "package_tool", ROOT / "scripts" / "package.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_should_skip_excludes_the_self_referential_manifests(self, pkg):
        from pathlib import Path as P

        for rel in ("SHA256SUMS", "docs/RELEASE_MANIFEST.md", "docs/RELEASE_MANIFEST.json"):
            assert pkg.should_skip(P(rel)), f"{rel} must not be shipped inside the archive"

    def test_built_archive_contains_no_manifest_of_itself(self, pkg, tmp_path):
        import zipfile

        out = tmp_path / "probe.zip"
        pkg.build(out, "Probe")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert not any(n.endswith("/SHA256SUMS") for n in names), names
        assert not any("RELEASE_MANIFEST" in n for n in names), names

    def test_build_stamps_provenance_into_the_archive(self, pkg, tmp_path):
        """A distributed copy must be able to name its own build commit."""
        import json
        import zipfile

        from chemml_version import git_commit

        out = tmp_path / "probe.zip"
        pkg.build(out, "Probe")
        with zipfile.ZipFile(out) as zf:
            info = json.loads(zf.read("Probe/BUILD_INFO.json").decode("utf-8"))
        assert info["version"] == "0.7.2"
        assert info["commit"] != "unknown", "the build must know its own commit"
        # both hash widths must agree with what git_commit() reports, so a dev
        # tree and an extracted copy answer the *same* question identically
        assert info["commit_short"] == git_commit()
        assert info["commit"] == git_commit(short=False)
        assert info["commit"].startswith(info["commit_short"])

    def test_workspace_runtime_state_is_not_shipped(self, pkg, tmp_path):
        import zipfile

        out = tmp_path / "probe.zip"
        pkg.build(out, "Probe")
        with zipfile.ZipFile(out) as zf:
            shipped = [n for n in zf.namelist() if "/workspace/" in n]
        assert shipped == ["Probe/workspace/.gitkeep"], shipped
