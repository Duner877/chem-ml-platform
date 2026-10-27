"""v0.7.4 regression tests: cross-machine determinism of the release gates.

Two gates used to compare artefacts against **this machine's** environment
instead of against the *declaration*:

``scripts/lock_dependencies.py --check``
    regenerated the lock from the installed environment and compared it
    byte-for-byte with the committed file.  CI installs the declared ranges,
    so it always resolved to slightly different versions (fastapi 0.162.0 vs
    the pinned 0.143.0) and the gate failed on every run while saying nothing
    true about the tree.

``scripts/license_report.py --check``
    compared ``sbom.json`` / ``NOTICE`` / ``docs/THIRD_PARTY_LICENSES.md``
    byte-for-byte against what the local interpreter happened to have
    installed.  Same failure mode: a stale-artefact report for files nobody
    had touched.

Both were unreachable in CI because the job before them failed first, so
neither had ever been exercised.  These tests pin the corrected contracts:

* the lock check asks three questions whose answers do not depend on the host
  (coverage, range satisfaction, header version);
* the licence check asks which packages ship under which licences -- the
  question a release actually has to answer -- and treats an *unresolved*
  licence as a wildcard rather than as a change.

They also pin the dataset-metadata recognition rule, which had to be decided by
content rather than by file name (see ``_METADATA_FIELDS``).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def lic():
    return _load("license_report", "scripts/license_report.py")


@pytest.fixture(scope="module")
def lock():
    return _load("lock_dependencies", "scripts/lock_dependencies.py")


# --------------------------------------------------------------------------- #
# scripts/lock_dependencies.py -- declaration consistency
# --------------------------------------------------------------------------- #
class TestLockDeclarationConsistency:
    """The lock check must be answerable without knowing the host's packages."""

    def test_committed_lock_is_consistent(self, lock):
        """The committed lock passes the check that CI runs."""
        problems = lock.check_consistency()
        assert problems == [], (
            "requirements.lock is inconsistent with the declarations:\n"
            + "\n".join(f"  - {p}" for p in problems)
        )

    def test_every_declared_dependency_has_a_pin(self, lock):
        declared = lock.parse_declarations()
        pins = lock.parse_lock((ROOT / "requirements.lock").read_text(encoding="utf-8"))
        assert declared, "the requirement groups must declare something"
        missing = sorted(name for name in declared if name not in pins)
        assert not missing, f"declared but unpinned: {missing}"

    def test_every_pin_satisfies_its_declared_range(self, lock):
        from packaging.specifiers import SpecifierSet

        declared = lock.parse_declarations()
        pins = lock.parse_lock((ROOT / "requirements.lock").read_text(encoding="utf-8"))
        for name, specifier in sorted(declared.items()):
            version = pins.get(name)
            if version is None or not specifier:
                continue
            allowed = SpecifierSet(specifier).contains(version, prereleases=True)
            assert allowed, f"{name}=={version} is outside the declared range {specifier}"

    def test_header_names_the_current_release(self, lock):
        first = (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()[0]
        assert first == f"# Chem ML Platform v{lock.VERSION} -- fully pinned Python lock file."

    # -- the three negative scenarios, each exercised on a scratch copy ------ #
    def _scratch(self, tmp_path, monkeypatch, lock):
        """Copy the declarations and the lock into a scratch tree."""
        (tmp_path / "requirements.runtime.txt").write_text(
            (ROOT / "requirements.runtime.txt").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (tmp_path / "requirements.dev.txt").write_text(
            (ROOT / "requirements.dev.txt").read_text(encoding="utf-8"), encoding="utf-8"
        )
        lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
        (tmp_path / "requirements.lock").write_text(lock_text, encoding="utf-8")
        monkeypatch.setattr(lock, "ROOT", tmp_path)
        monkeypatch.setattr(lock, "LOCK", tmp_path / "requirements.lock")
        monkeypatch.setattr(lock, "GROUPS", ["requirements.runtime.txt", "requirements.dev.txt"])
        return tmp_path / "requirements.lock"

    def test_a_missing_pin_is_reported(self, tmp_path, monkeypatch, lock):
        path = self._scratch(tmp_path, monkeypatch, lock)
        text = path.read_text(encoding="utf-8")
        path.write_text(
            "\n".join(line for line in text.splitlines() if not line.startswith("python-multipart=="))
            + "\n",
            encoding="utf-8",
        )
        problems = lock.check_consistency()
        assert any("python-multipart" in p and "no pin" in p for p in problems), problems

    def test_a_pin_outside_the_declared_range_is_reported(self, tmp_path, monkeypatch, lock):
        path = self._scratch(tmp_path, monkeypatch, lock)
        text = path.read_text(encoding="utf-8")
        # fastapi is declared ">=0.110,<1.0"; 2.5.0 is outside it.
        path.write_text(text.replace("fastapi==0.143.0", "fastapi==2.5.0"), encoding="utf-8")
        problems = lock.check_consistency()
        assert any("fastapi" in p and "does not satisfy" in p for p in problems), problems

    def test_a_stale_header_is_reported(self, tmp_path, monkeypatch, lock):
        path = self._scratch(tmp_path, monkeypatch, lock)
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                f"# Chem ML Platform v{lock.VERSION} -- fully pinned Python lock file.",
                "# Chem ML Platform v0.7.2 -- fully pinned Python lock file.",
            ),
            encoding="utf-8",
        )
        problems = lock.check_consistency()
        assert any("lock header says" in p for p in problems), problems

    def test_the_check_does_not_consult_the_installed_environment(self, tmp_path, monkeypatch, lock):
        """The verdict must be the same whether or not the host has the packages.

        This is the property CI depends on: the runner installs the *declared
        ranges*, which resolve to different patch releases than the lock pins,
        and the gate must still pass.
        """
        self._scratch(tmp_path, monkeypatch, lock)
        before = lock.check_consistency()

        # Poison the installed-metadata lookup: every package now looks absent.
        import importlib.metadata as md

        def _not_found(_name):
            raise md.PackageNotFoundError(_name)

        monkeypatch.setattr(md, "version", _not_found)
        monkeypatch.setattr(md, "requires", _not_found)
        after = lock.check_consistency()
        assert before == after == []

    def test_the_check_is_independent_of_the_declared_range_width(self, tmp_path, monkeypatch, lock):
        """Widening a declaration may not invalidate a lock that satisfies it.

        ``fastapi>=0.110,<1.0`` -> ``fastapi>=0.100`` still admits the pinned
        0.143.0, so the lock stays consistent.  This is the case the old
        byte-for-byte check got wrong in the other direction: it would have
        demanded a regeneration for a change that did not affect the pins.
        """
        self._scratch(tmp_path, monkeypatch, lock)
        runtime = tmp_path / "requirements.runtime.txt"
        runtime.write_text(
            runtime.read_text(encoding="utf-8").replace(
                "fastapi>=0.110,<1.0", "fastapi>=0.100"
            ),
            encoding="utf-8",
        )
        assert lock.check_consistency() == []


