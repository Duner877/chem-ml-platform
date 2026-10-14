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
        assert not (DATASETS / "mass_spectrometry").exists()
        assert (DATASETS / "spectroscopy" / "shimadzu_spc" / "sample_01.spc").is_file()

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
