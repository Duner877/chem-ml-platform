"""Regression tests for the external ABACUS path.

The defects these lock down were invisible to every existing check.  The
external backend reported ``engine=external:abacus`` with ``returncode=0`` and
``message="external run finished"`` while handing downstream figure nodes an
empty spectrum -- so a workflow asked for six product figures and delivered
none, and reported success.

The tests therefore drive a fake ``abacus`` executable and assert on **port
data**: the spectrum must exist, carry one trace per band, and the metrics must
contain a real total energy rather than the ``0.0`` that an empty metrics dict
used to be silently coerced into.

``shutil.which`` honours PATHEXT, so the launcher is ``abacus.cmd`` -- which is
also what the official ABACUS Windows installer emits.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from simulations.runners import ToolResult  # noqa: E402
from simulation_runtime.materials import ABACUSBackend  # noqa: E402
from workflow_engine.objects import Material  # noqa: E402

# A fake ABACUS that behaves like the real one: it reads ./INPUT, writes
# OUT.ABACUS/, rejects positional arguments, and prints an SCF table with no
# "total energy:" label (which is why the old stdout regex matched nothing).
_FAKE_BODY = r'''
import pathlib, sys
wd = pathlib.Path.cwd()
print("ARGV_SEEN_BY_ABACUS:", sys.argv[1:])
for arg in sys.argv[1:]:
    if not arg.startswith("-"):
        print("ABACUS: unrecognised positional argument:", arg)
        sys.exit(2)
if not (wd / "INPUT").is_file():
    print("ABACUS: no INPUT in cwd -> abort")
    sys.exit(1)
out = wd / "OUT.ABACUS"
out.mkdir(exist_ok=True)
(out / "running_scf.log").write_text(
    " E_Fermi 8.19 eV\n FINAL_ETOT_IS -3.749860962\n", encoding="utf-8")
(out / "BANDS_1.dat").write_text(
    "  -5.10 -1.20\n  -3.30  0.40\n  -1.10  1.90\n", encoding="utf-8")
(out / "dos_0.dat").write_text(
    "-5.0 0.10\n-4.0 0.85\n-3.0 1.92\n", encoding="utf-8")
(out / "pdos_0.dat").write_text(
    "-5.0 0.02 0.08\n-4.0 0.11 0.74\n-3.0 0.20 1.72\n", encoding="utf-8")
print("ITERATION    E_KohnSham(HA)")
print("1  -7.41239831")
sys.exit(0)
'''

HARTREE_TO_EV = 27.211386245988


def _make_out_dir(files: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="abacus_out_"))
    out = root / "OUT.ABACUS"
    out.mkdir(parents=True)
    for name, content in files.items():
        (out / name).write_text(content, encoding="utf-8")
    return out


class TestAbacusOutputReaders(unittest.TestCase):
    """Unit level: each reader against one documented file shape."""

    def setUp(self) -> None:
        self.backend = ABACUSBackend()

    def test_total_energy_comes_from_final_etot_is_in_hartree(self) -> None:
        out = _make_out_dir({"running_scf.log": " FINAL_ETOT_IS -3.749860962\n"})
        self.assertAlmostEqual(
            self.backend._read_total_energy(out), -3.749860962 * HARTREE_TO_EV, places=6
        )

    def test_istate_info_is_not_mistaken_for_a_total_energy(self) -> None:
        """``istate.info`` column 1 is an eigenvalue, not the total energy.

        Reading it as the energy reported -145.28 eV for aluminium -- a
        physically meaningless number that nothing would have flagged.
        """
        out = _make_out_dir({
            "istate.info": (
                "BAND              Energy (ev)          Occupation\n"
                "Kpoint = 1  ->  (0 0 0)\n"
                "1        -5.33892    0.03125\n"
            )
        })
        self.assertIsNone(self.backend._read_total_energy(out))

    def test_missing_log_yields_none_rather_than_zero(self) -> None:
        out = _make_out_dir({"BANDS_1.dat": " -5.10 -1.20\n"})
        self.assertIsNone(self.backend._read_total_energy(out))

    def test_bands_file_is_transposed_from_k_major_to_one_trace_per_band(self) -> None:
        out = _make_out_dir({"BANDS_1.dat": " -5.10 -1.20\n -3.30  0.40\n -1.10  1.90\n"})
        parsed = self.backend._read_bands(out)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["bands"]), 2)
        self.assertEqual(parsed["bands"][0], [-5.10, -3.30, -1.10])
        self.assertEqual(parsed["bands"][1], [-1.20, 0.40, 1.90])

    def test_single_band_file_is_not_discarded(self) -> None:
        """One band means one column; a ">= 2 columns" guard drops it silently."""
        out = _make_out_dir({"BANDS_1.dat": " -5.10\n -3.30\n -1.10\n"})
        parsed = self.backend._read_bands(out)
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed["bands"]), 1)

    def test_lowercase_band_filename_is_not_matched(self) -> None:
        """The documented name is ``BANDS_1.dat``; a wrong glob finds nothing."""
        out = _make_out_dir({"band_0.dat": " 1.0 2.0 3.0\n"})
        self.assertIsNone(self.backend._read_bands(out))

    def test_dos_and_pdos_readers(self) -> None:
        out = _make_out_dir({
            "dos_0.dat": "-5.0 0.10\n-4.0 0.85\n",
            "pdos_0.dat": "-5.0 0.02 0.08\n-4.0 0.11 0.74\n",
        })
        dos = self.backend._read_dos(out)
        self.assertEqual(dos["x"], [-5.0, -4.0])
        self.assertEqual(dos["y"], [0.10, 0.85])
        pdos = self.backend._read_pdos(out)
        self.assertEqual(len(pdos["curves"]), 2)
        self.assertEqual(len(pdos["labels"]), 2)

    def test_header_lines_are_skipped_not_crashed_on(self) -> None:
        out = _make_out_dir({
            "dos_0.dat": "Energy(eV) DOS\n-5.0 0.10\n#comment\n-4.0 0.85\n"
        })
        dos = self.backend._read_dos(out)
        self.assertEqual(len(dos["x"]), 2)


class TestAbacusExternalPathDeliversData(unittest.TestCase):
    """Integration level: the node's ports, driven through a fake executable."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.bindir = Path(tempfile.mkdtemp(prefix="abacus_fakebin_"))
        (cls.bindir / "body.py").write_text(_FAKE_BODY, encoding="utf-8")
        (cls.bindir / "abacus.cmd").write_text(
            f'@echo off\r\n"{sys.executable}" "%~dp0body.py" %*\r\n', encoding="utf-8"
        )
        cls._old_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{cls.bindir}{os.pathsep}{cls._old_path}"

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ["PATH"] = cls._old_path

    def _run(self, calculation: str):
        from simulation_runtime.base import SimulationRuntime
        from simulation_runtime.materials import MATERIALS_BACKENDS

        runtime = SimulationRuntime()
        for item in MATERIALS_BACKENDS:
            runtime.register(item)
        material = Material(
            formula="Al",
            name="aluminium fcc",
            structure={"lattice": "fcc", "a": 4.05, "element": "Al"},
            properties={},
        )
        workdir = Path(tempfile.mkdtemp(prefix=f"abacus_run_{calculation}_"))
        return runtime.run(
            "materials",
            material,
            workdir=workdir,
            calculation=calculation,
            element="Al",
            lattice="fcc",
            a=4.05,
            timeout=120.0,
        )

    def test_fake_executable_is_discoverable(self) -> None:
        """Windows note: an extensionless file is invisible to ``which``."""
        import shutil

        self.assertIsNotNone(shutil.which("abacus"))

    def test_bands_run_populates_the_spectrum_port(self) -> None:
        result = self._run("bands")
        self.assertEqual(result.engine, "external:abacus")
        spectrum = (result.ports or {}).get("spectrum")
        self.assertIsNotNone(
            spectrum, "external run reported success but delivered no spectrum"
        )
        self.assertEqual(getattr(spectrum, "mode", ""), "Bands")
        self.assertEqual(len(spectrum.curves), 2)
        self.assertTrue(all(len(row) == 3 for row in spectrum.curves))

    def test_total_energy_is_parsed_not_defaulted_to_zero(self) -> None:
        result = self._run("bands")
        self.assertIn("total_energy_ev", result.metrics)
        self.assertNotEqual(result.metrics["total_energy_ev"], 0.0)
        self.assertAlmostEqual(
            result.metrics["total_energy_ev"], -3.749860962 * HARTREE_TO_EV, places=6
        )

    def test_abacus_is_invoked_without_a_positional_input_argument(self) -> None:
        result = self._run("bands")
        self.assertEqual(result.engine, "external:abacus")
        observed = (result.raw.get("tool") or {}).get("stdout_tail") or ""
        line = next(
            (row for row in observed.splitlines() if "ARGV_SEEN_BY_ABACUS" in row), ""
        )
        self.assertTrue(
            line.endswith("[]"),
            f"ABACUS takes only switches; got argv {line!r}",
        )

    def test_dos_run_yields_a_populated_dos(self) -> None:
        result = self._run("dos")
        spectrum = (result.ports or {}).get("spectrum")
        self.assertIsNotNone(spectrum)
        self.assertEqual(getattr(spectrum, "mode", ""), "DOS")
        self.assertEqual(len(spectrum.y), 3)

    def test_pdos_run_yields_one_curve_per_orbital(self) -> None:
        result = self._run("pdos")
        spectrum = (result.ports or {}).get("spectrum")
        self.assertIsNotNone(spectrum)
        self.assertEqual(getattr(spectrum, "mode", ""), "PDOS")
        self.assertEqual(len(spectrum.curves), 2)
        self.assertEqual(len(spectrum.curve_labels), 2)

    def test_successful_run_without_output_files_raises_instead_of_reporting_ok(self) -> None:
        """A run that produced no spectrum must not look like a success.

        The failure mode being locked down is precisely a green result that
        yields nothing, so silence is not an acceptable outcome here.
        """
        from workflow_engine.errors import ExternalToolError

        backend = ABACUSBackend()
        empty = Path(tempfile.mkdtemp(prefix="abacus_empty_"))
        (empty / "OUT.ABACUS").mkdir()
        material = Material(
            formula="Al", name="al",
            structure={"lattice": "fcc", "a": 4.05, "element": "Al"},
            properties={},
        )
        result = ToolResult(command=["abacus"], returncode=0, stdout="", workdir=str(empty))
        with self.assertRaises(ExternalToolError):
            backend.to_object_from_result(
                result, material, {}, calculation="bands", element="Al"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)