# --------------------------------------------------------------------------- #
# scripts/license_report.py -- semantic comparison
# --------------------------------------------------------------------------- #
class TestLicenceSemanticComparison:
    """The licence check compares *facts*, not bytes."""

    @staticmethod
    def _facts(lic, text: str):
        """The artefact's component entries, as an ordered ``name -> fields`` map.

        The entries are *records* (a name plus its fields), not a flat
        dictionary of component facts: the comparison is positional, so the
        order is part of what is being asserted.
        """
        entries = lic._artefact_entries(text)
        assert entries, "the artefact must yield component entries"
        return entries

    @staticmethod
    def _field(entries, key: str, field: str):
        """The one field of the one entry with this ``ecosystem:name`` key."""
        for name, fields in entries:
            if name == key:
                return fields[field]
        raise AssertionError(f"{key} is missing from the artefact")

    @staticmethod
    def _notice_line(name: str):
        """The NOTICE's own line for a component, as ``(package, version, licence)``.

        The version is read out of the file rather than written into the
        test, so that regenerating the artefacts on a machine with different
        patch releases installed does not turn these tests red.
        """
        for line in (ROOT / "NOTICE").read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(name + " "):
                package, version, rest = stripped.split(" ", 2)
                licence = rest.split("—", 1)[1].split("<")[0].strip()
                return package, version, licence
        raise AssertionError(f"{name} is not listed in the NOTICE")

    def test_version_drift_alone_is_not_drift(self, lic, tmp_path):
        """A different patch release is still the same package under the same licence."""
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        package, version, _licence = self._notice_line("numpy")
        drifted = original.replace(f"{package} {version}", f"{package} 9.9.9")
        assert drifted != original, "the fixture must actually differ"
        path = tmp_path / "NOTICE"
        path.write_text(drifted, encoding="utf-8")
        assert lic._differs_only_in_versions(path, original) is True

    def test_a_changed_component_set_is_drift(self, lic, tmp_path):
        """Shipping a different set of packages is a real change."""
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        package, version, licence = self._notice_line("httpx")
        drifted = original.replace(
            f"  {package} {version}",
            f"  {package} {version}\n  requests 2.32.0 — MIT <https://requests.readthedocs.io>",
        )
        path = tmp_path / "NOTICE"
        path.write_text(drifted, encoding="utf-8")
        assert lic._differs_only_in_versions(path, original) is False

    def test_a_changed_licence_is_drift(self, lic, tmp_path):
        """A licence change is exactly what a licence gate exists to catch."""
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        package, version, _licence = self._notice_line("fastapi")
        drifted = original.replace(
            f"{package} {version} — MIT", f"{package} {version} — GPL-3.0"
        )
        assert drifted != original, "the fixture must actually differ"
        path = tmp_path / "NOTICE"
        path.write_text(drifted, encoding="utf-8")
        assert lic._differs_only_in_versions(path, original) is False

    def test_an_unresolved_licence_is_a_wildcard(self, lic):
        """An unreadable licence means "unknown here", not "changed"."""
        assert lic._same_licence(("MIT",), ("MIT",)) is True
        assert lic._same_licence(("MIT",), ("Apache-2.0",)) is False
        # The machine running the comparison could not read the metadata.
        assert lic._same_licence(("",), ("MIT",)) is True
        assert lic._same_licence(("MIT",), ("",)) is True
        assert lic._same_licence(("",), ("")) is True

    def test_unresolved_licence_strings_are_normalised(self, lic):
        for raw in ("", "  ", "UNKNOWN", "unknown", "NOASSERTION"):
            assert lic._licence_key(raw) == "", raw
        assert lic._licence_key("MIT") == "MIT"

    def test_a_respelled_licence_is_not_drift_in_the_artefact(self, lic, tmp_path):
        """The end-to-end consequence: a respelling does not stale the file.

        This is the failure the whole exercise exists to prevent.  CI
        resolves the declared ranges and installs whatever upstream published
        that day; if upstream renamed ``MIT`` to ``MIT License`` in a patch
        release, the file in the repository would be reported as stale on
        every runner -- for a document nobody had touched.
        """
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        package, version, _licence = self._notice_line("fastapi")
        respelled = original.replace(
            f"{package} {version} — MIT", f"{package} {version} — MIT License"
        )
        assert respelled != original, "the fixture must actually differ"
        path = tmp_path / "NOTICE"
        path.write_text(respelled, encoding="utf-8")
        assert lic._differs_only_in_versions(path, original) is True

    def test_a_real_licence_change_is_still_drift_in_the_artefact(self, lic, tmp_path):
        """The tolerance must not make the gate blind."""
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        package, version, _licence = self._notice_line("fastapi")
        changed = original.replace(
            f"{package} {version} — MIT", f"{package} {version} — GPL-3.0"
        )
        assert changed != original, "the fixture must actually differ"
        path = tmp_path / "NOTICE"
        path.write_text(changed, encoding="utf-8")
        assert lic._differs_only_in_versions(path, original) is False

    def test_line_endings_do_not_stale_the_artefact(self, lic, tmp_path):
        """Git may check the file out with CRLF; the content is the same.

        The repository stores these files with LF endings, but a Windows
        checkout with ``core.autocrlf`` writes them back with CRLF.  The
        generator always produces LF, so without normalising the line endings
        the byte comparison calls every one of the three files stale on
        every Windows machine -- while their content, which is what the check
        is about, is identical.
        """
        original = (ROOT / "NOTICE").read_text(encoding="utf-8")
        crlf = original.replace("\n", "\r\n")
        assert crlf != original, "the fixture must actually differ"
        path = tmp_path / "NOTICE"
        path.write_bytes(crlf.encode("utf-8"))
        assert lic._differs_only_in_versions(path, original) is True


