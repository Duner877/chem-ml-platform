"""Regression tests for the 0.7.3 hard-carbon pre-desolvation family.

The paper model (Nat. Commun. 15, 3497) is only useful if its numbers land on
the paper's own numbers.  Three things broke silently before these tests existed:

1. **The ICE ceiling was 100 %.**  ``aging_curves`` folded "loss that forms
   while the pores fill" and "loss that remains afterwards" into one parameter,
   so a fully aged cell reported exactly 100 % efficiency -- a number the paper
   never measures and no experiment produces.  The measured plateau is 99.09 %.
2. **The ICE gain read 0.91 pp instead of 8.95 pp.**  A direct consequence of
   the above: with the ceiling pinned at 100, most of the real improvement had
   nowhere to go.  Both reported anchors (90.14 % at 12 h, 99.09 % at 10 days)
   must come out of the model.
3. **The roll-up node indexed three different tables by position.**  The sieve
   table puts ``label`` at index 1 and ``size_angstrom`` at 2; reading index 1
   as a radius raised ``ValueError`` on the first run.  It now selects by column
   name, which is what makes the "one branch unconnected" case safe too.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from models.desolvation import (
    ICE_AT_10D,
    ICE_AT_12H,
    PAPER_PORE_DIAMETER_A,
    aging_curves,
)
from nodes.loader import get_registry
from workflow_engine.engine import WorkflowEngine

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / "workflows" / "08_hard_carbon_predesolvation.json"


@pytest.fixture(scope="module", autouse=True)
def _registry():
    get_registry().discover_package("nodes")


def _node(node_type: str, **params):
    return get_registry().create(node_type, params=params).execute({})


# --------------------------------------------------------------------------- #
# 1. The ICE curve is anchored on the paper's two measurements
# --------------------------------------------------------------------------- #
def test_ice_saturates_at_the_measured_plateau():
    """Not 100 %: the paper's best cell still loses ~0.91 %.

    The tolerance is 0.01 pp because the curve is sampled on a finite grid: at
    240 h with tau = 20.27 h the remaining unfilled fraction is ~5e-6, so the
    asymptote is reached to five digits but not exactly.
    """
    result = aging_curves(tau_fill_h=20.27, sei_capacity_loss=8.95)
    assert result.ice_percent[-1] == pytest.approx(ICE_AT_10D, abs=0.01)


def test_ice_start_and_gain_reproduce_the_reported_pair():
    """12 h -> 90.14 % and 10 d -> 99.09 % pin the loss split."""
    result = aging_curves(tau_fill_h=20.27, sei_capacity_loss=8.95)
    assert result.ice_percent[0] == pytest.approx(ICE_AT_12H, abs=0.01)
    assert result.ice_percent[-1] - result.ice_percent[0] == pytest.approx(8.95, abs=0.01)


def test_a_fully_aged_cell_never_reports_perfect_efficiency():
    """The specific bug: a 100 % ceiling is a number no experiment produces."""
    for loss in (0.5, 8.95, 12.5, 40.0):
        peak = max(aging_curves(sei_capacity_loss=loss).ice_percent)
        assert peak < 100.0, f"loss={loss} produced a perfect cell"


def test_ice_is_monotonically_increasing():
    result = aging_curves(tau_fill_h=20.27, sei_capacity_loss=8.95)
    assert all(b >= a for a, b in zip(result.ice_percent, result.ice_percent[1:]))


def test_impedance_hits_both_reported_points():
    """86.2 ohm at 4 h and 14.6 ohm at 40 h come out by construction."""
    result = aging_curves(time_h=[4.0, 40.0])
    assert result.impedance_ohm[0] == pytest.approx(86.2, abs=1e-6)
    assert result.impedance_ohm[1] == pytest.approx(14.6, abs=1e-6)


def test_residual_loss_must_be_a_percentage():
    with pytest.raises(ValueError):
        aging_curves(residual_loss_percent=101.0)
    with pytest.raises(ValueError):
        aging_curves(residual_loss_percent=-1.0)


def test_tau_must_be_positive():
    with pytest.raises(ValueError):
        aging_curves(tau_fill_h=0.0)


# --------------------------------------------------------------------------- #
# 2. The node exposes the split loss as a parameter
# --------------------------------------------------------------------------- #
def test_aging_node_saturates_at_the_measured_value():
    out = _node(
        "ElectrolyteAgingNode",
        tau_fill=20.27,
        r_initial=86.2,
        r_residual=14.6,
        sei_loss=8.95,
        residual_loss=0.91,
        max_time=240.0,
    )
    ice = out["table"].column("ice_percent")
    assert ice[-1] == pytest.approx(ICE_AT_10D, abs=0.01)
    assert ice[-1] < 100.0


def test_aging_node_reports_its_engine():
    out = _node("ElectrolyteAgingNode")
    assert out["table"].metadata.get("engine")
    assert out["text"].metadata.get("engine")


# --------------------------------------------------------------------------- #
# 3. The roll-up node reads columns by name and copes with missing branches
# --------------------------------------------------------------------------- #
def _three_branches():
    sieve = _node(
        "DesolvationSieveNode",
        pore_diameter=PAPER_PORE_DIAMETER_A,
        electrolyte="ether",
        concentration=1.0,
        dielectric=7.2,
    )
    aging = _node(
        "ElectrolyteAgingNode",
        tau_fill=20.27,
        r_initial=86.2,
        r_residual=14.6,
        sei_loss=8.95,
        residual_loss=0.91,
    )
    sei = _node(
        "DoubleSEIEnergeticsNode", electrolyte="ether", process="1", dielectric=7.2
    )
    return sieve, aging, sei


def test_rollup_accepts_all_three_branches():
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"], "energetics": sei["table"]}
    )
    stages = out["stages"].records()
    assert [row["verdict"] for row in stages] == ["ok", "ok", "ok"]
    assert out["text"].metadata["verdict"] == "ok"


def test_rollup_reports_a_missing_branch_instead_of_inventing_one():
    """An unconnected branch must read "not connected", not "no effect"."""
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"]}
    )
    stages = {row["stage"]: row["verdict"] for row in out["stages"].records()}
    assert stages["1_size_sieve"] == "ok"
    assert stages["3_double_sei"] == "not_connected"
    assert out["text"].metadata["verdict"] == "partial"
    assert out["text"].metadata["missing_stages"] == ["energetics"]


def test_rollup_with_no_inputs_does_not_crash():
    """A user wiring the node before anything else must get a message, not a stack trace."""
    out = get_registry().create("PreDesolvationMechanismNode").execute({})
    assert out["text"].metadata["verdict"] == "partial"
    assert len(out["stages"].rows) == 3
    assert out["mechanism"].metadata["series_names"] == []


def test_rollup_does_not_misread_the_sieve_label_as_a_number():
    """The regression: index 1 of the sieve table is a human label."""
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"], "energetics": sei["table"]}
    )
    # 3 of 4 solvation structures fit through the 4 A throat (Fig. 2d).
    admitted = out["stages"].records()[0]["value"]
    assert admitted == "3/4"


def test_rollup_double_sei_reduction_matches_the_energetics_table():
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"], "energetics": sei["table"]}
    )
    reported = float(sei["table"].column("reduction_percent")[0])
    shown = out["stages"].records()[2]["value"]
    assert shown == f"{reported:+.1f} %"


def test_rollup_barriers_use_the_reported_energies():
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"], "energetics": sei["table"]}
    )
    barriers = out["barriers"]
    assert len(barriers.y) == 2
    assert barriers.y[1] < barriers.y[0], "the in-pore SEI must be the cheaper one"
    assert barriers.y == pytest.approx(
        [
            float(sei["table"].column("E_a_S_SEI_kJ")[0]),
            float(sei["table"].column("E_a_I_SEI_kJ")[0]),
        ]
    )


def test_rollup_drops_and_names_a_branch_it_cannot_resample():
    """A 4-point sieve curve cannot share a 25-point ICE axis honestly."""
    sieve, aging, sei = _three_branches()
    out = get_registry().create("PreDesolvationMechanismNode").execute(
        {"sieve": sieve["sieve"], "aging": aging["table"], "energetics": sei["table"]}
    )
    mechanism = out["mechanism"]
    assert mechanism.metadata["dropped_series"] == ["radius ratio (SolvationState)"]
    assert mechanism.metadata["series_names"] == ["ICE vs rest time"]
    assert len(mechanism.x) == len(mechanism.y)


# --------------------------------------------------------------------------- #
# 4. The workflow wires the three stages into the roll-up
# --------------------------------------------------------------------------- #
def test_workflow_declares_the_rollup_and_its_three_edges():
    payload = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    ids = {node["type"] for node in payload["nodes"]}
    assert "PreDesolvationMechanismNode" in ids
    targets = {
        edge["target_port"] for edge in payload["edges"] if edge["target"] == "mechanism"
    }
    assert targets == {"sieve", "aging", "energetics"}


def test_workflow_anchors_the_aging_parameters():
    payload = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    aging = next(n for n in payload["nodes"] if n["id"] == "aging")
    params = aging["params"]
    assert params["sei_loss"] == pytest.approx(8.95)
    assert params["residual_loss"] == pytest.approx(100.0 - ICE_AT_10D, abs=0.01)
    assert params["tau_fill"] == pytest.approx(20.27, abs=0.01)


def test_workflow_runs_end_to_end_with_every_stage_ok():
    from backend.routers.workflows import load_workflow

    workflow = asyncio.run(load_workflow(WORKFLOW.name))
    result = WorkflowEngine(registry=get_registry()).run(workflow)
    assert result.status == "completed", result.errors
    assert result.errors == []
    text = result.output("mechanism", "text")
    assert text is not None
    assert text.metadata["verdict"] == "ok"
    assert text.metadata["engine"]
    stages = result.output("mechanism", "stages")
    assert [row["verdict"] for row in stages.records()] == ["ok", "ok", "ok"]


def test_workflow_cites_the_paper():
    payload = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    assert "47522" in payload["metadata"]["citation"]
    assert payload["version"] == "0.7.3"


# --------------------------------------------------------------------------- #
# 5. Nothing quietly claims to be first-principles
# --------------------------------------------------------------------------- #
def test_every_branch_states_that_it_is_a_surrogate():
    """A plot that looks like NEB but was not computed by NEB must say so."""
    for node_type, kwargs in (
        ("DesolvationSieveNode", {"pore_diameter": PAPER_PORE_DIAMETER_A}),
        ("ElectrolyteAgingNode", {}),
        ("DoubleSEIEnergeticsNode", {"electrolyte": "ether"}),
        ("PreDesolvationMechanismNode", {}),
    ):
        out = _node(node_type, **kwargs)
        engine = out["text"].metadata.get("engine", "")
        assert engine.startswith("internal:"), f"{node_type} claims engine {engine!r}"
        assert "external:" not in engine
        body = out["text"].text
        assert "NEB" in body or "first-principles" in body or "第一性原理" in body