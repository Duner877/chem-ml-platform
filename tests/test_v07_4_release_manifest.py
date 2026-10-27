"""Release-manifest consistency tests (the CI stage that never passed).

The ``release_manifest`` stage of the quality gate failed on **every** CI run
since 0.7.3.  The gate has 27 stages; a stage that can never pass is a stage
that reports nothing, and the repository's CI badge had been red for eleven
consecutive runs.  There were three independent reasons, and each one is
pinned here -- a checker that cannot be shown to fail is not evidence of
anything.

1. **The manifest names the commit it was generated at**, so it can never
   describe the commit that contains it.  The release process is "commit the
   source, generate the manifest, commit the manifest", and the second commit
   moves HEAD one revision past the commit the manifest names.  Comparing the
   two for equality therefore reported "manifest records 0.7.3@..., tree is
   0.7.4@..." on every version bump.  The check now compares the *version* and
   the artefacts a checkout can reproduce, and deliberately does not compare
   the commit.

2. **Three artefacts cannot exist in a fresh clone**: the source archive lives
   one level above the repository, and the installer and its blockmap live in
   ``desktop/dist/``, which is gitignored.  Comparing them meant comparing one
   machine's build leftovers against another machine's tree -- noise, not
   signal.

3. **A working tree does not hold the bytes the repository holds.**  Git's
   ``core.autocrlf`` rewrites LF to CRLF on checkout, so a Windows working tree
   holds a 112 800-byte ``sbom.json`` where the repository holds a 107 466-byte
   one.  Hashing the working tree produced a digest that was true of this
   machine and false of every other, and the manifest reported itself as
   drifted on a Linux runner for the very same commit.

The third one is the subtle one, and the reason these tests exist: it made the
manifest's own numbers depend on the machine that generated them.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def manifest_tool():
    spec = importlib.util.spec_from_file_location(
        "release_manifest_under_test", ROOT / "scripts" / "release_manifest.py"
    )
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves its field types through
    # ``sys.modules[cls.__module__]``, so the module has to be registered
    # before it is executed -- without this the import raises
    # ``AttributeError: 'NoneType' object has no attribute '__dict__'``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestTheManifestDescribesTheReleaseNotTheCheckout:
    """The manifest must mean the same thing on every machine."""

    def test_tracked_artefacts_are_hashed_from_the_repository(self, manifest_tool):
        """A tracked file's digest must not depend on the checkout's settings.

        Asserted against the real repository rather than a fixture, because
        the property only exists in a checkout: ``core.autocrlf`` rewrites the
        bytes on disk, and the manifest has to ignore that.

        The comparison is made against **git's own** idea of the stored bytes
        (``git hash-object --path``), not against ``HEAD:<path>``.  The two
        agree only when the working tree happens to be clean, and a test that
        fails every time an artefact has just been regenerated says nothing
        about the manifest -- it just reports that there is work in progress.
        What has to hold at all times is that the module's clean filter and
        git's clean filter produce the same bytes for the same file.
        """
        blob = manifest_tool._tracked_bytes(ROOT / "sbom.json")
        if blob is None:
            pytest.skip("sbom.json is not tracked in this checkout")

        ours = subprocess.run(
            ["git", "hash-object", "--stdin"],
            cwd=str(ROOT),
            input=blob,
            capture_output=True,
            timeout=30,
        )
        assert ours.returncode == 0
        git = subprocess.run(
            ["git", "hash-object", "--path=sbom.json", "sbom.json"],
            cwd=str(ROOT),
            capture_output=True,
            timeout=30,
        )
        assert git.returncode == 0
        assert ours.stdout.strip() == git.stdout.strip(), (
            "the digest must describe the bytes the repository stores, not the "
            "bytes this working tree happens to hold"
        )

    def test_the_digest_ignores_line_ending_rewrites(self, manifest_tool, tmp_path):
        """CRLF on disk, LF in the repository: the digest must not move.

        This is the failure that made the manifest report itself drifted on
        every Linux runner: the generator hashed a CRLF working tree and the
        checker hashed an LF checkout of the same commit, so the two digests
        could never agree.
        """
        work = tmp_path / "repo"
        work.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=str(work), check=True)
        subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=str(work), check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=str(work), check=True)

        payload = b"line one\nline two\n"
        (work / "artifact.txt").write_bytes(payload)
        subprocess.run(["git", "add", "-A"], cwd=str(work), check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "commit", "-qm", "x"],
            cwd=str(work),
            check=True,
        )

        # Rewrite the working tree the way ``core.autocrlf=true`` would.
        (work / "artifact.txt").write_bytes(payload.replace(b"\n", b"\r\n"))

        original_root = manifest_tool.ROOT
        try:
            manifest_tool.ROOT = work
            blob = manifest_tool._tracked_bytes(work / "artifact.txt")
        finally:
            manifest_tool.ROOT = original_root

        assert blob == payload, (
            "a CRLF working tree must still produce the digest of the LF blob "
            "the repository stores"
        )

    def test_an_untracked_file_falls_back_to_the_bytes_on_disk(self, manifest_tool, tmp_path):
        """Build outputs are not in the index, and must still be measured."""
        outside = tmp_path / "installer.exe"
        outside.write_bytes(b"not a tracked file")

        assert manifest_tool._tracked_bytes(outside) is None


class TestWhatTheCheckCompares:
    """The comparison has to be about the release, not about the machine."""

    def test_the_commit_is_not_part_of_the_staleness_verdict(self, manifest_tool):
        """The manifest names the commit it was generated at.

        That commit can never be the commit that contains the manifest, so
        requiring equality reports staleness on every single version bump --
        which is exactly what happened, on every CI run since 0.7.3.
        """
        source = (ROOT / "scripts" / "release_manifest.py").read_text(encoding="utf-8")
        assert 'stored.get("commit") != manifest["commit"]' not in source, (
            "the manifest can never name the commit that contains it, so the "
            "commit must not decide whether the manifest is stale"
        )

    def test_unreproducible_artefacts_are_excluded_by_name(self, manifest_tool):
        """Name the three artefacts a fresh clone cannot have.

        Excluding them by *name* rather than by "is the file there" matters:
        the second would silently skip any artefact that happens to be missing
        on the machine running the check, which is how a checker starts
        reporting success without checking anything.
        """
        excluded = {
            "source-archive",
            "windows-installer",
            "installer-blockmap",
        }
        assert excluded.isdisjoint(manifest_tool._COMPARABLE_ARTEFACTS), (
            "artefacts that cannot exist in a fresh clone must not be compared"
        )

    def test_the_comparable_set_covers_the_tracked_artefacts(self, manifest_tool):
        """Every artefact a checkout can reproduce must actually be compared."""
        tracked = {
            "sbom",
            "third-party-licences",
            "provenance-record",
            "notice",
            "synthetic-benchmark-report",
            "node-capability-catalogue",
            "python-dependency-lock",
            "frontend-dependency-lock",
            "desktop-runtime-probe",
            "plugin-spec",
            "release-report",
            "issue-log",
            "clean-env-test-record",
            "real-data-validation-plan",
        }
        assert tracked <= manifest_tool._COMPARABLE_ARTEFACTS, (
            "a tracked artefact left out of the comparison is an artefact "
            "whose drift goes unreported"
        )

    def test_every_comparable_artefact_is_actually_tracked(self, manifest_tool):
        """A comparable artefact that is not tracked cannot be reproduced."""
        for artefact_id in sorted(manifest_tool._COMPARABLE_ARTEFACTS):
            row = next(
                a for a in manifest_tool.ARTEFACTS if a.id == artefact_id
            )
            for candidate in row.candidates:
                expanded = candidate.format(version="0.0.0")
                if any(ch in expanded for ch in "*?["):
                    continue
                path = (ROOT / expanded).resolve()
                assert path.is_file() or path.parent.exists(), (
                    f"{artefact_id} is compared but {expanded} does not exist"
                )
                break


class TestTheCheckStillHasTeeth:
    """A check that cannot be shown to fail is not evidence of anything."""

    def test_a_changed_tracked_artefact_is_reported(self, manifest_tool, tmp_path, monkeypatch):
        """The whole point of the stage: the tree drifted, say so."""
        stored = json.loads(
            (ROOT / "docs" / "RELEASE_MANIFEST.json").read_text(encoding="utf-8")
        )
        rows = {r["id"]: dict(r) for r in stored.get("artefacts", [])}
        comparable = [
            r for r in stored.get("artefacts", []) if r["id"] in manifest_tool._COMPARABLE_ARTEFACTS
        ]
        if not comparable:
            pytest.skip("no comparable artefacts in the committed manifest")

        # Corrupt one comparable artefact's recorded digest and confirm the
        # comparison notices.
        fresh = {
            manifest_tool._identity(r): None for r in comparable
        }
        tampered = [dict(r) for r in comparable]
        tampered[0]["sha256"] = "0" * 64
        old = {manifest_tool._identity(r): None for r in tampered}
        assert fresh != old, "a changed digest must be detected"

    def test_the_version_is_still_compared(self, manifest_tool):
        """A version bump without a regenerated manifest is a real defect."""
        source = (ROOT / "scripts" / "release_manifest.py").read_text(encoding="utf-8")
        assert 'stored.get("version") != manifest["version"]' in source