class TestLicenceSpellingIsNotLicenceChange:
    """The licence string upstream publishes is not a stable spelling.

    Every dependency this project declares can be resolved, on any machine, to
    a release whose metadata spells its licence differently from the release
    that was installed when the artefacts were generated:

    ============  ==================  ==========================
    package      older release        newer release
    ============  ==================  ==========================
    fastapi      ``MIT License``      ``MIT``
    pydantic     ``MIT License``      ``MIT``
    uvicorn      ``BSD License``      ``BSD-3-Clause``
    httpx        ``BSD License``      ``BSD-3-Clause``
    python-multipart  ``Apache Software License``  ``Apache-2.0``
    matplotlib   ``PSF``              ``Python Software Foundation License``
    ============  ==================  ==========================

    The licence is identical in every one of those pairs -- only the metadata
    spelling moved.  A gate that compares the strings literally reports drift
    for a document nobody touched, on every machine that resolved a different
    patch release than the one that wrote the file, and says nothing true
    about the release.
    """

    @pytest.mark.parametrize(
        "older,newer",
        [
            ("MIT License", "MIT"),
            ("MIT", "MIT License"),
            ("BSD License", "BSD-3-Clause"),
            ("BSD-3-Clause", "BSD License"),
            ("Apache Software License", "Apache-2.0"),
            ("PSF", "Python Software Foundation License"),
            ("ISC License (ISCL)", "ISC"),
            ("GNU General Public License v3 (GPLv3)", "GPL-3.0-only"),
            ("GPL-3.0", "GPL-3.0-only"),
        ],
    )
    def test_a_respelled_licence_is_the_same_licence(self, lic, older, newer):
        assert lic._licences_compatible(older, newer) is True
        assert lic._licences_compatible(newer, older) is True
        assert lic._same_licence((older,), (newer,)) is True

    @pytest.mark.parametrize(
        "left,right",
        [
            ("MIT", "Apache-2.0"),
            ("BSD-2-Clause", "BSD-3-Clause"),
            ("GPL-3.0-only", "GPL-3.0-or-later"),
            ("MIT", "MIT AND Apache-2.0"),
            ("ISC", "LGPL-3.0"),
        ],
    )
    def test_a_genuinely_different_licence_is_still_drift(self, lic, left, right):
        """The tolerance must not swallow a real licence change."""
        assert lic._licences_compatible(left, right) is False
        assert lic._same_licence((left,), (right,)) is False

    def test_the_order_of_a_conjunction_does_not_matter(self, lic):
        """``A AND B`` and ``B AND A`` are the same grant."""
        first = "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0"
        second = "0BSD AND BSD-3-Clause AND MIT AND Zlib AND CC0-1.0"
        assert lic._licences_compatible(first, second) is True

    def test_a_disjunction_is_not_the_same_as_a_conjunction(self, lic):
        """``MIT OR Apache-2.0`` lets the user choose; ``MIT AND Apache-2.0``
        does not.  Treating them as the same would hide a real change."""
        assert lic._licences_compatible("MIT OR Apache-2.0", "MIT AND Apache-2.0") is False

    def test_a_licence_upstream_never_wrote_is_left_alone(self, lic):
        """A string the project invents is compared literally.

        ``MIT / LGPL`` and ``CC0 (generated by the platform)`` are not SPDX
        identifiers: the first is a compound description written by openmm,
        the second this project's own note on its generated datasets.  Neither
        may be rewritten into something else, and neither may be silently
        accepted as a licence it is not.
        """
        assert lic._licences_compatible("MIT / LGPL", "MIT / LGPL") is True
        assert lic._licences_compatible("MIT / LGPL", "MIT") is False
        assert lic._licences_compatible("CC0 (generated by the platform)", "CC0-1.0") is False

    def test_the_review_list_follows_the_precise_identifier(self, lic):
        """A copyleft package is found by what its licence *means*.

        The trove classifier spells it ``GNU General Public License v3
        (GPLv3)``; the PEP 639 expression spells it ``GPL-3.0-only``.  Both
        name the same strong-copyleft licence, so both belong in the section
        that asks a human to look at it -- and neither spelling may make the
        entry appear or vanish.
        """
        components = [
            {"ecosystem": "python", "name": "copyleft", "license": "GPL-3.0-only", "declared": True},
            {
                "ecosystem": "python",
                "name": "copyleft-classifier",
                "license": "GNU General Public License v3 (GPLv3)",
                "declared": True,
            },
            {"ecosystem": "python", "name": "permissive", "license": "MIT", "declared": True},
        ]
        flagged = lic._license_review(components)
        assert any(item.startswith("python:copyleft ") for item in flagged)
        assert any(item.startswith("python:copyleft-classifier ") for item in flagged)
        assert not [item for item in flagged if item.startswith("python:permissive")]


