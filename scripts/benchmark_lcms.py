#!/usr/bin/env python
"""Known-answer benchmark for the unknown-compound identification workflow.

The v0.7.1 task specification requires that *at least one end-to-end workflow has
a benchmark with known answers* (任务书 §五 / 任务 I).  This script exercises the
flagship workflow node ``UnknownCompoundIdentificationNode`` over the curated
offline library ``databases.local_library`` (24 compounds whose identity,
formula and monoisotopic mass are known).

Two reference libraries are evaluated so the numbers cannot be inflated by
comparing a model against itself:

``synthetic``
    The reference spectra of every candidate are produced by the platform's own
    forward models (:mod:`models.spectra`).  This is a **closed-loop** check: it
    verifies that the search/ranking pipeline reproduces a known answer, and
    doubles as a determinism test.

``curated``
    The reference entries carry the *project-authored* diagnostic fragments / IR
    bands / UV maxima shipped with ``databases.local_library``, while the observed
    "unknown" is still a forward prediction.  Molecular identity (formula, SMILES,
    monoisotopic mass) is real and checked against PubChem values; the spectral
    values are **hand-written illustrative numbers, not extracted from a licensed
    experimental spectral database**.

    This is therefore a *cross-source* check only in the narrow sense that the
    reference values were not produced by the same forward models.  It is **not**
    validation against real instrument data, and the numbers below must never be
    quoted as a real-world identification accuracy (spec task P0-06).

For each library the metric suite is reported per evidence channel (MS only,
IR only, NMR only, UV only) and for the full multimodal fusion:

=========================  ====================================================
metric                     meaning
=========================  ====================================================
Top-1 accuracy             the correct structure is ranked first
Top-3 / Top-5 accuracy     the correct structure is within the first K
MRR                        mean reciprocal rank of the correct structure
=========================  ====================================================

Negative controls (independent of the reference library):

* **discrimination** - the correct candidate must score higher against its own
  evidence than against a rotated (mismatched) evidence set;
* **determinism** - two independent runs yield byte-identical rankings;
* **open-set** - an analyte absent from the library (vanillin) must not be
  matched as confidently as a genuine library member.

Usage
-----
    python scripts/benchmark_lcms.py                  # run and print the table
    python scripts/benchmark_lcms.py --json out.json  # also dump raw metrics
    python scripts/benchmark_lcms.py --quiet          # only the PASS/FAIL line
    python scripts/benchmark_lcms.py --strict         # non-zero exit on failure

No network access is required; every value comes from the internal engines.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from databases.local_library import COMPOUND_LIBRARY  # noqa: E402
from models.spectra import predict_ir, predict_ms, predict_nmr, predict_uvvis  # noqa: E402
import nodes.question.identification as _identification  # noqa: E402
from nodes.question.identification import UnknownCompoundIdentificationNode  # noqa: E402
from workflow_engine.objects import Spectrum, Table  # noqa: E402

_ADDUCT = "[M+H]+"

#: analyte deliberately absent from the library, used as an open-set control
OUT_OF_LIBRARY = {"name": "vanillin", "smiles": "COc1cc(C=O)ccc1O", "formula": "C8H8O3"}

#: candidate search window during benchmarking (unchanged across configs so the
#: only variable is the evidence channel set)
_MASS_TOLERANCE_PPM = 15.0

#: Data provenance of this benchmark (spec task P0-06).
#:
#: The spec forbids presenting a synthetic benchmark as real-data validation.
#: Rather than trusting a paragraph of prose to carry that caveat, the claim and
#: its evidence travel together in the machine-readable output, so a downstream
#: report cannot quote the numbers without the caveat.
PROVENANCE: Dict[str, Any] = {
    "benchmark_kind": "synthetic",
    "benchmark_title": "Identification known-answer benchmark (synthetic only)",
    "script": "scripts/benchmark_lcms.py",
    "dataset_version": "chemml-lcms-synthetic-2026.1",
    "real_instrument_data": False,
    "real_data_validation": "not_performed",
    "real_data_validation_note": (
        "No licensed experimental spectral dataset is bundled with this release. "
        "See docs/V07_2_REAL_DATA_VALIDATION_PLAN.md; real-data accuracy is UNVERIFIED."
    ),
    "libraries": {
        "synthetic": {
            "origin": "generated",
            "generator": "models.spectra forward models (predict_ms/predict_ir/predict_nmr/predict_uvvis)",
            "independent_of_model": False,
            "note": "closed-loop: reference spectra come from the same forward models the "
                    "node scores against, so this measures ranking correctness and determinism, "
                    "not real-world accuracy",
        },
        "curated": {
            "origin": "hand-authored",
            "generator": "databases.local_library diagnostic values maintained in this repository",
            "independent_of_model": True,
            "note": "cross-source only in the sense that reference values were NOT produced by "
                    "the same forward models; they are project-authored illustrative values, "
                    "NOT extracted from a licensed experimental spectral database. Molecular "
                    "identity (formula/SMILES/monoisotopic mass) is checked against PubChem.",
        },
    },
    "analyte_source": "databases.local_library.COMPOUND_LIBRARY (24 entries)",
    "adduct": _ADDUCT,
    "mass_tolerance_ppm": _MASS_TOLERANCE_PPM,
    "forbidden_claims": [
        "不得引用为真实仪器数据上的鉴定准确率",
        "不得引用为 LC-MS/MS 平台的整体准确率",
        "不得与外部文献报告的准确率直接比较",
    ],
    "permitted_claims": [
        "在合成数据上，排名管线能复现已知答案（closed-loop）",
        "参考值不来自同一正向模型时（cross-source）排名仍然稳定",
        "两次运行结果完全一致（确定性）",
        "库外分析物的置信度显著低于库内化合物（开放集行为）",
    ],
}

#: acceptance thresholds for the primary (closed-loop, multimodal) metrics plus
#: the negative controls.  Values are set a little below what is measured at
#: release so the gate catches real regressions without being brittle.
THRESHOLDS: Dict[str, float] = {
    "synthetic.multimodal.top1": 0.90,
    "synthetic.multimodal.top3": 1.00,
    "synthetic.multimodal.mrr": 0.95,
    "synthetic.ms_only.top1": 0.90,
    "curated.multimodal.top1": 0.75,
    "curated.multimodal.top3": 0.90,
    "discrimination.rate": 0.80,
    "discrimination.separation": 0.05,
}


# --------------------------------------------------------------------------- #
# Deterministic prediction cache
# --------------------------------------------------------------------------- #
#: The node scores every candidate with the same forward models the synthetic
#: library is built from.  Those models are pure functions of their arguments, so
#: we memoise them; each distinct spectrum is generated exactly once per process.
#: This keeps the benchmark honest (no sampling shortcuts) while cutting the
#: runtime from minutes to seconds.
@lru_cache(maxsize=None)
def _cached_ms(smiles: str, noise: float) -> Spectrum:
    return predict_ms(smiles, adduct=_ADDUCT, noise=noise)


@lru_cache(maxsize=None)
def _cached_ir(smiles: str, noise: float) -> Spectrum:
    return predict_ir(smiles, noise=noise)


@lru_cache(maxsize=None)
def _cached_nmr(smiles: str, nucleus: str, points: int) -> Spectrum:
    return predict_nmr(smiles, nucleus=nucleus, points=points)


@lru_cache(maxsize=None)
def _cached_uvvis(smiles: str, noise: float) -> Spectrum:
    return predict_uvvis(smiles, noise=noise)


def _install_prediction_cache() -> None:
    """Route the identification node's NMR calls through the memo cache."""
    _identification.predict_nmr = (
        lambda candidate, nucleus="1H", points=4096: _cached_nmr(candidate, nucleus, int(points))
    )


