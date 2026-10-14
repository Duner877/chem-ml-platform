"""v0.7.1 node capability / controlled-execution tests (tasks E and F).

* capability tags and the honest status grade are declared and exported;
* the registry reports a node whose external program is missing as
  ``unavailable`` -- it never pretends the computation ran;
* the :class:`ControlledRunner` only launches allowlisted programs, passes an
  explicit argv (no shell), isolates the working directory and cleans up.
"""

from __future__ import annotations

import sys
import time

import pytest

from node_registry import scan, node_status
from node_registry.capabilities import GRADES, resolve_software
from nodes.loader import get_registry
from simulations.controlled import (
    TOOL_ALLOWLIST,
    ControlledRunner,
    ExternalToolError,
    ExternalToolNotAllowed,
    ExternalToolUnavailable,
    describe_tools,
    runner,
)


class TestDeclaration:
    def test_spec_exports_capability_fields(self):
        spec = get_registry().get("PubChemNode").spec()
        assert "capabilities" in spec
        assert "requires_network" in spec["capabilities"]
        assert spec["implementation_status"] in GRADES
        assert spec["deterministic"] is True

    def test_gpu_nodes_declare_gpu_capability(self):
        spec = get_registry().get("GpuDeviceInfoNode").spec()
        assert "requires_gpu" in spec["capabilities"]

    def test_simulation_connectors_are_experimental(self):
        status = node_status(get_registry().get("ORCANode"))
        assert "requires_external_software" in status["capabilities"]
        assert status["implementation_status"] == "experimental"
        assert status["required_software"]

    def test_nondeterministic_nodes_flagged(self):
        from nodes.ai.prediction import TrainModelNode

        assert TrainModelNode.deterministic is False
        assert "nondeterministic" in TrainModelNode.effective_capabilities()


class TestHonestGrading:
    def test_missing_external_software_is_unavailable(self):
        # No ORCA on a typical CI box -> the node must report 'unavailable'.
        status = node_status(get_registry().get("ORCANode"))
        if resolve_software("orca") is None:
            assert status["availability"] == "unavailable"
            assert "orca" in status["missing_software"]

    def test_registry_rollup_is_consistent(self):
        report = scan()
        total = sum(report["availability_summary"].values())
        assert total == report["total_nodes"]
        assert set(report["availability_summary"]) <= set(GRADES)

    def test_validated_grade_only_when_declared(self):
        # No node may claim 'validated' without a declared benchmark grade.
        report = scan()
        for node in report["nodes"]:
            if node["availability"] == "validated":
                assert node["implementation_status"] == "validated"


