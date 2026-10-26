"""Release safety: the source archive must never carry user state (v0.7.3 P0-1).

The audit found that ``scripts/package.py::should_skip()`` treated ``config/``
with ``return rel_posix.endswith("ai.json")``.  That reads like an allow-list
but is a single deny-entry: ``config/credentials.json`` (plaintext provider API
keys) and ``config/session.json`` (the desktop session token) both shipped.
The published zip happened to contain an *empty* ``credentials.json`` -- not
because the rule was safe, but because nobody had configured a key in that
work tree yet.  One real key later, it would have been public.

These tests pin the behaviour from three angles:

1. the *rule* -- forbidden paths are skipped, required paths still ship;
2. the *archive* -- real sentinel secrets planted in a throwaway tree do not
   appear in the produced zip (end to end, not a unit test of a predicate);
3. the *guard* -- the post-build scan actually catches a planted leak, so a
   future rule regression fails the build instead of publishing.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGER_SOURCE = ROOT / "scripts" / "package.py"

#: Values that must never appear in a published archive.  Each one is a real
#: credential *shape* -- a scan that only matched the literal test strings would
#: prove nothing about a scan run against a user's actual key.
SENTINEL = "SENTINEL-do-not-ship-9f2c1a7b4e6d"


@pytest.fixture
def scratch():
    """A temp directory **outside the repository tree**.

    Deliberately not ``tmp_path``: the quality gate runs pytest with
    ``--basetemp`` pointed inside ``output/``, so a ``tmp_path`` fixture would
    plant these deliberately credential-shaped fixtures in the very tree the
    licence/secret scan walks -- and the release gate would then fail on its
    own test data, which is how a scanner gets switched off.  ``tempfile`` puts
    them in the OS temp directory where they belong.
    """
    path = Path(tempfile.mkdtemp(prefix="chemml-packaging-test-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="module")
def packager():
    spec = importlib.util.spec_from_file_location("packager_v073", ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def real_archive(packager):
    """Package the actual repository, exactly as a release would.

    Module scoped: building the real archive is the expensive part, and the
    archive is immutable once built, so every test can share it safely.  ``scan``
    is off here because the *scan* is what these tests are exercising -- turning
    it on would delete the artefact out from under them.

    Deliberately ``tempfile`` and not ``tmp_path``: the quality gate points
    pytest's ``--basetemp`` inside ``output/``, and a full archive of the working
    tree planted there would be walked by the licence/secret scan afterwards.
    """
    work = Path(tempfile.mkdtemp(prefix="chemml-real-scan-"))
    out = work / "tree.zip"
    try:
        packager.build(out, name="tree", scan=False)
        yield out
    finally:
        shutil.rmtree(work, ignore_errors=True)


class TestPackagingRuleIsAnAllowList:
    """The rule itself: state files are excluded by default, not by name."""

    @pytest.mark.parametrize(
        "rel",
        [
            # The two files the audit named explicitly.
            "config/credentials.json",
            "config/session.json",
            # ...and everything else config/ might grow into.
            "config/tokens.json",
            "config/oauth.json",
            "config/subdir/credentials.json",
            "config/private/notes.txt",
            # Dotenv, root and nested.
            ".env",
            ".env.production",
            "backend/.env",
            "backend/.env.local",
            # Private plugins (examples/ is tracked source and still ships).
            "plugins/private_plugin.py",
            "plugins/nested/thing.py",
            # Runtime state that must not travel.
            "memory/memory.json",
            "output/runs/run_1/events.jsonl",
            "output/security_audit.jsonl",
            "workspace/raw_data/sample.csv",
            # Key material.
            "certs/server.pem",
            "id_rsa",
        ],
    )
    def test_state_is_excluded(self, packager, rel):
        assert packager.should_skip(Path(rel)) is True, f"{rel} must not be published"

    @pytest.mark.parametrize(
        "rel",
        [
            # config/ keeps exactly these three, and they must remain shippable
            # or a fresh clone has no configuration template at all.
            "config/ai.example.json",
            "config/.gitkeep",
            "config/ai.json.example",
            # Tracked example plugin still ships.
            "examples/plugins/melting_point_note.py",
            # ...and the ordinary source tree is untouched.
            "backend/app.py",
            # v0.7.4: the node implementations moved into ``custom_nodes/``.
            # Both trees ship: ``custom_nodes/`` holds the implementations and
            # ``nodes/`` holds the legacy import facade the old code paths
            # still resolve through.
            "custom_nodes/data_io/io.py",
            "nodes/__init__.py",
            "scripts/package.py",
            ".env.example",
            "frontend/dist/assets/index.js",
        ],
    )
    def test_source_is_still_shipped(self, packager, rel):
        assert packager.should_skip(Path(rel)) is False, f"{rel} must still ship"

    def test_the_config_rule_is_an_allow_list_not_a_deny_list(self, packager):
        """A guard against the exact regression shape.

        The old rule returned ``False`` (ship it) for *every* config path that
        did not end in ``ai.json``.  Whatever this function returns, a file the
        allow-list has never heard of must be excluded -- otherwise the next
        secret config file is public by default.
        """
        for name in ("credentials.json", "session.json", "brand_new_secret.json"):
            rel = Path("config") / name
            assert packager.should_skip(rel) is True
        assert packager.CONFIG_ALLOWLIST == {
            "config/.gitkeep",
            "config/ai.example.json",
            "config/ai.json.example",
        }


class TestArchiveReallyExcludesSecrets:
    """End to end: plant real-shaped secrets, produce a zip, look inside."""

    # Function scoped on purpose: each test gets its own throwaway tree, so one
    # test can never observe another's leftovers.  The tree is a handful of tiny
    # files, so re-building it per test costs nothing.
    @pytest.fixture
    def built(self, scratch, packager):
        """Package a synthetic tree that mimics a configured work tree."""
        work = scratch / "configured_worktree"
        work.mkdir(parents=True)
        (work / "scripts").mkdir()
        (work / "scripts" / "package.py").write_text(
            PACKAGER_SOURCE.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (work / "README.md").write_text("# synthetic tree\n", encoding="utf-8")

        cfg = work / "config"
        cfg.mkdir()
        (cfg / "ai.example.json").write_text('{"mode": "offline"}\n', encoding="utf-8")
        (cfg / "credentials.json").write_text(
            json.dumps({"openai": {"api_key": f"sk-{SENTINEL}"}}), encoding="utf-8"
        )
        (cfg / "session.json").write_text(
            json.dumps({"token": f"session-{SENTINEL}"}), encoding="utf-8"
        )

        (work / ".env").write_text(f"OPENAI_API_KEY=sk-{SENTINEL}\n", encoding="utf-8")
        (work / ".env.production").write_text(f"ANTHROPIC_API_KEY=sk-ant-{SENTINEL}\n", encoding="utf-8")

        plug = work / "plugins"
        plug.mkdir()
        (plug / "private_plugin.py").write_text(
            f'API_KEY = "{SENTINEL}"  # somebody else\'s private node\n', encoding="utf-8"
        )
        (work / "examples").mkdir()
        (work / "examples" / "keep.py").write_text("VALUE = 1\n", encoding="utf-8")

        mem = work / "memory"
        mem.mkdir()
        (mem / "memory.json").write_text(json.dumps({"notes": SENTINEL}), encoding="utf-8")

        out = work / "dist.zip"
        original_root = packager.ROOT
        try:
            packager.ROOT = work
            packager.build(out, name="synthetic", scan=True)
        finally:
            packager.ROOT = original_root
        return out

    def test_archive_exists_and_is_non_empty(self, built):
        assert built.exists()
        with zipfile.ZipFile(built) as zf:
            assert zf.namelist()

    def test_no_planted_secret_reaches_the_archive(self, built):
        """The single most important assertion in this file."""
        with zipfile.ZipFile(built) as zf:
            for info in zf.infolist():
                if info.file_size > 512 * 1024:
                    continue
                try:
                    text = zf.read(info).decode("utf-8")
                except UnicodeDecodeError:
                    continue
                assert SENTINEL not in text, (
                    f"{info.filename} carries the planted secret -- the archive would "
                    "be public and the sentinel is proof"
                )

    def test_state_paths_are_absent_but_source_survives(self, built):
        with zipfile.ZipFile(built) as zf:
            # Compare full relative paths, not basenames: a leak nested deeper
            # ("a/config/credentials.json") must not hide behind a same-named
            # legitimate file elsewhere in the tree.
            names = {n.split("/", 1)[-1] for n in zf.namelist()}
        for forbidden in (
            "credentials.json",
            "session.json",
            ".env",
            ".env.production",
            "plugins/private_plugin.py",
            "memory/memory.json",
        ):
            assert forbidden not in names, f"{forbidden} must not be in the archive"
        # A tree of nothing but exclusions is not a successful test.
        assert "examples/keep.py" in names
        assert "config/ai.example.json" in names


class TestPostBuildScanCatchesARegression:
    """The guard must actually fire, or it is decoration."""

    @pytest.fixture
    def leaky_archive(self, scratch):
        """A zip that violates the rules on purpose."""
        path = scratch / "leaky.zip"
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("synthetic/README.md", "hi\n")
            zf.writestr("synthetic/config/credentials.json", '{"k": "v"}')
            zf.writestr("synthetic/.env", "TOKEN=abc\n")
            zf.writestr("synthetic/certs/server.pem", "-----BEGIN PRIVATE KEY-----\n")
            zf.writestr(
                "synthetic/nodes/llm.py",
                f'API_KEY = "{SENTINEL}"\n',
            )
        return path

    def test_scan_reports_every_violation(self, packager, leaky_archive):
        problems = packager.scan_archive(leaky_archive, root_name="synthetic")
        joined = " | ".join(problems)
        assert "config/credentials.json" in joined
        assert ".env" in joined
        assert "server.pem" in joined
        # The inline-credential pattern must fire on a node source file.
        assert "nodes/llm.py" in joined

    def test_clean_archive_scans_clean(self, scratch, packager):
        good = scratch / "good.zip"
        with zipfile.ZipFile(good, "w") as zf:
            zf.writestr("synthetic/README.md", "# clean\n")
            zf.writestr("synthetic/config/ai.example.json", '{"mode": "offline"}')
        assert packager.scan_archive(good, root_name="synthetic") == []

    def test_build_refuses_and_deletes_a_leaky_tree(self, scratch, packager, monkeypatch):
        """If should_skip is bypassed, scan_archive must still stop the build."""
        work = scratch / "work"
        (work / "scripts").mkdir(parents=True)
        (work / "scripts" / "package.py").write_text(
            Path(packager.__file__).read_text(encoding="utf-8"), encoding="utf-8"
        )
        leak = work / "notes.txt"
        leak.write_text(f'token = "{SENTINEL}"\n', encoding="utf-8")

        out = work / "out.zip"
        monkeypatch.setattr(packager, "ROOT", work)
        # Neutralise the path rule so only the content scan can catch it.
        monkeypatch.setattr(packager, "should_skip", lambda rel: False)

        with pytest.raises(SystemExit) as excinfo:
            packager.build(out, name="synthetic", scan=True)
        assert "REFUSING TO PUBLISH" in str(excinfo.value)
        assert not out.exists(), "a leaky archive must not survive on disk"


class TestDocumentationOfTheRule:
    """The rule is a security boundary; its intent has to stay readable."""

    def test_package_docstring_states_the_allow_list_rule(self, packager):
        source = Path(packager.__file__).read_text(encoding="utf-8")
        assert "positive" in source and "allow-list" in source

    def test_allowlist_covers_the_documented_template_files(self, packager):
        """Whatever config/ ships must also be an example, never a live file."""
        for rel in sorted(packager.CONFIG_ALLOWLIST):
            assert rel.startswith("config/")
            assert "example" in rel or rel.endswith(".gitkeep")

    def test_gitignore_and_packager_agree_on_credentials(self):
        """Two independent mechanisms must both protect the credential file.

        ``.gitignore`` protects the repo; the packager protects the archive.
        They are different filesystems with different escape routes, so one
        cannot stand in for the other -- but they must not disagree.
        """
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        assert "config/credentials.json" in text
        assert "config/session.json" in text


class TestScannersAreTrackedAsACategory:
    """A scanner must spell out the secret it looks for -- and then trip on itself.

    This is not hypothetical: adding a private-key pattern to
    ``scripts/quality_gate.py`` made the *archive* scan reject the release,
    because ``scripts/package.py`` correctly spotted a credential shape in a
    shipped source file.  Three scanners, three near-identical incidents.  So the
    exempt set is asserted as a *category* -- any file that greps for a secret
    must be listed -- rather than left to be rediscovered one broken build at a
    time.
    """

    #: Files whose job is to search source text for credential shapes.
    SCANNER_FILES = (
        "scripts/package.py",
        "scripts/license_report.py",
        "scripts/quality_gate.py",
    )

    def test_every_scanner_is_exempt_from_the_content_scan(self, packager):
        for rel in self.SCANNER_FILES:
            assert rel in packager.SECRET_SCAN_ALLOWLIST, (
                f"{rel} greps for credential shapes and must therefore be exempt "
                "from the content scan, or the release cannot be packaged"
            )

    def test_every_scanner_is_exempt_from_the_gate_scan(self):
        """Same category, second scanner: ``quality_gate.py``'s own stage.

        Adding the private-key pattern to the gate made the *gate* fail on
        itself.  Both scanners walk the same tree with the same shapes, so both
        exemption sets have to name every scanner -- checked here against the
        gate's own constant so the two lists cannot drift apart.
        """
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "qg_v073", ROOT / "scripts" / "quality_gate.py"
        )
        gate = importlib.util.module_from_spec(spec)
        # dataclasses needs the module registered before exec, not after.
        sys.modules["qg_v073"] = gate
        try:
            spec.loader.exec_module(gate)
        finally:
            sys.modules.pop("qg_v073", None)
        for rel in self.SCANNER_FILES:
            assert rel in gate._SCAN_SELF_EXEMPT, (
                f"{rel} is a scanner but is missing from quality_gate's "
                "_SCAN_SELF_EXEMPT -- the gate will fail on its own source"
            )

    def test_the_exemption_is_per_file_never_a_directory(self, packager):
        """A directory rule would wave through a real key stored beside it.

        The failure this guards against is an entry like ``"scripts/"`` or
        ``"config/"``: it looks like one entry, silently exempts everything
        beneath it, and a real ``config/credentials.json`` walks straight out.
        Every entry must name a single file -- no entry may be a directory
        prefix of another.
        """
        entries = sorted(packager.SECRET_SCAN_ALLOWLIST)
        for rel in entries:
            assert not rel.endswith("/"), f"{rel} is a directory rule -- too broad"
        for shorter in entries:
            for longer in entries:
                assert not longer.startswith(shorter + "/"), (
                    f"{shorter} implicitly exempts {longer} through prefix matching"
                )

    def test_the_whole_repository_scans_clean(self, packager, real_archive):
        """Scan the real tree, not a synthetic one.

        The synthetic fixtures in this file cannot catch a scanner tripping over
        a *real* source file -- which is exactly how the ``quality_gate.py``
        incident shipped.  This is the check that would have caught it: run the
        shipped patterns over every file the packager would actually publish.
        """
        problems = packager.scan_archive(real_archive, root_name="tree")
        assert problems == [], (
            "the real tree no longer scans clean: " + " | ".join(problems)
        )