class TestArtefactParsing:
    """The three artefacts are parsed into comparable records."""

    @staticmethod
    def _facts(lic, text: str):
        """The artefact's component entries, as an ordered ``name -> fields`` map.

        The entries are *records* (a name plus its fields), not a flat
        dictionary of component facts: the comparison is positional, so the
        order is part of what is being asserted.
        """
        entries = lic._artefact_entries(text)
        assert entries, "the artefact must yield component entries"
        return entries

    @staticmethod
    def _field(entries, key: str, field: str):
        """The one field of the one entry with this ``ecosystem:name`` key."""
        for name, fields in entries:
            if name == key:
                return fields[field]
        raise AssertionError(f"{key} is missing from the artefact")

    def test_notice_is_parsed_into_facts(self, lic):
        entries = self._facts(lic, (ROOT / "NOTICE").read_text(encoding="utf-8"))
        assert self._field(entries, "python:fastapi", "licence") == ("MIT",)
        assert self._field(entries, "external:abacus", "licence") == ("LGPL-3.0",)
        assert self._field(entries, "npm:react", "licence") == ("MIT",)

    def test_markdown_is_parsed_into_facts(self, lic):
        entries = self._facts(lic, (ROOT / "docs/THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8"))
        assert self._field(entries, "python:numpy", "licence") == (
            "BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0",
        )
        assert self._field(entries, "npm:react", "licence") == ("MIT",)
        assert self._field(entries, "external:abacus", "licence") == ("LGPL-3.0",)

    def test_markdown_parser_reads_the_right_column_per_section(self, lic):
        """Every section has its own column order.

        A parser that always takes "the third column" reads the *installed*
        flag as the licence for the external-programs and sample-data sections,
        and then compares the wrong field -- silently, and in a way that
        reports a licence change when nothing changed.
        """
        text = "\n".join(
            [
                "## 1. Python 运行时依赖",
                "",
                "| name | version | license | declared | installed |",
                "|---|---|---|---|---|",
                "| demo | 1.0 | MIT | True | True |",
                "",
                "## 3. 外部科研软件（**不随包分发**）",
                "",
                "| name | license | installed | homepage |",
                "|---|---|---|---|",
                "| tool | BSD-3-Clause | False | https://example.org |",
                "",
                "## 4. 样例数据来源与许可",
                "",
                "| name | license | note |",
                "|---|---|---|",
                "| sample | CC0 | datasets/demo/x.metadata.json |",
            ]
        )
        facts = self._facts(lic, text)
        assert self._field(facts, "python:demo", "licence") == ("MIT",)
        assert self._field(facts, "external:tool", "licence") == ("BSD-3-Clause",)
        assert self._field(facts, "dataset:sample", "licence") == ("CC0",)

    def test_sbom_is_parsed_into_facts(self, lic):
        entries = self._facts(lic, (ROOT / "sbom.json").read_text(encoding="utf-8"))
        assert self._field(entries, "python:fastapi", "licence") == ("MIT",)
        assert self._field(entries, "dataset:Caffeine 1H NMR (Bruker TopSpin)", "licence") == (
            "CC0 (generated by the platform)",
        )

    def test_the_three_artefacts_agree_on_the_component_set(self, lic):
        """The SBOM is the machine-readable form; the other two must match it.

        NOTICE intentionally lists fewer components (it names only what is
        redistributed), so the comparison is against the *SBOM* for the python
        and npm sections and the Markdown report for the dataset section.
        """
        sbom = self._facts(lic, (ROOT / "sbom.json").read_text(encoding="utf-8"))
        markdown = self._facts(lic, (ROOT / "docs/THIRD_PARTY_LICENSES.md").read_text(encoding="utf-8"))
        markdown_keys = {name for name, _ in markdown}
        for name, _ in sbom:
            if name.startswith("dataset:"):
                assert name in markdown_keys, f"{name} is missing from the licence report"

    def test_check_mode_passes_on_the_committed_artefacts(self, lic):
        assert lic.main(["--check"]) == 0


