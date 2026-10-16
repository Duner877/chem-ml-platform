"""Task deliverables for *Recover the subsurface structure from a seismic line,
starting from a one-dimensional trend*.

The task asks for three files.  This module writes them and, more importantly,
computes the two quantities that decide whether the submission is worth
anything, so the run reports them instead of leaving the user to find out:

``velocity_model.npy``
    The recovered ``(n_depth, n_lateral)`` velocity section in m/s, clipped to
    the task's own ``[1500, 4500]`` range.

``wavelet.npy``
    The **estimated** source signature, normalised to unit peak.  The task
    supplies none and states it is not zero-phase, so this is recovered by
    least squares rather than assumed to be a Ricker.

``run_summary.json``
    Method, engine provenance, misfit before and after, the held-out
    validation, and the task's own lateral-correlation score computed against
    the truth **when the caller supplies one**.

Why the honest reporting matters here: the score removes the horizontal mean
at every depth, so a model that only fixes the depth trend scores zero, and a
model that fits the shots it was given while getting worse on held-out shots
scores zero outright.  A summary that reported "misfit reduced 50%" while the
lateral correlation stayed negative would be worse than no summary at all.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from simulations.fwi import (
    V_MAX,
    V_MIN,
    FWIResult,
    Survey,
    lateral_correlation,
)

__all__ = [
    "SubmissionPaths",
    "lateral_correlation",
    "score_model",
    "write_submission",
]

VELOCITY_FILE = "velocity_model.npy"
WAVELET_FILE = "wavelet.npy"
SUMMARY_FILE = "run_summary.json"


@dataclass(frozen=True)
class SubmissionPaths:
    """The three files, with their resolved locations."""

    directory: Path
    velocity: Path
    wavelet: Path
    summary: Path

    def as_dict(self) -> Dict[str, str]:
        return {
            "directory": str(self.directory),
            "velocity_model": str(self.velocity),
            "wavelet": str(self.wavelet),
            "run_summary": str(self.summary),
        }

    def exists(self) -> Dict[str, bool]:
        return {
            "velocity_model": self.velocity.is_file(),
            "wavelet": self.wavelet.is_file(),
            "run_summary": self.summary.is_file(),
        }


def score_model(
    velocity: np.ndarray,
    truth: Optional[np.ndarray] = None,
    start: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """The task's own score, computed only where the inputs allow.

    ``lateral_correlation`` is the metric that matters: it removes the
    horizontal mean at each depth before correlating, so depth-trend-only
    models score zero no matter how good they look in absolute terms.  The
    starting model is reported alongside it, because "0.32" means something very
    different against a baseline of 0.0 than against a baseline of 0.30.
    """
    out: Dict[str, Any] = {
        "lateral_correlation": None,
        "start_lateral_correlation": None,
        "improvement": None,
        "velocity_min": float(np.min(velocity)),
        "velocity_max": float(np.max(velocity)),
        "velocity_mean": float(np.mean(velocity)),
        "velocity_shape": [int(velocity.shape[0]), int(velocity.shape[1])],
        "in_task_range": bool(
            float(np.min(velocity)) >= V_MIN and float(np.max(velocity)) <= V_MAX
        ),
    }
    if truth is not None:
        truth = np.asarray(truth, dtype=float)
        out["lateral_correlation"] = lateral_correlation(velocity, truth)
        out["rmse_vs_truth"] = float(np.sqrt(np.mean((velocity - truth) ** 2)))
        if start is not None:
            base = lateral_correlation(np.asarray(start, dtype=float), truth)
            out["start_lateral_correlation"] = base
            out["start_rmse_vs_truth"] = float(
                np.sqrt(np.mean((np.asarray(start, dtype=float) - truth) ** 2))
            )
            out["improvement"] = out["lateral_correlation"] - base
            out["beats_start"] = bool(out["lateral_correlation"] > base)
        else:
            out["start_lateral_correlation"] = None
            out["start_rmse_vs_truth"] = None
            out["improvement"] = None
            out["beats_start"] = None
    else:
        # Explicit null rather than a missing key.  In JSON these read
        # differently -- an absent field invites the question "was this
        # forgotten?", while a null says "there was nothing to measure against".
        for key in (
            "lateral_correlation",
            "rmse_vs_truth",
            "start_lateral_correlation",
            "start_rmse_vs_truth",
            "improvement",
            "beats_start",
        ):
            out[key] = None
    return out


def _finite_or_none(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    return value


def write_submission(
    directory: Any,
    result: FWIResult,
    survey: Survey,
    truth: Optional[np.ndarray] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> SubmissionPaths:
    """Write the three deliverables and return their resolved paths.

    Parameters
    ----------
    directory:
        Output directory; created if absent.
    result:
        Whatever :func:`simulations.fwi.run_fwi` returned.
    survey:
        The acquisition, used to record the geometry and the held-out split.
    truth:
        The ground-truth section, **if the caller has it**.  A synthetic
        benchmark does; a real survey does not, and passing ``None`` simply
        omits the score rather than inventing one.
    extra:
        Additional JSON-serialisable entries merged into the summary.

    Notes
    -----
    ``velocity_model.npy`` is written from a clipped copy so the file on disk
    is exactly what the scorer will read -- a summary quoting an in-range
    statistic next to an out-of-range array would be a trap.
    """
    out_dir = Path(directory)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = SubmissionPaths(
        directory=out_dir,
        velocity=out_dir / VELOCITY_FILE,
        wavelet=out_dir / WAVELET_FILE,
        summary=out_dir / SUMMARY_FILE,
    )

    model = np.clip(np.asarray(result.velocity, dtype=float), V_MIN, V_MAX)
    np.save(paths.velocity, model)

    signature = np.asarray(result.wavelet, dtype=float)
    peak = float(np.max(np.abs(signature))) if signature.size else 0.0
    if peak > 0.0:
        signature = signature / peak
    np.save(paths.wavelet, signature)

    scoring = score_model(model, truth=truth, start=survey.velocity)
    summary: Dict[str, Any] = {
        "engine": result.engine,
        "method": result.method,
        "source_signature_estimation": result.source_estimation,
        "signature_peak_normalised": bool(peak > 0.0),
        "iterations": int(result.n_iterations),
        "wall_time_s": round(float(result.wall_time_s), 3),
        "misfit": {
            "initial": _finite_or_none(result.initial_misfit),
            "final": _finite_or_none(result.final_misfit),
            "per_stage": [_finite_or_none(v) for v in result.stage_misfits],
            "reduction_pct": (
                round(
                    100.0 * (1.0 - result.final_misfit / result.initial_misfit), 4
                )
                if result.initial_misfit > 0.0
                else None
            ),
            "definition": (
                "band-limited L2 over the last frequency stage's band, on the "
                "monitoring shots; both modelled and observed traces are "
                "filtered with the same zero-phase window"
            ),
        },
        "validation": {
            "shots_used": list(result.shots_used),
            "held_out_shots": list(result.held_out_shots),
            "held_out_initial_misfit": _finite_or_none(result.held_out_initial_misfit),
            "held_out_final_misfit": _finite_or_none(result.held_out_final_misfit),
            "held_out_improved": (
                bool(result.held_out_final_misfit < result.held_out_initial_misfit)
                if result.held_out_initial_misfit is not None
                else None
            ),
            "note": (
                "held-out shots are excluded from the gradient entirely; if none "
                "were declared the fields are null rather than filled in with the "
                "fitted shots"
            ),
        },
        "survey": {
            "n_shots": int(survey.n_shots),
            "n_receivers": int(survey.n_receivers),
            "nt": int(survey.nt),
            "dt": float(survey.dt),
            "dx": float(survey.dx),
            "shape": [int(v) for v in survey.shape],
        },
        "score": scoring,
        "truth_available": truth is not None,
    }
    if extra:
        summary.update(extra)

    # sort_keys keeps the file byte-stable across runs with identical inputs,
    # which is what makes the reproducibility check meaningful.
    paths.summary.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return paths


def load_submission(
    directory: Any,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    """Read back what :func:`write_submission` wrote.

    Round-tripping is the only way to be sure the files on disk are loadable by
    the scorer -- a ``.npy`` written from a non-contiguous view or a summary
    holding a numpy scalar both fail silently until the grader opens them.
    """
    out_dir = Path(directory)
    model = np.load(out_dir / VELOCITY_FILE)
    signature = np.load(out_dir / WAVELET_FILE)
    summary = json.loads((out_dir / SUMMARY_FILE).read_text(encoding="utf-8"))
    if model.ndim != 2:
        raise ValueError(f"{VELOCITY_FILE} must be 2-D, got shape {model.shape}")
    if signature.ndim != 1:
        raise ValueError(f"{WAVELET_FILE} must be 1-D, got shape {signature.shape}")
    return model, signature, summary


def synthetic_benchmark(
    n_depth: int = 60,
    n_lateral: int = 120,
    dx: float = 15.0,
    dt: float = 0.0015,
    nt: int = 1500,
    n_shots: int = 8,
    n_receivers: int = 60,
    wavelet_f0: float = 12.0,
    wavelet_delay: float = 0.02,
    truth: Optional[np.ndarray] = None,
    held_out: Sequence[int] = (),
) -> Tuple[Survey, np.ndarray, np.ndarray]:
    """A reproducible faulted section, its records, and the starting trend.

    Provided so the whole pipeline -- survey, forward model, inversion, scoring
    -- can be exercised locally without any external data.  The truth is a
    synthetic benchmark, not a claim about real geology.

    The wavelet keeps its delay: the task states the record begins before the
    source has finished acting, so a zero-phase pulse would understate the
    difficulty of recovering the signature.
    """
    from simulations.fwi import forward_model

    z = np.arange(n_depth)[:, None]
    x = np.arange(n_lateral)[None, :]
    if truth is None:
        base = 1900.0 + 1.6 * z
        interface_1 = 12 + 0.06 * x
        interface_2 = 26 - 0.05 * x
        model = np.where(z > interface_2, base + 700.0, base)
        model = np.where(z > interface_1, model, base - 150.0)
        fault = int(round(n_lateral * 0.6))
        model[:, fault:] -= 240.0
        cx, cz = n_lateral * 0.79, n_depth * 0.30
        lens = ((x - cx) ** 2 / (n_lateral * 0.10) ** 2 + (z - cz) ** 2 / (n_depth * 0.083) ** 2) < 1.0
        truth = np.clip(np.where(lens, model - 320.0, model), V_MIN, V_MAX)

    trend = 1850.0 + 1.15 * z + 0.010 * z ** 2
    start = np.repeat(trend, n_lateral, axis=1)

    shot_rc = np.stack(
        [
            np.zeros(n_shots, dtype=int),
            np.linspace(4, n_lateral - 5, n_shots).astype(int),
        ],
        axis=1,
    )
    rec_rc = np.stack(
        [
            np.zeros(n_receivers, dtype=int),
            np.linspace(2, n_lateral - 3, n_receivers).astype(int),
        ],
        axis=1,
    )

    t = np.arange(nt) * dt
    a = np.pi * wavelet_f0 * (t - wavelet_delay)
    wavelet = (1.0 - 2.0 * a ** 2) * np.exp(-a ** 2)
    peak = float(np.max(np.abs(wavelet)))
    wavelet = wavelet / peak if peak > 0 else wavelet

    records = forward_model(truth, wavelet, shot_rc, rec_rc, dt, dx, nt).modelled
    survey = Survey(
        velocity=start,
        records=records,
        shot_rc=shot_rc,
        rec_rc=rec_rc,
        dt=dt,
        dx=dx,
        nt=nt,
        held_out=held_out,
    )
    return survey, truth, wavelet