# --------------------------------------------------------------------------- #
# Reference libraries
# --------------------------------------------------------------------------- #
def _ms_fragments(smiles: str) -> Tuple[List[float], float]:
    """Return (fragment m/z list, precursor m/z) from the forward MS model."""
    spectrum = _cached_ms(smiles, 0.004)
    precursor = float(spectrum.precursor_mz or 0.0)
    fragments = sorted(
        float(peak.x)
        for peak in spectrum.peaks
        if abs(float(peak.x) - precursor) > 0.05
    )
    return fragments, precursor


def _strong_bands(spectrum: Spectrum, limit: int = 6) -> List[float]:
    """Return the positions of the ``limit`` strongest peaks of ``spectrum``."""
    ranked = sorted(
        spectrum.peaks,
        key=lambda peak: float(peak.intensity or peak.y),
        reverse=True,
    )[:limit]
    return sorted(float(peak.x) for peak in ranked)


def _join(values: Sequence[float]) -> str:
    return ";".join(f"{value:.4f}" for value in values)


_LIBRARY_COLUMNS = ["name", "smiles", "formula", "mass", "fragments", "ir_bands", "uv_max", "family"]


def build_reference_library(kind: str) -> Table:
    """Build a reference table from either forward models or curated values."""
    records: List[Dict[str, Any]] = []
    for entry in COMPOUND_LIBRARY:
        if kind == "synthetic":
            fragments, _precursor = _ms_fragments(entry.smiles)
            ir_bands = _strong_bands(_cached_ir(entry.smiles, 0.004))
            uv_max = _strong_bands(_cached_uvvis(entry.smiles, 0.002), limit=2)
        elif kind == "curated":
            fragments = list(entry.fragments)
            ir_bands = list(entry.ir_bands)
            uv_max = list(entry.uv_max)
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown reference library kind {kind!r}")
        records.append(
            {
                "name": entry.name,
                "smiles": entry.smiles,
                "formula": entry.formula,
                "mass": entry.mass,
                "fragments": _join(fragments),
                "ir_bands": _join(ir_bands),
                "uv_max": _join(uv_max),
                "family": entry.family,
            }
        )
    rows = [[record[column] for column in _LIBRARY_COLUMNS] for record in records]
    return Table(
        name=f"{kind} reference library",
        columns=_LIBRARY_COLUMNS,
        rows=rows,
    )


