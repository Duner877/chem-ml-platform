"""v0.7.2 spec task P0-05 -- known-answer tests for `verified`-grade nodes.

A node may only claim ``capability_status = "verified"`` when an *independent*
known-answer check backs that claim (task P0-05: "所有声明为 verified 的节点都有
可追溯验证证据" / "未验证节点不得仅凭可以执行就标记为 verified").

The tests here are deliberately **analytically** verifiable: the input is built
from a closed-form expression, so the correct output is known exactly rather
than by comparison with the implementation's own previous behaviour.

These names are referenced verbatim from the nodes' ``validation_evidence``
lists, so renaming a test invalidates the claim -- which is the point.
"""

from __future__ import annotations

import math

import pytest

from workflow_engine.objects import Molecule, Spectrum, Table


def _gaussian(x: float, centre: float, width: float, height: float = 1.0) -> float:
    return height * math.exp(-((x - centre) ** 2) / (2.0 * width ** 2))


class TestPeakPickingKnownAnswer:
    """PeakPickingNode -- the injected peak centres are the known answer."""

    CENTRES = (10.0, 25.0, 42.0)
    WIDTH = 0.4
    STEP = 0.01

    def _spectrum(self) -> Spectrum:
        xs, ys = [], []
        value = 0.0
        while value <= 60.0:
            y = sum(_gaussian(value, c, self.WIDTH) for c in self.CENTRES)
            xs.append(round(value, 4))
            ys.append(y)
            value += self.STEP
        return Spectrum.from_arrays(xs, ys, mode="IR", x_unit="cm-1", name="known-answer")

    def test_recovers_injected_peak_positions(self, registry):
        node = registry.create("PeakPickingNode", "pp", {"prominence": 0.05})
        outputs = node.process({"spectrum": self._spectrum()}, None)
        peaks = outputs["spectrum"].peaks
        assert len(peaks) == len(self.CENTRES), f"expected 3 peaks, got {len(peaks)}"
        centres = sorted(float(p.x) for p in peaks)
        for found, expected in zip(centres, self.CENTRES):
            assert abs(found - expected) < 0.05, f"{found} != {expected}"

    def test_peak_count_is_exact(self, registry):
        """A flat baseline must yield zero peaks -- no fabricated detection."""
        xs = [float(i) for i in range(200)]
        flat = Spectrum.from_arrays(xs, [0.0] * 200, mode="IR")
        node = registry.create("PeakPickingNode", "pp2", {"prominence": 0.05})
        assert node.process({"spectrum": flat}, None)["spectrum"].peaks == []

    def test_peak_table_matches_peak_list(self, registry):
        node = registry.create("PeakPickingNode", "pp3", {"prominence": 0.05})
        outputs = node.process({"spectrum": self._spectrum()}, None)
        table = outputs["table"]
        assert isinstance(table, Table)
        assert len(table.rows) == len(outputs["spectrum"].peaks)


class TestNormalizeKnownAnswer:
    """NormalizeNode(max) -- the maximum must become exactly 1.0."""

    def _spectrum(self) -> Spectrum:
        # y = 2*x on [0, 10] -> max is 20 at x = 10.
        xs = [i * 0.1 for i in range(101)]
        ys = [2.0 * x for x in xs]
        return Spectrum.from_arrays(xs, ys, mode="UV-Vis")

    def test_max_normalisation_is_exact(self, registry):
        node = registry.create("NormalizeNode", "n1", {"method": "max"})
        out = node.process({"spectrum": self._spectrum()}, None)["spectrum"]
        assert max(out.y) == pytest.approx(1.0, abs=1e-12)
        # The argmax is preserved by max-normalisation.
        assert out.x[out.y.index(max(out.y))] == pytest.approx(10.0, abs=1e-9)

    def test_none_is_identity(self, registry):
        node = registry.create("NormalizeNode", "n2", {"method": "none"})
        original = self._spectrum()
        out = node.process({"spectrum": original}, None)["spectrum"]
        assert out.y == pytest.approx(original.y, abs=1e-12)


class TestSmoothingKnownAnswer:
    """SmoothingNode -- a symmetric kernel leaves a linear ramp unchanged."""

    def test_linear_ramp_is_invariant(self, registry):
        xs = [float(i) for i in range(101)]
        ys = [0.5 * x + 3.0 for x in xs]
        ramp = Spectrum.from_arrays(xs, ys, mode="IR")
        node = registry.create("SmoothingNode", "s1", {"window": 5, "method": "moving_average"})
        out = node.process({"spectrum": ramp}, None)["spectrum"]
        # Interior points of a linear ramp are reproduced exactly by any
        # symmetric normalised kernel; the edges are handled by the node's own
        # padding policy, so only the interior is asserted.
        for index in range(10, len(xs) - 10):
            assert out.y[index] == pytest.approx(ys[index], abs=1e-9)


class TestMolecularFormulaKnownAnswer:
    """MoleculeInputNode -- ethanol's formula and exact mass are known."""

    def test_ethanol_formula_and_exact_mass(self, registry):
        molecule = registry.create(
            "MoleculeInputNode", "m1", {"smiles": "CCO"}
        ).process({}, None)["molecule"]
        assert isinstance(molecule, Molecule)
        assert molecule.formula == "C2H6O"
        # Monoisotopic mass of C2H6O = 2*12.0 + 6*1.0078250319 + 15.9949146221
        assert molecule.exact_mass == pytest.approx(46.0419, abs=1e-3)

    def test_heavy_atom_count_is_three(self, registry):
        molecule = registry.create(
            "MoleculeInputNode", "m2", {"smiles": "CCO"}
        ).process({}, None)["molecule"]
        heavy = [a for a in molecule.atoms if str(getattr(a, "element", "")) != "H"]
        assert len(heavy) == 3


class TestVerifiedClaimIntegrity:
    """A `verified` claim must point at real, existing evidence."""

    def test_every_verified_node_has_existing_evidence(self, registry):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        verified = []
        for node_type in registry.types():
            spec = registry.spec(node_type)
            if spec.get("capability_status") != "verified":
                continue
            verified.append(node_type)
            evidence = spec.get("validation_evidence") or []
            assert evidence, f"{node_type} claims verified without evidence"
            for item in evidence:
                target = item.split("::")[0]
                assert (root / target).exists(), f"{node_type}: evidence {item} does not exist"
        # The mechanism must actually be exercised by at least one node.
        assert verified, "no node claims 'verified' -- the mechanism is untested"

    def test_no_verified_without_evidence_is_possible(self):
        """The downgrade rule itself: declared verified + no evidence -> executable."""
        from workflow_engine.node_base import ScientificNode

        class Rogue(ScientificNode):
            capability_status = "verified"
            validation_evidence = []

        status, note = Rogue.effective_capability_status()
        assert status == "executable"
        assert note and "no validation_evidence" in note

    def test_external_without_dependency_is_downgraded(self):
        from workflow_engine.node_base import ScientificNode

        class Rogue(ScientificNode):
            execution_mode = "external"
            required_software = []
            required_dependencies = []

        mode, note = Rogue.effective_execution_mode()
        assert mode == "internal_approximation"
        assert note