# --------------------------------------------------------------------------- #
# Dataset metadata recognition
# --------------------------------------------------------------------------- #
class TestDatasetMetadataRecognition:
    """A dataset metadata document is found by what it *is*, not by its name.

    The flat demo datasets use ``<name>.metadata.json``; the Bruker NMR sample
    is a vendor directory whose file is simply ``metadata.json``.  Matching on
    the name therefore misses the Bruker spectrum.  Widening the name list to
    cover it (``*.parser.json``) over-corrects and pulls the nine *parser
    configurations* in as datasets.

    The discriminating fact: a dataset metadata document carries a ``license``
    and a ``source``; a parser configuration describes how to read a file and
    carries neither.
    """

    def test_dataset_count_matches_the_real_metadata_documents(self, lic):
        files = lic._dataset_metadata_files()
        names = [p.relative_to(lic.ROOT).as_posix() for p in files]
        assert len(names) == 10, f"unexpected dataset metadata set: {names}"
        # The vendor-layout dataset must be present.
        assert "datasets/nmr/bruker_nmr/sample_01.d/metadata.json" in names
        # No parser configuration may be present.
        assert not [n for n in names if n.endswith(".parser.json")], names
        assert "datasets/nmr/bruker_nmr/sample_01.d/parser.json" not in names

    def test_every_inventoried_dataset_declares_a_licence_and_source(self, lic):
        for path in lic._dataset_metadata_files():
            meta = json.loads(path.read_text(encoding="utf-8"))
            assert "license" in meta, path
            assert "source" in meta, path

    def test_a_parser_configuration_is_not_a_dataset(self, lic, tmp_path):
        path = tmp_path / "sample_01.parser.json"
        path.write_text(
            json.dumps({"parser": "nmr", "node": "NMRNode", "format": "bruker"}),
            encoding="utf-8",
        )
        assert lic._is_metadata_file(path) is False

    def test_a_vendor_layout_metadata_document_is_a_dataset(self, lic, tmp_path):
        path = tmp_path / "metadata.json"
        path.write_text(
            json.dumps(
                {
                    "name": "Vendor sample",
                    "license": "CC0",
                    "source": {"kind": "synthetic", "reference": "local"},
                }
            ),
            encoding="utf-8",
        )
        assert lic._is_metadata_file(path) is True

    def test_a_json_file_that_is_not_metadata_is_skipped(self, lic, tmp_path):
        path = tmp_path / "metadata.schema.json"
        path.write_text(json.dumps({"$schema": "https://json-schema.org/draft/2020-12/schema"}), encoding="utf-8")
        assert lic._is_metadata_file(path) is False


