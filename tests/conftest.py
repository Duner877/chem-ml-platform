"""Shared pytest fixtures and the test-suite classification policy.

Spec task P0-03 requires the test corpus to have *one* set of collection rules
and a *declared* boundary between unit / integration / security / benchmark /
desktop tests, so the release report can state "22 security tests passed"
and have that number mean something reproducible.

The classification lives here, in one table, rather than as scattered
``@pytest.mark`` decorators: a marker on a function is invisible in a diff
review of the suite inventory, whereas a filename table can be audited at a
glance and provably covers every file (see :func:`pytest_collection_modifyitems`).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

#: The five declared suites (spec P0-03 #2).  Exactly one applies to every test.
SUITE_MARKERS = ("unit", "integration", "security", "benchmark", "desktop")

#: Extra orthogonal marker: tests whose result depends on the *host*, not the
#: code (GPU present, external solver installed, network reachable).  These are
#: allowed -- and expected -- to SKIP, and the gate counts them separately.
ENV_MARKER = "requires_env"

#: Filename stem -> suite.  Order does not matter; lookup is exact.
SUITE_BY_STEM: Dict[str, str] = {
    # -- security: authentication, authorisation, upload/path safety ----------
    "test_v07_1_security": "security",
    "test_v07_1_upload_stream": "security",
    "test_v07_1_capabilities": "security",
    "test_v07_2_ws_security": "security",
    "test_v07_storage": "security",
    "test_v07_storage_api": "security",
    "test_v07_2_capability_provenance": "security",
    # -- benchmark: known-answer / regression thresholds ----------------------
    "test_v07_1_benchmark": "benchmark",
    "test_v07_2_node_known_answers": "benchmark",
    # -- desktop: Electron shell, runtime probe, installer wiring -------------
    "test_v07_2_desktop_runtime": "desktop",
    "test_v07_4_desktop_syntax": "desktop",
    # -- integration: multi-module behaviour through the real engine/API ------
    "test_engine": "integration",
    "test_workflows": "integration",
    "test_v06": "integration",
    "test_v07_engine_provenance": "integration",
    "test_v07_provenance": "integration",
    "test_v07_1_agent_runtime": "integration",
    "test_v07_agent_state": "integration",
    "test_v07_report": "integration",
    "test_v07_1_report_provenance": "integration",
    "test_v07_2_provenance_reproducibility": "integration",
    "test_v07_1_dataset_quality": "integration",
    "test_v07_errors": "integration",
    "test_v07_1_license_report": "integration",
    "test_v07_gpu": "integration",
    # Solid-state engine + agent planning path: pure-function physics checks
    # alongside one full engine run, so the whole file is classified as
    # integration rather than falling through to the unit default.
    "test_v07_3_solid_state": "integration",
    # Model-catalogue parsing / selection plus static checks of the TypeScript
    # theme contract: no network, but it reads real frontend and desktop sources.
    "test_v07_3_model_list_and_theme": "integration",
    # Software update: the backend endpoints, the version comparison and the
    # GUI entry point (which is asserted by reading the frontend sources) --
    # so it spans two modules and is classified as integration.
    "test_v07_4_update": "integration",
    "test_v07_4_legacy_facade": "integration",
    # -- unit: single-module behaviour ---------------------------------------
    "test_nodes": "unit",
    "test_v07_2_version_consistency": "unit",
    "test_v07_2_gate_scope": "unit",
}

#: Files that may not run without a specific host capability.
ENV_DEPENDENT_STEMS = ("test_v07_gpu",)

#: Anything not listed above and not matched by a rule falls back to ``unit``,
#: but the fallback is recorded so the gate can flag an unclassified new file.
_DEFAULT_SUITE = "unit"

_FALLBACKS: List[str] = []


@pytest.fixture(scope="session")
def registry():
    """The fully populated global node registry."""
    from nodes.loader import get_registry

    return get_registry()


@pytest.fixture(scope="session")
def workflow_files():
    """Every stored demo workflow."""
    return sorted((ROOT / "workflows").glob("*.json"))


def _suite_for(stem: str) -> str:
    if stem in SUITE_BY_STEM:
        return SUITE_BY_STEM[stem]
    for prefix in ENV_DEPENDENT_STEMS:
        if stem == prefix or stem.startswith(prefix + "_"):
            return _DEFAULT_SUITE
    _FALLBACKS.append(stem)
    return _DEFAULT_SUITE


def pytest_collection_modifyitems(config, items):  # noqa: ARG001 - pytest hook
    """Tag every collected test with exactly one suite marker (+ env if needed)."""
    for item in items:
        stem = Path(str(item.fspath)).stem
        item.add_marker(getattr(pytest.mark, _suite_for(stem)))
        if stem in ENV_DEPENDENT_STEMS or stem.startswith(tuple(s + "_" for s in ENV_DEPENDENT_STEMS)):
            item.add_marker(getattr(pytest.mark, ENV_MARKER))


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    """Report the per-suite census so a run is self-describing.

    Only the ``call`` phase is counted: pytest also emits ``setup`` and
    ``teardown`` reports per test, and counting those inflates every figure
    roughly threefold -- which is precisely the kind of unverifiable number the
    release report must not contain.
    """
    counts: Dict[str, int] = {marker: 0 for marker in SUITE_MARKERS}
    for reports in terminalreporter.stats.values():
        for report in reports:
            if getattr(report, "when", "call") != "call":
                continue
            keywords = getattr(report, "keywords", None) or {}
            for marker in SUITE_MARKERS:
                if marker in keywords:
                    counts[marker] += 1
                    break
    if any(counts.values()):
        terminalreporter.write_sep("-", "suite census (call phase)")
        for marker in SUITE_MARKERS:
            terminalreporter.write_line(f"  {marker:<12} {counts[marker]}")
        terminalreporter.write_line(f"  {'total':<12} {sum(counts.values())}")
    if _FALLBACKS:
        terminalreporter.write_line(
            "  unclassified test files (defaulted to unit): " + ", ".join(sorted(set(_FALLBACKS)))
        )
