"""The gate's own scope must be honest (ISSUE-26).

The ``python_compile`` stage reports "N first-party files compiled", and the
release report quotes that number as evidence of what was checked.  The
desktop payload tests build full copies of the Python tree under
``output/pytest_gate_tmp/``; the stage counted those fixtures as well, so the
reported number grew with every gate run (2663 -> 3479 -> 4296) while the tree
itself holds a couple of hundred first-party files.  A count that silently
absorbs leftover test state is exactly the "field exists but carries no
conclusion" failure mode this release set out to remove.

The counting scope and the ``compileall`` skip pattern are now derived from a
single set; these tests pin that property.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location(
        "quality_gate_under_test", ROOT / "scripts" / "quality_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    # ``@dataclass`` resolves its annotations through ``sys.modules`` -- a
    # module that only exists as a local variable makes it raise a bare
    # ``AttributeError`` (see ISSUE-12 and the loader in ci_pipeline.py).
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return module


class TestCompileScopeCountsFirstPartySourceOnly:
    def test_runtime_state_is_never_counted(self, gate):
        # ``tempfile`` rather than pytest's ``tmp_path`` on purpose: when the
        # gate drives pytest, ``tmp_path`` lives under
        # ``output/pytest_gate_tmp/`` -- the very directory this scope
        # excludes -- so a synthetic tree built there would vanish entirely.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "nodes").mkdir()
            (root / "nodes" / "real.py").write_text("x = 1\n", encoding="utf-8")
            fixture = root / "output" / "pytest_gate_tmp" / "run1_0" / "app"
            fixture.mkdir(parents=True)
            (fixture / "chemml_version.py").write_text("x = 1\n", encoding="utf-8")
            (root / ".pytest_cache").mkdir()
            (root / ".pytest_cache" / "leftover.py").write_text("x = 1\n", encoding="utf-8")

            counted = sorted(p.name for p in gate._first_party_python_files(root))
            assert counted == ["real.py"]

    def test_live_tree_holds_no_runtime_state(self, gate):
        counted = gate._first_party_python_files()
        assert counted, "the sweep found no first-party source at all"
        assert all("output" not in p.parts for p in counted)
        assert all(".pytest_cache" not in p.parts for p in counted)

    def test_skip_pattern_excludes_the_same_dirs_as_the_count(self, gate):
        pattern = re.compile(gate._COMPILEALL_SKIP)
        for name in gate._NON_SOURCE_DIRS:
            assert pattern.search(f"/repo/{name}/module.py"), name
        assert not pattern.search("/repo/nodes/module.py")
        assert not pattern.search("/repo/backend/routers/api.py")
