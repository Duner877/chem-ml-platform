"""Regression tests for the 0.7.3 seismic / FWI family.

Four things are locked here, each of which cost real debugging time and would
otherwise regress silently:

1. **The adjoint gradient's sign and shape.**  A wrong-signed gradient is
   non-zero, finite, and plausible -- it only shows up as the misfit going the
   wrong way.  The check is a descent profile along the gradient itself, because
   single-direction finite differences sit below the float64 noise floor of a
   misfit this small.
2. **The source-signature estimator.**  Not its correlation with the truth (that
   belongs to ``check_fwi.py``, which owns the synthetic ground truth), but the
   properties that make it safe to use unattended: it never returns something
   that ran off the end of its own window, and it says what it did.
3. **Held-out shots are genuinely held out.**  A shot listed as validation must
   not appear in the gradient, and the validation numbers must be comparable to
   each other (same signature, same band) or the comparison is meaningless.
4. **The three deliverables round-trip.**  ``.npy`` files that the scorer cannot
   load, or a summary quoting an in-range statistic next to an out-of-range
   array, are the two failure modes worth a test.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from chemml_version import VERSION
from nodes.loader import get_registry
from simulations.fwi import (
    V_MAX,
    V_MIN,
    FWIConfig,
    Survey,
    _adjoint_gradient,
    _apply_filter,
    _filter_bank,
    build_survey,
    estimate_wavelet,
    forward_model,
    lateral_correlation,
    run_fwi,
)
from simulations.fwi_submission import (
    load_submission,
    score_model,
    synthetic_benchmark,
    write_submission,
)

# A small but complete survey: the physics is the same at any size, and these
# tests are about contracts rather than inversion quality.
ND, NX = 30, 60
DX, DT, NT = 20.0, 0.002, 900
N_SHOTS, N_RECS = 6, 30
HELD_OUT = (1, 4)


def _small_survey() -> tuple[Survey, np.ndarray, np.ndarray]:
    survey, truth, wavelet = synthetic_benchmark(
        n_depth=ND,
        n_lateral=NX,
        dx=DX,
        dt=DT,
        nt=NT,
        n_shots=N_SHOTS,
        n_receivers=N_RECS,
        held_out=HELD_OUT,
    )
    return survey, truth, wavelet


# --------------------------------------------------------------------------- #
# gradient
# --------------------------------------------------------------------------- #
def test_adjoint_gradient_descends_along_its_own_direction():
    """The misfit must fall along +g and rise along -g.

    This is the check that catches a sign error.  An earlier version stepped
    0.05% of the mean velocity and compared the sign of a 0.4% change, which is
    indistinguishable from noise -- it "passed" while the gradient pointed
    uphill.  The profile below spans a decade of step sizes and has to turn over
    somewhere, which a wrong-signed gradient cannot do.
    """
    survey, _truth, wavelet = _small_survey()
    window, nfft = _filter_bank(NT, DT, ((6.0, 15.0, 4.0),))[(6.0, 15.0, 4.0)]
    grad = _adjoint_gradient(
        survey,
        survey.velocity,
        wavelet,
        (window, nfft),
        np.ones((ND, NX)),
        shots=survey.fit_shots,
    )
    assert np.all(np.isfinite(grad))
    assert float(np.max(np.abs(grad))) > 0.0

    energy = sum(
        float(np.sum(_apply_filter(survey.records[i], window, nfft) ** 2))
        for i in survey.fit_shots
    )

    def misfit(model: np.ndarray) -> float:
        # Both sides filtered.  Differencing a filtered model against *raw*
        # observations measures the derivative of a different objective than
        # the one being minimised, which is how a reversed adjoint gradient
        # stayed green for a whole release.
        mod = forward_model(
            model, wavelet, survey.shot_rc, survey.rec_rc, DT, DX, NT,
            band=(window, nfft),
        ).modelled
        return sum(
            float(
                np.sum(
                    (
                        _apply_filter(mod[i], window, nfft)
                        - _apply_filter(survey.records[i], window, nfft)
                    )
                    ** 2
                )
            )
            for i in survey.fit_shots
        ) / energy

    direction = grad / float(np.max(np.abs(grad)))
    mean_v = float(np.mean(survey.velocity))
    base = misfit(survey.velocity)
    values = [
        misfit(np.clip(survey.velocity - f * mean_v * direction, V_MIN, V_MAX))
        for f in (0.005, 0.01, 0.02, 0.05, 0.10, 0.20)
    ]
    # ``_adjoint_gradient`` returns dJ/dv, so *descending* means moving along
    # the negated direction.  A test that steps the other way would pass only
    # while the sign was wrong.
    assert min(values) < base * 0.995, f"no descent along -dJ/dv: {values}"
    # The profile has to come back up past its own minimum, which pins the
    # optimum rather than just confirming "smaller is better".
    assert values[-1] > min(values)
    assert misfit(np.clip(survey.velocity + 0.02 * mean_v * direction, V_MIN, V_MAX)) > base


def test_adjoint_gradient_is_finite_for_every_shot():
    survey, _truth, wavelet = _small_survey()
    window, nfft = _filter_bank(NT, DT, ((3.0, 8.0, 0.0),))[(3.0, 8.0, 0.0)]
    for ishot in range(survey.n_shots):
        grad = _adjoint_gradient(
            survey, survey.velocity, wavelet, (window, nfft),
            np.ones((ND, NX)), shots=[ishot],
        )
        assert np.all(np.isfinite(grad))


# --------------------------------------------------------------------------- #
# source signature
# --------------------------------------------------------------------------- #
def test_estimated_signature_does_not_run_off_its_window():
    survey, _truth, _wavelet = _small_survey()
    signature, method = estimate_wavelet(survey)
    if np.any(signature):
        support = int(np.count_nonzero(signature))
        peak = int(np.argmax(np.abs(signature)))
        assert peak < support // 2, (
            f"the filter's peak sat at sample {peak} of {support}: the signature "
            "ran off the end of its own window"
        )
        assert "degenerate" not in method
    else:
        # A refusal is an acceptable outcome, but it has to say so.
        assert "degenerate" in method


def test_signature_estimation_is_deterministic():
    survey, _truth, _wavelet = _small_survey()
    first, _ = estimate_wavelet(survey)
    second, _ = estimate_wavelet(survey)
    assert np.array_equal(first, second)


def test_supplying_an_all_zero_wavelet_is_refused_by_the_forward_model():
    survey, _truth, _wavelet = _small_survey()
    with pytest.raises(ValueError):
        forward_model(
            survey.velocity, np.zeros(NT), survey.shot_rc, survey.rec_rc, DT, DX, NT
        )


def test_forward_model_rejects_a_cfl_violation_with_numbers():
    survey, _truth, _wavelet = _small_survey()
    with pytest.raises(ValueError, match="CFL"):
        forward_model(
            survey.velocity, np.eye(1, NT, 0).ravel(), survey.shot_rc,
            survey.rec_rc, dt=0.05, dx=DX, nt=NT,
        )


# --------------------------------------------------------------------------- #
# held-out discipline
# --------------------------------------------------------------------------- #
def test_held_out_shots_are_excluded_from_the_gradient():
    survey, _truth, _wavelet = _small_survey()
    assert survey.held_out_shots == list(HELD_OUT)
    assert set(survey.fit_shots).isdisjoint(survey.held_out_shots)
    assert len(survey.fit_shots) + len(survey.held_out_shots) == survey.n_shots


def test_survey_rejects_an_out_of_range_held_out_shot():
    records = np.zeros((2, 4, 8))
    with pytest.raises(ValueError, match="held-out"):
        build_survey(
            records, np.full((4, 4), 2000.0),
            [[0, 0], [0, 3]], [[0, 1]] * 4, 0.001, 10.0, 8, held_out=(5,),
        )


def test_run_fwi_reports_which_shots_were_used():
    survey, _truth, _wavelet = _small_survey()
    result = run_fwi(
        survey,
        FWIConfig(
            frequency_schedule=((6.0, 15.0, 4.0),),
            iterations_per_stage=1,
            verbose=False,
        ),
    )
    assert result.shots_used == survey.fit_shots
    assert result.held_out_shots == list(HELD_OUT)
    assert result.held_out_initial_misfit is not None
    assert result.held_out_final_misfit is not None


def test_inversion_reduces_the_misfit():
    survey, _truth, _wavelet = _small_survey()
    result = run_fwi(
        survey,
        FWIConfig(
            frequency_schedule=((6.0, 15.0, 4.0),),
            iterations_per_stage=2,
            verbose=False,
        ),
    )
    assert result.final_misfit < result.initial_misfit
    assert float(result.velocity.min()) >= V_MIN
    assert float(result.velocity.max()) <= V_MAX


def test_starting_trend_scores_zero_on_the_tasks_own_metric():
    """The reason a depth-trend start is a hard problem, asserted rather than assumed.

    The task removes the horizontal mean at every depth before correlating, so a
    model that varies only with depth has nothing to contribute.  If this test
    ever fails, the metric has changed and every recorded score means something
    different.
    """
    survey, truth, _wavelet = _small_survey()
    assert abs(lateral_correlation(survey.velocity, truth)) < 1e-12
    assert lateral_correlation(truth, truth) == pytest.approx(1.0, abs=1e-9)


# --------------------------------------------------------------------------- #
# deliverables
# --------------------------------------------------------------------------- #
def test_submission_round_trips_through_disk(tmp_path: Path):
    survey, truth, _wavelet = _small_survey()
    result = run_fwi(
        survey,
        FWIConfig(
            frequency_schedule=((6.0, 15.0, 4.0),),
            iterations_per_stage=1,
            verbose=False,
        ),
    )
    paths = write_submission(tmp_path, result, survey, truth=truth)
    assert all(paths.exists().values())

    model, signature, summary = load_submission(tmp_path)
    assert model.ndim == 2
    assert signature.ndim == 1
    assert float(model.min()) >= V_MIN and float(model.max()) <= V_MAX
    # The array on disk must be the clipped one the scorer reads, not an
    # in-range statistic quoted next to an out-of-range model.
    assert np.allclose(model, np.clip(result.velocity, V_MIN, V_MAX))
    assert summary["truth_available"] is True
    assert summary["score"]["lateral_correlation"] is not None


def test_submission_omits_the_score_when_there_is_no_truth(tmp_path: Path):
    """A null score and a zero score are different claims."""
    survey, _truth, _wavelet = _small_survey()
    result = run_fwi(
        survey,
        FWIConfig(
            frequency_schedule=((6.0, 15.0, 4.0),),
            iterations_per_stage=1,
            verbose=False,
        ),
    )
    write_submission(tmp_path, result, survey, truth=None)
    _model, _signature, summary = load_submission(tmp_path)
    assert summary["truth_available"] is False
    assert summary["score"]["lateral_correlation"] is None
    assert summary["score"]["rmse_vs_truth"] is None


def test_submission_summary_is_byte_stable_for_identical_inputs(tmp_path: Path):
    survey, truth, _wavelet = _small_survey()
    result = run_fwi(
        survey,
        FWIConfig(
            frequency_schedule=((6.0, 15.0, 4.0),),
            iterations_per_stage=1,
            verbose=False,
        ),
    )
    first = write_submission(tmp_path / "a", result, survey, truth=truth)
    second = write_submission(tmp_path / "b", result, survey, truth=truth)
    assert (
        first.summary.read_text(encoding="utf-8")
        == second.summary.read_text(encoding="utf-8")
    )


def test_score_model_reports_the_baseline_alongside_the_score():
    survey, truth, _wavelet = _small_survey()
    better = np.clip(survey.velocity + 120.0, V_MIN, V_MAX)
    scores = score_model(better, truth=truth, start=survey.velocity)
    assert scores["start_lateral_correlation"] == pytest.approx(0.0, abs=1e-12)
    assert scores["lateral_correlation"] is not None
    assert scores["beats_start"] == (scores["lateral_correlation"] > 0.0)
    assert scores["in_task_range"] is True


def test_assembled_result_does_not_claim_a_misfit_history():
    """A result built by a downstream node must not report ``misfit 0.0``.

    Zero is a perfectly ordinary misfit value, so a placeholder is
    indistinguishable from a measurement once it has been through JSON.  The
    flag is what lets a consumer tell them apart.
    """
    from simulations.fwi import FWIResult

    empty = FWIResult(velocity=np.full((4, 4), 2000.0), wavelet=np.zeros(8))
    payload = empty.to_dict()
    assert payload["has_diagnostics"] is False
    assert payload["initial_misfit"] is None
    assert payload["final_misfit"] is None

    real = FWIResult(
        velocity=np.full((4, 4), 2000.0),
        wavelet=np.zeros(8),
        stage_misfits=[1.0e-9],
        n_iterations=3,
        initial_misfit=2.0e-9,
        final_misfit=1.0e-9,
    )
    payload = real.to_dict()
    assert payload["has_diagnostics"] is True
    assert payload["initial_misfit"] is not None
    assert payload["misfit_reduction_pct"] == pytest.approx(50.0, abs=0.01)


# --------------------------------------------------------------------------- #
# nodes and workflow
# --------------------------------------------------------------------------- #
def test_seismic_nodes_are_registered():
    registry = get_registry()
    registry.discover_package("nodes")
    types = set(registry.types())
    for name in (
        "SeismicSurveyNode",
        "SeismicForwardNode",
        "FWIInversionNode",
        "SeismicSubmissionNode",
    ):
        assert name in types


def test_survey_node_declares_a_truth_port_only_when_synthetic():
    registry = get_registry()
    registry.discover_package("nodes")
    node = registry.create("SeismicSurveyNode", params={"n_depth": 20, "n_lateral": 40,
                                                        "n_shots": 4, "n_receivers": 12,
                                                        "nt": 200})
    out = node.execute({})
    assert "truth" in out, "the synthetic benchmark should publish its truth"
    assert out["truth"].type == "Image"

    external = registry.create(
        "SeismicSurveyNode",
        params={"source": "external", "n_depth": 20, "n_lateral": 40},
    )
    survey, _t, _w = synthetic_benchmark(
        n_depth=20, n_lateral=40, dx=DX, dt=DT, nt=200, n_shots=4, n_receivers=12
    )
    out = external.execute({"survey": survey})
    assert "truth" not in out, "a real survey has no truth and must not pretend to"


def test_fwi_workflow_file_is_valid_json_with_the_expected_shape():
    root = Path(__file__).resolve().parents[1]
    path = root / "workflows" / "09_seismic_fwi.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    # The shipped workflow must declare the current platform version; see
    # the note in ``test_v07_3_hard_carbon.py`` for why this is not a
    # literal.
    assert data["version"] == VERSION
    types = {n["type"] for n in data["nodes"]}
    assert "FWIInversionNode" in types
    assert "SeismicSubmissionNode" in types
    # The submission node is only meaningful when the report and the signature
    # reach it; without those edges it writes a zero misfit and an all-zero
    # wavelet while looking like it succeeded.
    edges = {
        (e["source"], e["source_port"], e["target"], e["target_port"])
        for e in data["edges"]
    }
    assert ("invert", "report", "submit", "report") in edges
    assert ("invert", "wavelet", "submit", "wavelet") in edges

# --------------------------------------------------------------------------- #
# v0.7.3 audit P1-6: the forward node had no consumer, and truth was mandatory
# --------------------------------------------------------------------------- #
def test_the_forward_node_output_is_actually_consumed():
    """A node in the demo workflow whose every output dangles is a lie.

    ``SeismicForwardNode`` cost a full modelling run and made the user believe
    its gather fed the inversion, when nothing consumed any of its outputs.
    """
    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "workflows" / "09_seismic_fwi.json").read_text(encoding="utf-8")
    )
    consumed = {(e["source"], e["source_port"]) for e in data["edges"]}
    forward_outputs = {"gather", "green", "energy", "text"}
    used = {port for src, port in consumed if src == "forward"}
    assert used, "the forward node has no consumer at all in the demo workflow"
    assert used <= forward_outputs


def test_the_forward_qc_reaches_the_submission_summary():
    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "workflows" / "09_seismic_fwi.json").read_text(encoding="utf-8")
    )
    edges = {
        (e["source"], e["source_port"], e["target"], e["target_port"])
        for e in data["edges"]
    }
    assert ("forward", "energy", "submit", "forward_qc") in edges


def test_the_truth_port_is_optional_so_real_data_can_run():
    """Real survey data has no ground truth.

    While this port was mandatory, a real-data workflow could not even be
    validated -- which made a synthetic, truth-scored chain look like the only
    supported path.
    """
    from nodes.loader import get_registry

    spec = get_registry().get("SeismicSubmissionNode").spec()
    ports = {p["name"]: p for p in spec["inputs"]}
    assert ports["truth"].get("optional") is True
    assert ports["forward_qc"].get("optional") is True


def test_forward_qc_is_read_out_of_the_table_not_guessed():
    from nodes.instruments.seismic import _forward_qc_from_inputs
    from workflow_engine.objects import Table

    table = Table.from_records(
        [
            {"shot": 0, "gather_energy": 1.0e6},
            {"shot": 1, "gather_energy": 1.1e6},
            {"shot": 2, "gather_energy": 0.0},      # a dead trace
        ],
        name="qc",
        metadata={"cfl_dt_limit_s": 8e-4, "requested_dt_s": 4e-4, "cfl_margin": 2.0},
    )
    qc = _forward_qc_from_inputs({"forward_qc": table})
    assert qc["connected"] is True
    assert qc["shots"] == 3
    assert qc["cfl_admissible"] is True
    assert qc["dead_shots"] == 1, "a zero-energy shot must be surfaced, not averaged away"


def test_absent_forward_qc_is_reported_as_absent_not_as_zero():
    """No QC run and a QC result of zero are different facts."""
    from nodes.instruments.seismic import _forward_qc_from_inputs

    assert _forward_qc_from_inputs({}) is None
    assert _forward_qc_from_inputs({"forward_qc": None}) is None