class TestControlledRunner:
    def test_unknown_tool_is_rejected(self):
        with pytest.raises(ExternalToolNotAllowed):
            runner.run("rm_rf_everything", [])

    def test_missing_allowlisted_tool_reports_unavailable(self):
        runner.resolve("orca")  # allowed
        if resolve_software("orca") is None:
            with pytest.raises(ExternalToolUnavailable):
                runner.run("orca", ["input.inp"])

    def test_describe_tools_is_honest(self):
        report = describe_tools()
        keys = {item["key"] for item in report}
        assert "orca" in keys and "gromacs" in keys
        for item in report:
            if not item["installed"]:
                assert item["path"] == ""
                assert item["version"] == ""

    def test_runs_allowlisted_program_with_explicit_argv(self, tmp_path, monkeypatch):
        from simulations.controlled import ExternalToolSpec

        spec = ExternalToolSpec(key="probe", executable=sys.executable,
                                description="python probe", domain="test")
        monkeypatch.setitem(TOOL_ALLOWLIST, "probe", spec)
        result = ControlledRunner().run(
            "probe", ["-c", "print('hello-controlled')"], timeout=30
        )
        assert result["success"] is True
        assert "hello-controlled" in result["stdout"]
        assert result["backend"].startswith("external:")

    def test_no_shell_interpretation(self, tmp_path, monkeypatch):
        """A shell metacharacter must be passed as a literal argv entry."""
        from simulations.controlled import ExternalToolSpec

        spec = ExternalToolSpec(key="probe2", executable=sys.executable,
                                description="python probe", domain="test")
        monkeypatch.setitem(TOOL_ALLOWLIST, "probe2", spec)
        marker = tmp_path / "pwned.txt"
        # If a shell were used, `>` would create the marker.
        ControlledRunner().run(
            "probe2",
            ["-c", "print('safe')", ";", "touch", str(marker)],
            workdir=tmp_path,
            timeout=30,
        )
        assert not marker.exists()

    def test_scratch_directory_is_cleaned_up(self, monkeypatch):
        from simulations.controlled import ExternalToolSpec

        spec = ExternalToolSpec(key="probe3", executable=sys.executable,
                                description="python probe", domain="test")
        monkeypatch.setitem(TOOL_ALLOWLIST, "probe3", spec)
        result = ControlledRunner().run("probe3", ["-c", "print(1)"], timeout=30)
        import os

        assert not os.path.exists(result["workdir"])

    def test_concurrency_is_bounded(self):
        r = ControlledRunner(max_concurrency=3)
        assert r.max_concurrency == 3
        assert r.active == 0

    def test_timeout_terminates_the_child_and_cleans_up(self, tmp_path, monkeypatch):
        """Spec P1-03: "超时任务会被可靠终止或标记为终止失败".

        Raising an exception is not enough -- the child must actually stop.
        The probe writes a heartbeat counter until it is killed, so a frozen
        counter after the timeout proves termination without needing an OS
        process API.  The scratch directory must also be removed.
        """
        from simulations.controlled import ExternalToolSpec

        spec = ExternalToolSpec(key="probe_slow", executable=sys.executable,
                                description="slow probe", domain="test")
        monkeypatch.setitem(TOOL_ALLOWLIST, "probe_slow", spec)

        heartbeat = tmp_path / "beats.txt"
        script = (
            "import time, pathlib, sys\n"
            f"p = pathlib.Path({str(heartbeat)!r})\n"
            "n = 0\n"
            "while True:\n"
            "    n += 1\n"
            "    p.write_text(str(n), encoding='utf-8')\n"
            "    time.sleep(0.1)\n"
        )
        with pytest.raises(ExternalToolError) as excinfo:
            ControlledRunner().run(
                "probe_slow", ["-c", script], workdir=tmp_path, timeout=1.5
            )
        assert "timed out" in str(excinfo.value).lower()

        # The child updated the counter at least once before the timeout.
        assert heartbeat.exists(), "probe never started"
        frozen = int(heartbeat.read_text(encoding="utf-8"))
        time.sleep(1.0)
        after = int(heartbeat.read_text(encoding="utf-8"))
        assert after == frozen, (
            f"child kept running after the timeout ({frozen} -> {after}): "
            "the task was abandoned, not terminated"
        )

    def test_timeout_cleans_the_scratch_directory(self, monkeypatch):
        """A timed-out task must not leave a half-written scratch directory."""
        import os

        from simulations.controlled import ExternalToolSpec

        spec = ExternalToolSpec(key="probe_slow2", executable=sys.executable,
                                description="slow probe", domain="test")
        monkeypatch.setitem(TOOL_ALLOWLIST, "probe_slow2", spec)

        seen = {}

        import simulations.controlled as controlled

        real_mkdtemp = controlled.tempfile.mkdtemp

        def spy_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            seen["dir"] = path
            return path

        monkeypatch.setattr(controlled.tempfile, "mkdtemp", spy_mkdtemp)
        with pytest.raises(ExternalToolError):
            ControlledRunner().run(
                "probe_slow2",
                ["-c", "import time; time.sleep(30)"],
                timeout=1.0,
            )
        assert seen.get("dir"), "runner did not create a scratch directory"
        assert not os.path.exists(seen["dir"]), (
            "timed-out task left its scratch directory behind"
        )
