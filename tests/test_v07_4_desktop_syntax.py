"""Regression: the Electron main process must parse before it ships (v0.7.4).

The 0.7.4 installer shipped a ``desktop/src/main.js`` with one surplus
closing parenthesis.  The failure was unusually well camouflaged:

* the TypeScript linter only reads ``frontend/``, so it said nothing;
* ``electron-builder`` copies the script into the package without parsing it,
  so the installer was produced successfully;
* the installer itself installed cleanly, and the main process started --
  but died inside the module loader, *before* ``app.whenReady()``.

The result was an application with no window, no renderer process and not a
single line in ``backend.log``.  Nothing in the pipeline could point at the
cause, because every stage that ran had, by construction, succeeded.

These tests pin the two properties that make such a bug impossible to ship
again:

* the shipped main-process scripts parse;
* the quality gate's syntax stage actually *fails* on a broken script, so it
  is a gate rather than a rubber stamp.

The second test matters more than the first.  A check that cannot fail is not
a check, and a gate stage added without proving it catches the failure is how
the next one slips through.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
SCRIPTS = DESKTOP / "src"

NODE = shutil.which("node") or shutil.which("node.exe")

pytestmark = pytest.mark.desktop

requires_node = pytest.mark.skipif(
    NODE is None, reason="node is not installed on this host (parse check needs Node)"
)


def _load_gate():
    """Import ``quality_gate.py`` without importing the whole package."""
    spec = importlib.util.spec_from_file_location(
        "quality_gate_under_test", ROOT / "scripts" / "quality_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _parse_ok(path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [NODE, "--check", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        cwd=str(ROOT),
    )


class TestMainProcessParses:
    """Every script that ends up inside the installer must parse."""

    @requires_node
    def test_shipped_scripts_parse(self):
        scripts = sorted(SCRIPTS.glob("*.js"))
        assert scripts, f"no scripts found under {SCRIPTS}"
        broken = []
        for script in scripts:
            result = _parse_ok(script)
            if result.returncode != 0:
                broken.append(f"{script.name}: {result.stderr.strip().splitlines()[-1]}")
        assert not broken, "desktop main-process scripts do not parse:\n" + "\n".join(broken)

    @requires_node
    def test_the_shipped_entry_point_parses(self):
        """``package.json``'s ``main`` is the file Electron loads first.

        A parse error there kills the app before ``app.whenReady()``, so it
        gets its own assertion rather than being folded into the sweep above.
        """
        import json

        config = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
        entry = config["main"]
        target = DESKTOP / entry
        assert target.exists(), f"package.json main points at a missing file: {entry}"
        result = _parse_ok(target)
        assert result.returncode == 0, (
            f"{entry} does not parse -- the application would start and die "
            f"before app.whenReady():\n{result.stderr}"
        )


class TestGateStageCatchesSyntaxErrors:
    """The gate stage must be able to fail."""

    @requires_node
    def test_stage_is_registered(self):
        gate = _load_gate()
        names = [stage[0] for stage in gate.build_suite(True)]
        assert "desktop_main_process_syntax" in names, (
            "the quality gate has no stage that parses the desktop scripts; "
            "a syntax error there is invisible to every other stage"
        )

    @requires_node
    def test_stage_reports_a_broken_script_as_failure(self):
        """Prove the stage fails on a broken script.

        The stage runs against the repository, so the break is applied to a
        temporary copy of the tree instead: the stage's own path resolution is
        what is under test, and a stage that only ever sees green trees is
        indistinguishable from a stage that never runs.
        """
        gate = _load_gate()

        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            (tmp_root / "scripts").mkdir()
            (tmp_root / "desktop" / "src").mkdir(parents=True)
            broken = tmp_root / "desktop" / "src" / "main.js"
            broken.write_text(
                "const x = { a: 1 });\n",  # surplus closing parenthesis
                encoding="utf-8",
            )
            (tmp_root / "scripts" / "quality_gate.py").write_text(
                (ROOT / "scripts" / "quality_gate.py").read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            original_root = gate.ROOT
            try:
                gate.ROOT = tmp_root
                with tempfile.TemporaryDirectory() as log_dir:
                    status, detail, extra = gate.stage_desktop_syntax(Path(log_dir))
            finally:
                gate.ROOT = original_root

        assert status == "FAIL", (
            "the syntax stage passed a script that does not parse -- the gate "
            "would not have caught the shipped 0.7.4 installer"
        )
        assert "main.js" in detail or "main.js" in str(extra)

    @requires_node
    def test_stage_passes_on_a_valid_script(self):
        gate = _load_gate()
        with tempfile.TemporaryDirectory() as log_dir:
            status, detail, _ = gate.stage_desktop_syntax(Path(log_dir))
        assert status == "PASS", f"the syntax stage failed on the current tree: {detail}"
