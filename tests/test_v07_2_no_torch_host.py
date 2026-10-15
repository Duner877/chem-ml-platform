"""v0.7.2 regression test: runs must survive a machine without torch.

The installed desktop app runs on whatever Python the host provides, and that
interpreter often has no torch.  ``collect_environment`` used to dereference
``torch`` inside its own ``except`` handler, so on such a machine the import
failure left the name unbound and every workflow run died with

    UnboundLocalError: cannot access local variable 'torch'

before a single node executed -- the UI just showed a run that never started.
The developer virtualenv has torch, so only a torch-less host exposed it.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def without_torch(monkeypatch):
    """Make ``import torch`` fail, the way a bare host interpreter behaves."""
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    for module in [m for m in sys.modules if m == "torch" or m.startswith("torch.")]:
        monkeypatch.delitem(sys.modules, module, raising=False)
    yield


class TestEnvironmentCollectionWithoutTorch:
    def test_collect_environment_survives_missing_torch(self, without_torch):
        from provenance.schema import collect_environment

        info = collect_environment()
        assert info.torch_version == ""
        assert info.cuda_available is False
        assert info.gpu_names == []

    def test_provenance_collector_constructs_without_torch(self, without_torch):
        """The collector is built before any node runs, so this is the gate."""
        from provenance.collector import ProvenanceCollector

        collector = ProvenanceCollector("run_no_torch", workflow=None)
        assert collector.environment is not None

    def test_workflow_runs_without_torch(self, without_torch):
        """End to end: the run must complete, not abort during collection."""
        from nodes.loader import get_registry
        from workflow_engine import Workflow, WorkflowEngine

        workflow = Workflow.from_file(
            ROOT / "workflows" / "01_unknown_compound_identification.json"
        )
        engine = WorkflowEngine(
            registry=get_registry(),
            workdir=str(ROOT / "output" / "pytest_no_torch"),
            max_workers=1,
            use_cache=False,
        )
        result = engine.run(workflow, run_id="pytest_no_torch")
        assert result.status == "completed", result.errors
        assert result.records


class TestNoDanglingTorchReference:
    def test_handler_never_touches_an_unbound_torch(self):
        """Static guard: no ``except`` body may reference ``torch``.

        A handler that mentions ``torch`` is only safe when the import it
        guards is known to have bound the name.  The broken version read
        ``torch.cuda`` in the handler, which is precisely the failure mode, so
        the rule is simply stated: handlers do not mention it.
        """
        source = (ROOT / "provenance" / "schema.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            for handler in node.handlers:
                for inner in ast.walk(handler):
                    if isinstance(inner, ast.Name) and inner.id == "torch":
                        offenders.append(inner.lineno)
                    if isinstance(inner, ast.Attribute) and isinstance(
                        inner.value, ast.Name
                    ):
                        if inner.value.id == "torch":
                            offenders.append(inner.lineno)
        assert not offenders, f"except handler references torch at lines {offenders}"

    def test_no_duplicate_except_clauses_in_shipped_sources(self):
        """A doubled handler is the fingerprint of the bad patch."""
        offenders = []
        for path in ROOT.rglob("*.py"):
            parts = set(path.parts)
            if parts & {".venv", "node_modules", "__pycache__", "output", "dist", ".git"}:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Try) and len(node.handlers) >= 2:
                    kinds = [
                        ast.dump(h.type) if h.type else "bare" for h in node.handlers
                    ]
                    if len(set(kinds)) != len(kinds):
                        offenders.append(
                            f"{path.relative_to(ROOT)}:{node.lineno}"
                        )
        assert not offenders, offenders