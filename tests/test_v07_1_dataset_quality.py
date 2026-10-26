"""v0.7.1 dataset metadata governance tests (task G / spec §P1-07, §G.2-G.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_layer.quality import (
    FAMILY_DATA_TYPES,
    check,
    metadata_files,
    quality_report,
)

DATASETS = Path(__file__).resolve().parents[1] / "datasets"


def _write(root: Path, rel: str, payload) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (dict, list)):
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        path.write_bytes(payload)
    return path


class TestShippedDatasets:
    def test_all_shipped_metadata_is_consistent(self):
        report = quality_report(DATASETS)
        assert report["ok"] is True, report["problems"]
        assert report["datasets"] >= 8

    def test_family_matches_directory_for_every_record(self):
        for meta in metadata_files(DATASETS):
            data = json.loads(meta.read_text(encoding="utf-8"))
            family = meta.relative_to(DATASETS).parts[0]
            assert data["family"] == family, meta
            assert data["data_type"] in FAMILY_DATA_TYPES[family], meta

    def test_no_mass_spectrometry_directory_mismatch(self):
        # The shimadzu FT-IR sample was relocated to spectroscopy/ (task G.2).
        # v0.7.2 later added a *real* mass_spectrometry/ dataset (the mzML scan),
        # so the directory itself is legitimate again -- what must never happen
        # is a non-MS payload (e.g. the .spc FT-IR file) sitting inside it.
        assert (DATASETS / "spectroscopy" / "shimadzu_spc" / "sample_01.spc").is_file()
        ms_dir = DATASETS / "mass_spectrometry"
        if ms_dir.exists():
            payloads = [
                path
                for path in ms_dir.rglob("*")
                if path.is_file() and not path.name.endswith(".metadata.json")
            ]
            assert payloads, "mass_spectrometry/ exists but ships no payload"
            for path in payloads:
                assert path.suffix.lower() in {".mzml", ".mzmlg", ".msp", ".mgf", ".txt"}, path
            for meta in metadata_files(ms_dir):
                data = json.loads(meta.read_text(encoding="utf-8"))
                assert data["data_type"] in FAMILY_DATA_TYPES["mass_spectrometry"], meta

    def test_every_record_has_source_license_and_checksums(self):
        for meta in metadata_files(DATASETS):
            data = json.loads(meta.read_text(encoding="utf-8"))
            assert data["source"]["kind"]
            assert data["license"]
            assert data["files"], f"{meta} lists no payload files"
            for entry in data["files"]:
                assert len(entry["sha256"]) == 64


class TestDetectors:
    def _base(self, root: Path, data_type="IRSpectrum", family="spectroscopy"):
        meta = {
            "schema_version": "1.0",
            "name": "t",
            "family": family,
            "data_type": data_type,
            "format": "XY",
            "license": "CC0",
            "source": {"kind": "synthetic"},
            "files": [],
        }
        return meta

    def test_family_directory_mismatch_flagged(self, tmp_path):
        meta = self._base(tmp_path, family="nmr")  # dir will be spectroscopy
        meta["files"] = [{"path": "spectroscopy/x/x.xy", "bytes": 3, "sha256": "0" * 64}]
        _write(tmp_path, "spectroscopy/x/x.xy", b"abc")
        _write(tmp_path, "spectroscopy/x/x.metadata.json", meta)
        ok, problems = check(tmp_path)
        assert not ok
        assert any("does not match directory" in p["issue"] for p in problems)

    def test_data_type_not_allowed_for_family(self, tmp_path):
        meta = self._base(tmp_path, data_type="MassSpectrum", family="spectroscopy")
        _write(tmp_path, "spectroscopy/y/y.xy", b"abc")
        _write(tmp_path, "spectroscopy/y/y.metadata.json", meta)
        ok, problems = check(tmp_path)
        assert not ok
        assert any("not allowed for family" in p["issue"] for p in problems)

    def test_checksum_drift_detected(self, tmp_path):
        meta = self._base(tmp_path)
        _write(tmp_path, "spectroscopy/z/z.xy", b"abc")
        meta["files"] = [{"path": "spectroscopy/z/z.xy", "bytes": 3, "sha256": "f" * 64}]
        _write(tmp_path, "spectroscopy/z/z.metadata.json", meta)
        ok, problems = check(tmp_path)
        assert not ok
        assert any("checksum mismatch" in p["issue"] for p in problems)

    def test_duplicate_content_detected(self, tmp_path):
        for name in ("a", "b"):
            _write(tmp_path, f"spectroscopy/{name}/s.xy", b"same-bytes")
        for name in ("a", "b"):
            from data_layer.quality import sha256_file

            digest = sha256_file(tmp_path / f"spectroscopy/{name}/s.xy")
            meta = self._base(tmp_path)
            meta["files"] = [
                {"path": f"spectroscopy/{name}/s.xy", "bytes": 10, "sha256": digest}
            ]
            _write(tmp_path, f"spectroscopy/{name}/s.metadata.json", meta)
        ok, problems = check(tmp_path)
        assert not ok
        assert any("duplicate content" in p["issue"] for p in problems)

    def test_missing_units_flagged_for_spectra(self, tmp_path):
        meta = self._base(tmp_path)
        _write(tmp_path, "spectroscopy/w/w.xy", b"abc")
        _write(tmp_path, "spectroscopy/w/w.metadata.json", meta)
        ok, problems = check(tmp_path)
        assert not ok
        assert any("missing x_unit/y_unit" in p["issue"] for p in problems)


class TestApi:
    def test_quality_endpoint(self):
        from fastapi.testclient import TestClient

        from backend.app import create_app

        with TestClient(create_app()) as client:
            body = client.get("/api/data/quality").json()
        assert body["ok"] is True, body["problems"]
        assert body["datasets"] >= 8


class TestChecksumsDoNotDependOnTheCheckout:
    """A checksum must answer "is this the same data?", not "on a machine like mine".

    Git's ``core.autocrlf`` rewrites LF to CRLF on checkout, so the same
    commit gives a Windows working tree a 6 823-byte ``caffeine_ms.xy`` and a
    Linux checkout a 6 420-byte one.  The shipped metadata had recorded the
    Windows bytes, so the dataset-quality stage failed on every Linux runner
    for data that was never modified -- and passed only on the machine that
    had generated it.

    The fix is to measure the bytes the *repository* stores, which every
    machine agrees on.
    """

    def test_the_shipped_datasets_pass_on_any_checkout(self):
        """The real dataset tree must validate as shipped."""
        report = quality_report(DATASETS)
        assert report["ok"] is True, report["problems"]

    def test_a_tracked_dataset_is_hashed_from_the_repository(self):
        """The digest must be the repository's, not the working tree's."""
        import hashlib
        import subprocess

        from data_layer.quality import sha256_file

        target = DATASETS / "demo" / "caffeine_ms.xy"
        if not target.is_file():
            pytest.skip("demo dataset not present")

        committed = subprocess.run(
            ["git", "cat-file", "-p", "HEAD:datasets/demo/caffeine_ms.xy"],
            cwd=str(DATASETS.parents[1]),
            capture_output=True,
            timeout=30,
        )
        if committed.returncode != 0:
            pytest.skip("not a git checkout")
        assert sha256_file(target) == hashlib.sha256(committed.stdout).hexdigest()

    def test_an_untracked_dataset_falls_back_to_the_bytes_on_disk(self, tmp_path):
        """A dataset outside the repository has no other definition."""
        import hashlib

        from data_layer.quality import sha256_file

        payload = b"line one\nline two\n"
        target = tmp_path / "loose.xy"
        target.write_bytes(payload)
        assert sha256_file(target) == hashlib.sha256(payload).hexdigest()
