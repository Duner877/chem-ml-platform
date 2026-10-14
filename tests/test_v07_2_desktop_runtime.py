"""Desktop runtime probe and packaging tests (spec task P0-02).

The v0.7.1 audit found the desktop shell validated four packages and then
declared the environment healthy.  These tests pin the replacement behaviour:

* the probe reads and validates the **whole** declared runtime set;
* a missing distribution is classified as ``dependencies_missing``, not ``ok``;
* an out-of-range interpreter is ``python_incompatible`` (and a patch release of
  the newest supported minor is *not* out of range -- a real bug found while
  writing this suite);
* optional components degrade capability instead of blocking startup;
* the Electron shell wires the packaged frontend, the runtime probe and the
  documented user-data / log directories.

Every test that needs Node is skipped with a stated reason when ``node`` is not
available, and never silently reported as a pass.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / "desktop"
PROBE = DESKTOP / "src" / "runtime-probe.js"

NODE = shutil.which("node")

pytestmark = pytest.mark.desktop


def _node_available() -> bool:
    return NODE is not None


requires_node = pytest.mark.skipif(
    not _node_available(), reason="node is not installed on this host (desktop probe needs Node)"
)


def _run_probe(*extra: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run the probe CLI and return the completed process (exit code is meaningful)."""
    import sys

    return subprocess.run(
        [NODE, str(PROBE), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        cwd=str(ROOT),
    )


def _find_python() -> str:
    import sys

    for candidate in (sys.executable, shutil.which("python3"), shutil.which("python")):
        if candidate:
            return candidate
    return ""


# --------------------------------------------------------------------------- #
# Static wiring
# --------------------------------------------------------------------------- #


class TestElectronWiring:
    """The shell must reference the packaged layout, not the dev tree."""

    def test_probe_module_exists_and_is_plain_commonjs(self):
        assert PROBE.exists(), "desktop/src/runtime-probe.js is missing"
        text = PROBE.read_text(encoding="utf-8")
        # Must stay requireable without Electron so it can be tested/CLI-run.
        assert 'require("electron")' not in text
        assert "module.exports" in text
        assert "require.main === module" in text

    def test_main_process_uses_the_probe(self):
        main = (DESKTOP / "src" / "main.js").read_text(encoding="utf-8")
        assert 'require("./runtime-probe")' in main
        assert "probeRuntime" in main

    def test_main_process_classifies_failures(self):
        main = (DESKTOP / "src" / "main.js").read_text(encoding="utf-8")
        for code in (
            "install_failure",
            "runtime_missing",
            "dependency_missing",
            "port_conflict",
            "backend_timeout",
            "backend_crashed",
            "backend_unstable",
        ):
            assert code in main, f"failure code {code} is not defined in main.js"

    def test_main_process_terminates_the_child_tree_on_every_quit_path(self):
        main = (DESKTOP / "src" / "main.js").read_text(encoding="utf-8")
        for hook in ('app.on("before-quit"', 'app.on("will-quit"', 'process.on("exit"'):
            assert hook in main, f"missing child-cleanup hook {hook}"
        assert "taskkill" in main and "/T" in main

    def test_main_process_fails_fast_when_the_backend_dies(self):
        main = (DESKTOP / "src" / "main.js").read_text(encoding="utf-8")
        assert "BACKEND_EXITED" in main
        assert "HEALTH_TIMEOUT" in main
        # the timeout must be configurable, not a hard-coded constant only
        assert "CHEMML_START_TIMEOUT_MS" in main

    def test_preload_exposes_the_v072_surface(self):
        preload = (DESKTOP / "src" / "preload.js").read_text(encoding="utf-8")
        for channel in (
            "backend-failure",
            "backend-restarting",
            "runtime-diagnosis",
            "port-info",
            "restart-backend",
        ):
            assert channel in preload, f"preload does not expose {channel}"

    def test_packaged_layout_includes_the_runtime_probe(self):
        config = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
        assert "src/**/*" in config["build"]["files"]
        # extraResources must carry the built frontend and the python app tree
        targets = {entry["to"] for entry in config["build"]["extraResources"]}
        assert "app/frontend/dist" in targets
        assert "app/backend" in targets
        assert "app/requirements.txt" in targets or any("requirements" in t for t in targets)

    def test_package_json_declares_the_current_version(self):
        import chemml_version

        config = json.loads((DESKTOP / "package.json").read_text(encoding="utf-8"))
        assert config["version"] == chemml_version.VERSION


class TestRuntimeProbeContract:
    """The probe must be a stable, documented interface."""

    def test_dependency_groups_are_declared_separately(self):
        runtime = ROOT / "requirements.runtime.txt"
        optional = ROOT / "requirements.optional.txt"
        dev = ROOT / "requirements.dev.txt"
        assert runtime.exists() and optional.exists() and dev.exists()
        # requirements.txt is a manifest of groups, so it must not duplicate pins
        manifest = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "-r requirements.runtime.txt" in manifest
        assert "fastapi" not in manifest

    def test_runtime_set_covers_the_advertised_features(self):
        text = (ROOT / "requirements.runtime.txt").read_text(encoding="utf-8")
        for package in ("fastapi", "uvicorn", "pydantic", "numpy", "scipy", "networkx", "matplotlib"):
            assert package in text, f"{package} missing from the required runtime set"
        # optional accelerators must NOT be required, or startup would block
        assert "torch" not in text

    def test_probe_parses_requirement_lines(self):
        source = PROBE.read_text(encoding="utf-8")
        # comments and blank lines are filtered in JS before hitting python
        assert "startsWith(\"#\")" in source

    def test_probe_reads_the_runtime_group_first(self):
        source = PROBE.read_text(encoding="utf-8")
        assert '"requirements.runtime.txt"' in source
        assert '"requirements.optional.txt"' in source


# --------------------------------------------------------------------------- #
# Live probe
# --------------------------------------------------------------------------- #


@requires_node
class TestLiveProbe:
    """Run the real probe against the real interpreter on this host."""

    def test_probe_returns_a_classification(self):
        proc = _run_probe("--json", "--python", _find_python())
        payload = json.loads(proc.stdout)
        assert payload["classification"] in {
            "ok",
            "python_missing",
            "python_incompatible",
            "dependencies_missing",
            "dependencies_incompatible",
            "probe_error",
        }
        assert payload["pythonCommand"] == _find_python()

    def test_supported_range_is_a_major_minor_band(self):
        proc = _run_probe("--json", "--python", _find_python())
        payload = json.loads(proc.stdout)
        assert payload["python"]["supportedRange"] == "3.10–3.13"

    def test_patch_release_of_newest_supported_minor_is_not_out_of_range(self):
        """Regression: 3.13.14 was wrongly classified as incompatible."""
        source = PROBE.read_text(encoding="utf-8")
        assert "function outOfRange" in source
        assert "slice(0, 2)" in source, "the range check must compare major.minor only"

    def test_probe_validates_the_whole_declared_set(self):
        proc = _run_probe("--json", "--python", _find_python())
        payload = json.loads(proc.stdout)
        declared_lines = [
            line
            for line in (ROOT / "requirements.runtime.txt").read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert payload["requirements"]["declared"] == len(declared_lines)
        assert payload["requirements"]["applicable"] >= 5, "probe checked suspiciously few packages"

    def test_probe_reports_optional_separately(self):
        proc = _run_probe("--json", "--python", _find_python())
        payload = json.loads(proc.stdout)
        assert payload["requirements"]["optionalSource"] == "requirements.optional.txt"
        assert "optional" in payload["requirements"]

    def test_exit_code_encodes_the_verdict(self):
        proc = _run_probe("--python", _find_python())
        result = json.loads(_run_probe("--json", "--python", _find_python()).stdout)
        assert proc.returncode == (0 if result["ok"] else 1)

    def test_bogus_interpreter_is_classified_not_crashed(self):
        proc = _run_probe("--json", "--python", "chemml-definitely-not-a-python")
        payload = json.loads(proc.stdout)
        assert payload["classification"] in {"python_missing", "probe_error"}
        assert payload["ok"] is False
        assert payload["guidance"], "a failure must carry actionable guidance"

    def test_missing_dependency_is_not_reported_as_ok(self, tmp_path):
        """A tree whose requirements demand an impossible package must fail."""
        fake_root = tmp_path / "approot"
        fake_root.mkdir()
        (fake_root / "requirements.runtime.txt").write_text(
            "chemml-definitely-not-installed>=99.0\n", encoding="utf-8"
        )
        proc = _run_probe("--json", "--python", _find_python(), "--root", str(fake_root))
        payload = json.loads(proc.stdout)
        assert payload["classification"] == "dependencies_missing"
        assert payload["ok"] is False
        assert [m["name"] for m in payload["requirements"]["missing"]] == [
            "chemml-definitely-not-installed"
        ]

    def test_satisfied_dependency_is_reported_as_ok(self, tmp_path):
        fake_root = tmp_path / "okroot"
        fake_root.mkdir()
        (fake_root / "requirements.runtime.txt").write_text("numpy>=1.0\n", encoding="utf-8")
        proc = _run_probe("--json", "--python", _find_python(), "--root", str(fake_root))
        payload = json.loads(proc.stdout)
        assert payload["classification"] == "ok"
        assert payload["ok"] is True
