"""v0.7.1 known-answer benchmark regression tests (task I).

These are the *software-test* layer of the scientific benchmark (任务书 §5.3,
任务 I.4): they run a fast subset of ``scripts/benchmark_lcms.py`` so a regression
in the identification pipeline is caught by the normal test suite.  The full
benchmark report is produced by the script itself.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def bench():
    """Import ``scripts/benchmark_lcms.py`` as a module."""
    spec = importlib.util.spec_from_file_location(
        "benchmark_lcms", ROOT / "scripts" / "benchmark_lcms.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._install_prediction_cache()
    return module


@pytest.fixture(scope="module")
def synthetic_library(bench):
    return bench.build_reference_library("synthetic")


#: a representative subset: aromatic, aliphatic, sugar, amino acid, alkaloid
SUBSET = ("caffeine", "aspirin", "ethanol", "benzene", "glucose", "L-tryptophan")


def _subset_entries(bench):
    by_name = {entry.name: entry for entry in bench.COMPOUND_LIBRARY}
    return [by_name[name] for name in SUBSET]


class TestBenchmarkPipeline:
    def test_reference_library_has_candidate_columns(self, synthetic_library):
        for column in ("name", "smiles", "formula", "mass", "fragments", "ir_bands", "uv_max"):
            assert column in synthetic_library.columns

    def test_closed_loop_multimodal_top1_is_exact(self, bench, synthetic_library):
        """On the closed-loop reference every known answer must rank first."""
        channels = ("ms", "ir", "nmr", "uvvis")
        for entry in _subset_entries(bench):
            ranked = bench.run_node(bench.observed_spectra(entry.smiles), synthetic_library, channels)
            assert bench._rank_of(ranked, entry.smiles) == 1, entry.name

    def test_ms_only_top1_is_exact(self, bench, synthetic_library):
        for entry in _subset_entries(bench):
            ranked = bench.run_node(bench.observed_spectra(entry.smiles), synthetic_library, ("ms",))
            assert bench._rank_of(ranked, entry.smiles) == 1, entry.name

    def test_ranking_is_deterministic(self, bench, synthetic_library):
        channels = ("ms", "ir", "nmr", "uvvis")
        entry = _subset_entries(bench)[0]
        first = [item["smiles"] for item in bench.run_node(bench.observed_spectra(entry.smiles), synthetic_library, channels)]
        second = [item["smiles"] for item in bench.run_node(bench.observed_spectra(entry.smiles), synthetic_library, channels)]
        assert first == second

    def test_matched_evidence_outranks_mismatched(self, bench, synthetic_library):
        """A rotated evidence set must not score the candidate as high."""
        channels = ("ms", "ir", "nmr", "uvvis")
        entries = _subset_entries(bench)
        for index, entry in enumerate(entries):
            other = entries[(index + 1) % len(entries)]
            matched = bench._confidence_of(
                bench.run_node(bench.observed_spectra(entry.smiles), synthetic_library, channels),
                entry.smiles,
            )
            mismatched = bench._confidence_of(
                bench.run_node(bench.observed_spectra(other.smiles), synthetic_library, channels),
                entry.smiles,
            )
            assert matched > mismatched, entry.name


class TestCandidateTableEvidence:
    """The ``candidates`` port documents an external reference library."""

    def test_table_spectral_lists_drive_the_ms_channel(self, bench, synthetic_library):
        from nodes.question.identification import UnknownCompoundIdentificationNode
        from databases.local_library import COMPOUND_LIBRARY

        entry = COMPOUND_LIBRARY[0]
        node = UnknownCompoundIdentificationNode(
            node_id="t",
            params={"adduct": "[M+H]+", "mass_tolerance_ppm": 15.0, "top_k": 5, "use_ai": False},
        )
        pool = node._candidate_pool({"candidates": synthetic_library}, None)
        record = next(item for item in pool if item["smiles"] == entry.smiles)
        # the table's serialised fragment list was parsed back into a numeric list
        assert record["fragments"], entry.name
        assert all(isinstance(value, float) for value in record["fragments"])

    def test_numeric_list_parser_handles_delimiters(self, bench):
        from nodes.question.identification import _numeric_list

        assert _numeric_list("1.0; 2.5, 3") == [1.0, 2.5, 3.0]
        assert _numeric_list([1, 2, 3]) == [1.0, 2.0, 3.0]
        assert _numeric_list("") == []
        assert _numeric_list(None) == []