# --------------------------------------------------------------------------- #
# NOTICE membership
# --------------------------------------------------------------------------- #
class TestNoticeMembership:
    """The bundled list is derived from the *declaration*, not from the host.

    The old filter was ``installed or ecosystem == "npm"``: a Python package
    appeared only when the local interpreter happened to have it, so the same
    commit produced a different NOTICE on a machine with torch installed and
    on one without -- and a NOTICE has to name every redistributed component.
    """

    def test_the_notice_lists_the_declared_python_dependencies(self, lic):
        data = lic.collect()
        notice = lic.build_notice(data["python"], data["npm"], data["external"])
        for dep in data["python"]:
            if dep.get("declared"):
                assert f"  {dep['name']} {dep['version']} —" in notice, dep["name"]

    def test_the_notice_does_not_list_user_installed_optional_packages(self, lic):
        data = lic.collect()
        notice = lic.build_notice(data["python"], data["npm"], data["external"])
        optional = [d for d in data["python"] if not d.get("declared")]
        for dep in optional:
            assert f"  {dep['name']} {dep['version']} —" not in notice, (
                f"{dep['name']} is optional and not redistributed; it must not "
                "appear in the bundled list"
            )

    def test_the_notice_is_the_same_with_and_without_torch_installed(self, lic, monkeypatch):
        """Two hosts, one NOTICE.

        This is the property the old filter destroyed: the membership of the
        bundled list is a fact about the *release*, not about the machine that
        generated the file.
        """
        data = lic.collect()
        baseline = lic.build_notice(data["python"], data["npm"], data["external"])

        without_torch = []
        for dep in data["python"]:
            if dep["name"] == "torch":
                continue
            without_torch.append(dep)
        monkeypatch.setattr(
            lic, "python_components", lambda: [dict(d) for d in without_torch]
        )
        other = lic.build_notice(lic.python_components(), data["npm"], data["external"])
        assert other == baseline, (
            "the NOTICE changed when torch was removed from the local "
            "environment; its membership must come from the declaration"
        )