# --------------------------------------------------------------------------- #
# Observed spectra (the "unknown")
# --------------------------------------------------------------------------- #
def observed_spectra(smiles: str) -> Dict[str, Spectrum]:
    """Generate the observed evidence streams for ``smiles`` (noisy)."""
    return {
        "ms": _cached_ms(smiles, 0.004),
        "ir": _cached_ir(smiles, 0.004),
        "nmr": _cached_nmr(smiles, "1H", 4096),
        "uvvis": _cached_uvvis(smiles, 0.002),
    }


def run_node(
    spectra: Dict[str, Spectrum],
    library: Table,
    channels: Sequence[str],
) -> List[Dict[str, Any]]:
    """Execute the identification node and return the full ranked candidate list."""
    inputs: Dict[str, Any] = {"candidates": library}
    for channel in channels:
        if spectra.get(channel) is not None:
            inputs[channel] = spectra[channel]
    node = UnknownCompoundIdentificationNode(
        node_id="benchmark",
        params={
            "adduct": _ADDUCT,
            "mass_tolerance_ppm": _MASS_TOLERANCE_PPM,
            "top_k": len(COMPOUND_LIBRARY),
            "use_ai": False,
            "language": "en",
        },
    )
    outputs = node.execute(inputs, None)
    return list(outputs["text"].data.get("candidates", []))


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def _rank_of(ranked: Sequence[Dict[str, Any]], true_smiles: str) -> Optional[int]:
    for index, item in enumerate(ranked):
        if str(item.get("smiles", "")) == true_smiles:
            return index + 1
    return None


def _confidence_of(ranked: Sequence[Dict[str, Any]], smiles: str) -> float:
    for item in ranked:
        if str(item.get("smiles", "")) == smiles:
            return float(item.get("confidence", 0.0))
    return 0.0


def _aggregate(ranks: Sequence[Optional[int]]) -> Dict[str, float]:
    total = len(ranks) or 1
    top1 = sum(1 for rank in ranks if rank == 1)
    top3 = sum(1 for rank in ranks if rank is not None and rank <= 3)
    top5 = sum(1 for rank in ranks if rank is not None and rank <= 5)
    mrr = statistics.fmean(1.0 / rank if rank else 0.0 for rank in ranks)
    return {
        "cases": len(ranks),
        "top1": round(top1 / total, 4),
        "top3": round(top3 / total, 4),
        "top5": round(top5 / total, 4),
        "mrr": round(mrr, 4),
    }


def _evaluate(kind: str, config_name: str, channels: Sequence[str], library: Table) -> Dict[str, Any]:
    """Run one configuration over every library compound and collect metrics."""
    ranks: List[Optional[int]] = []
    matched_conf: List[float] = []
    per_case: List[Dict[str, Any]] = []
    for entry in COMPOUND_LIBRARY:
        ranked = run_node(observed_spectra(entry.smiles), library, channels)
        rank = _rank_of(ranked, entry.smiles)
        ranks.append(rank)
        confidence = _confidence_of(ranked, entry.smiles)
        matched_conf.append(confidence)
        per_case.append(
            {
                "compound": entry.name,
                "smiles": entry.smiles,
                "rank": rank if rank is not None else -1,
                "top1_smiles": ranked[0]["smiles"] if ranked else "",
                "confidence": round(confidence, 6),
            }
        )
    metrics = _aggregate(ranks)
    metrics.update(
        {
            "library": kind,
            "config": config_name,
            "channels": list(channels),
            "mean_confidence": round(statistics.fmean(matched_conf), 6),
            "per_case": per_case,
        }
    )
    return metrics


def _discrimination(library: Table, channels: Sequence[str]) -> Dict[str, float]:
    """Matched vs. mismatched evidence separation (a real negative control).

    For each case the correct candidate is scored twice: once against its own
    spectra and once against the spectra of the next compound in the library.
    Correct identification must yield a strictly higher confidence.
    """
    wins = 0
    matched: List[float] = []
    mismatched: List[float] = []
    for index, entry in enumerate(COMPOUND_LIBRARY):
        other = COMPOUND_LIBRARY[(index + 1) % len(COMPOUND_LIBRARY)]
        matched_conf = _confidence_of(
            run_node(observed_spectra(entry.smiles), library, channels), entry.smiles
        )
        mismatched_conf = _confidence_of(
            run_node(observed_spectra(other.smiles), library, channels), entry.smiles
        )
        matched.append(matched_conf)
        mismatched.append(mismatched_conf)
        if matched_conf > mismatched_conf:
            wins += 1
    total = len(COMPOUND_LIBRARY)
    return {
        "rate": round(wins / total, 4),
        "matched_mean": round(statistics.fmean(matched), 6),
        "mismatched_mean": round(statistics.fmean(mismatched), 6),
        "separation": round(statistics.fmean(matched) - statistics.fmean(mismatched), 6),
    }


def _determinism(library: Table, channels: Sequence[str]) -> Dict[str, Any]:
    """Two independent runs must produce byte-identical rankings."""
    first = [tuple(item["smiles"] for item in run_node(observed_spectra(e.smiles), library, channels))
             for e in COMPOUND_LIBRARY]
    second = [tuple(item["smiles"] for item in run_node(observed_spectra(e.smiles), library, channels))
              for e in COMPOUND_LIBRARY]
    return {"identical": first == second, "cases": len(first)}