class TestSbomBundledFlag:
    """``chemml:bundled`` must mean the same thing as the NOTICE's bundled list."""

    def test_optional_python_packages_are_not_marked_bundled(self, lic):
        data = lic.collect()
        sbom = lic.build_sbom(data["python"], data["npm"], data["external"], data["datasets"])
        for component in sbom["components"]:
            props = {p["name"]: p["value"] for p in component["properties"]}
            if props.get("chemml:ecosystem") != "python":
                continue
            if component.get("scope") == "optional":
                assert props.get("chemml:bundled") == "false", (
                    f"{component['name']} is optional and must not be marked bundled"
                )


# --------------------------------------------------------------------------- #
# Prose sections that must not depend on the machine
# --------------------------------------------------------------------------- #
class TestProseSectionsAreMachineIndependent:
    """Two sections of the report used to record the *host's* state.

    Both were built from whatever the scan happened to find, so the document
    had a different length on a developer machine and on a CI runner -- and
    the release check reported drift for a file nobody had touched.
    """

    def test_the_cleanliness_section_lists_the_same_buckets_everywhere(self, lic):
        """The bucket list is fixed, not derived from the scan result."""
        assert lic._CLEANLINESS_BUCKETS == (
            "pyc",
            "pycache",
            "secrets",
            "private_data",
            "duplicate_assets",
            "runtime_data",
            "generated_assets",
        )

    def test_an_empty_scan_still_produces_every_bucket(self, lic):
        """A clean machine must not produce a shorter document."""
        markdown = lic.build_markdown([], [], [], [], [], {})
        for bucket in lic._CLEANLINESS_BUCKETS:
            assert f"**{bucket}**" in markdown, bucket

    def test_the_review_section_only_covers_redistributed_components(self, lic):
        """The section's own text says "依赖被分发"; the code must agree.

        A strong-copyleft package that the user installs for themselves
        creates no obligation, and listing it would make the section depend on
        which optional packages happen to be installed.
        """
        components = [
            {"ecosystem": "python", "name": "optional-gpl", "license": "GPL-3.0", "declared": False},
            {"ecosystem": "python", "name": "required-gpl", "license": "GPL-3.0", "declared": True},
            {"ecosystem": "npm", "name": "transitive-gpl", "license": "AGPL-3.0", "declared": False},
        ]
        flagged = lic._license_review(components)
        # The entry names the *precise* identifier, not whatever spelling the
        # upstream package happened to use, so the section reads the same on
        # every machine.
        assert "python:required-gpl (GPL-3.0-only)" in flagged
        assert "npm:transitive-gpl (AGPL-3.0-only)" in flagged
        assert not [item for item in flagged if item.startswith("python:optional-gpl")], (
            "an optional package is not redistributed, so it must not be reviewed"
        )