def _open_set(library: Table, channels: Sequence[str]) -> Dict[str, float]:
    """An out-of-library analyte must not be matched as confidently."""
    ranked = run_node(observed_spectra(OUT_OF_LIBRARY["smiles"]), library, channels)
    return {
        "analyte": OUT_OF_LIBRARY["name"],
        "top1_confidence": round(float(ranked[0]["confidence"]), 6) if ranked else 0.0,
        "top1_compound": ranked[0]["name"] if ranked else "",
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def _print_case_table(metrics: Dict[str, Any], show_all: bool) -> None:
    print(f"\n  {metrics['library']}::{metrics['config']}  (channels: {', '.join(metrics['channels'])})")
    print(f"  {'compound':<26} {'rank':>5}  {'confidence':>10}  top-1 candidate")
    print("  " + "-" * 74)
    cases = metrics["per_case"] if show_all else [c for c in metrics["per_case"] if c["rank"] != 1]
    if not cases:
        cases = metrics["per_case"][:3]
        print("  (all cases ranked first - showing a sample)")
    for case in cases:
        rank = case["rank"] if case["rank"] > 0 else "-"
        print(
            f"  {case['compound']:<26} {str(rank):>5}  {case['confidence']:>10.4f}  "
            f"{case['top1_smiles']}"
        )


def _check_thresholds(summary: Dict[str, Any]) -> List[Tuple[str, bool, str]]:
    def metric(key: str) -> float:
        kind, config, field = key.split(".")
        return float(summary["metrics"][kind][config][field])

    disc = summary["discrimination"]
    checks: List[Tuple[str, bool, str]] = []
    labels = {
        "synthetic.multimodal.top1": "closed-loop multimodal Top-1",
        "synthetic.multimodal.top3": "closed-loop multimodal Top-3",
        "synthetic.multimodal.mrr": "closed-loop multimodal MRR",
        "synthetic.ms_only.top1": "closed-loop MS-only Top-1",
        "curated.multimodal.top1": "cross-source multimodal Top-1",
        "curated.multimodal.top3": "cross-source multimodal Top-3",
    }
    for key, threshold in THRESHOLDS.items():
        if key in labels:
            value = metric(key)
            checks.append(
                (f"{labels[key]} >= {threshold:.2f}", value >= threshold, f"measured {value:.3f}")
            )
    checks.append(
        (
            f"discrimination rate >= {THRESHOLDS['discrimination.rate']:.2f}",
            disc["rate"] >= THRESHOLDS["discrimination.rate"],
            f"measured {disc['rate']:.3f}",
        )
    )
    checks.append(
        (
            f"confidence separation >= {THRESHOLDS['discrimination.separation']:.3f}",
            disc["separation"] >= THRESHOLDS["discrimination.separation"],
            f"measured {disc['separation']:.3f}",
        )
    )
    checks.append(
        (
            "deterministic (two runs identical)",
            bool(summary["determinism"]["identical"]),
            "identical" if summary["determinism"]["identical"] else "MISMATCH",
        )
    )
    closed_loop_conf = summary["metrics"]["synthetic"]["multimodal"]["mean_confidence"]
    checks.append(
        (
            "open-set confidence below closed-loop",
            summary["open_set"]["top1_confidence"] < closed_loop_conf,
            f"{summary['open_set']['top1_confidence']:.3f} < {closed_loop_conf:.3f}",
        )
    )
    return checks


_CONFIGS = (
    ("ms_only", ("ms",)),
    ("ir_only", ("ir",)),
    ("nmr_only", ("nmr",)),
    ("uv_only", ("uvvis",)),
    ("multimodal", ("ms", "ir", "nmr", "uvvis")),
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=str, default="", help="write raw metrics here")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict")
    parser.add_argument("--all-cases", action="store_true", help="print every per-case row")
    parser.add_argument("--strict", action="store_true", help="exit 1 when a threshold fails")
    args = parser.parse_args(argv)

    started = time.time()
    _install_prediction_cache()

    libraries = {kind: build_reference_library(kind) for kind in ("synthetic", "curated")}
    if not args.quiet:
        print(
            "=" * 78
            + "\nSYNTHETIC BENCHMARK — 合成数据基准，不是真实仪器验证\n"
            + "  本基准的全部参考谱与观测谱均由平台内部正向模型生成或为仓库内手写值。\n"
            + "  不得将其引用为真实 LC-MS/MS 数据上的鉴定准确率。\n"
            + "  真实数据验证状态：NOT PERFORMED（见 docs/V07_2_REAL_DATA_VALIDATION_PLAN.md）\n"
            + "=" * 78
        )
        print(f"dataset: {PROVENANCE['dataset_version']}  "
              f"library: {len(COMPOUND_LIBRARY)} compounds, adduct {_ADDUCT}, "
              f"tolerance {_MASS_TOLERANCE_PPM:.0f} ppm")

    metrics: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for kind, library in libraries.items():
        metrics[kind] = {}
        for config_name, channels in _CONFIGS:
            metrics[kind][config_name] = _evaluate(kind, config_name, channels, library)
            if not args.quiet and config_name == "multimodal":
                _print_case_table(metrics[kind][config_name], args.all_cases)

    synthetic_library = libraries["synthetic"]
    full_channels = ("ms", "ir", "nmr", "uvvis")
    discrimination = _discrimination(synthetic_library, full_channels)
    determinism = _determinism(synthetic_library, full_channels)
    open_set = _open_set(synthetic_library, full_channels)

    summary: Dict[str, Any] = {
        "generated_by": "scripts/benchmark_lcms.py",
        "provenance": PROVENANCE,
        "adduct": _ADDUCT,
        "mass_tolerance_ppm": _MASS_TOLERANCE_PPM,
        "library_size": len(COMPOUND_LIBRARY),
        "elapsed_s": round(time.time() - started, 2),
        "metrics": {
            kind: {name: {k: v for k, v in cfg.items() if k != "per_case"} for name, cfg in configs.items()}
            for kind, configs in metrics.items()
        },
        "metrics_detail": metrics,
        "discrimination": discrimination,
        "determinism": determinism,
        "open_set": open_set,
        "thresholds": THRESHOLDS,
    }

    checks = _check_thresholds(summary)
    summary["checks"] = [{"name": name, "ok": ok, "detail": detail} for name, ok, detail in checks]
    summary["ok"] = all(ok for _n, ok, _d in checks)

    if not args.quiet:
        for kind in ("synthetic", "curated"):
            label = "generated by this platform's forward models" if kind == "synthetic" else (
                "hand-authored project values (identity verified vs PubChem)"
            )
            print(f"\nmetrics  [{kind} reference library — {label}]")
            print(f"  {'config':<12} {'Top-1':>7} {'Top-3':>7} {'Top-5':>7} {'MRR':>7} {'mean conf':>10}")
            for config_name, _channels in _CONFIGS:
                cfg = metrics[kind][config_name]
                print(
                    f"  {config_name:<12} {cfg['top1']:>7.3f} {cfg['top3']:>7.3f} "
                    f"{cfg['top5']:>7.3f} {cfg['mrr']:>7.3f} {cfg['mean_confidence']:>10.3f}"
                )
        print("\nnegative controls")
        print(
            f"  discrimination rate   {discrimination['rate']:.3f}  "
            f"(matched {discrimination['matched_mean']:.3f} vs "
            f"mismatched {discrimination['mismatched_mean']:.3f})"
        )
        print(f"  determinism           {'identical' if determinism['identical'] else 'MISMATCH'}")
        print(
            f"  open-set ({open_set['analyte']}) confidence {open_set['top1_confidence']:.3f} "
            f"vs closed-loop {metrics['synthetic']['multimodal']['mean_confidence']:.3f}"
        )
        print("\nchecks  (regression floors — NOT performance claims; each is set below the")
        print("         measured value so the gate catches regressions without being brittle)")
        for name, ok, detail in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {name}  ({detail})")

    if args.json:
        path = Path(args.json)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        if not args.quiet:
            print(f"\nraw metrics -> {path}")

    print(
        f"\n[{'PASS' if summary['ok'] else 'FAIL'}] identification known-answer benchmark "
        f"({len(COMPOUND_LIBRARY)} cases x 2 reference libraries, {summary['elapsed_s']}s)"
    )
    if args.strict and not summary["ok"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
