"""Regression tests for the legacy import facade (``nodes.*``).

Moving the node implementations into ``custom_nodes/`` must not break a
single existing import.  The facade exists precisely so that nobody has to
audit several hundred call sites by hand -- but a facade that answers
*differently depending on how it was reached* is worse than no facade at
all, because the failure is order-dependent and therefore intermittent.

Two properties are locked here.

1. **Every name 0.7.3 exported is still reachable.**  The baseline is read
   out of the 0.7.3 release commit, not copied into this file: a test that
   embeds its own copy of the expectation keeps passing after the
   production code is broken, which is the exact opposite of what a
   regression test is for.

2. **The facade answers the same way on both paths.**  There are two ways
   in: the meta-path finder (used when the import happens after
   ``nodes`` is loaded) and the eager pre-population done at import time.
   They used to be two copies of the same aggregation loop, and they
   drifted -- the eager copy ignored the modern package's own ``__all__``,
   so ``from nodes.agent import __version__`` broke while the finder path
   still worked.  Whichever path runs first must not decide the answer.
"""

from __future__ import annotations

import ast
import importlib
import io
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, List, Set

import pytest

REPO = Path(__file__).resolve().parent.parent

#: The 0.7.3 release commit -- the last tree in which the node library still
#: lived under ``nodes/``.  It is the only honest baseline for "what did the
#: old import paths export".
BASELINE_COMMIT = "b7c0580"

#: Legacy umbrella packages, each of which used to be a real package with an
#: ``__init__.py`` of its own.
UMBRELLA_PACKAGES = (
    "ai",
    "instruments",
    "simulation",
    "agent",
    "databases",
    "question",
    "gpu",
)


def _baseline_exports(package: str) -> Set[str]:
    """The ``__all__`` of ``nodes/<package>/__init__.py`` in 0.7.3.

    Read from git rather than pasted here: a pasted list is a second
    source of truth, and it is the one that goes stale.
    """
    archive = subprocess.run(
        ["git", "archive", BASELINE_COMMIT, f"nodes/{package}"],
        cwd=str(REPO),
        capture_output=True,
    )
    if archive.returncode != 0 or not archive.stdout:
        pytest.skip(f"cannot read {BASELINE_COMMIT}:nodes/{package} from git")
    with tempfile.TemporaryDirectory() as tmp:
        with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
            tar.extractall(tmp)
        init = Path(tmp) / "nodes" / package / "__init__.py"
        if not init.exists():
            pytest.skip(f"{BASELINE_COMMIT}:nodes/{package} has no __init__.py")
        tree = ast.parse(init.read_text(encoding="utf-8", errors="ignore"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    return {
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant)
                    }
    pytest.skip(f"{BASELINE_COMMIT}:nodes/{package} has no __all__")


# --------------------------------------------------------------------------- #
# 1. Nothing that 0.7.3 exported may disappear
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("package", UMBRELLA_PACKAGES)
def test_every_baseline_export_is_still_reachable(package: str) -> None:
    """Every name 0.7.3 exported from ``nodes.<package>`` still resolves."""
    import nodes  # noqa: F401  -- installs the facade as a side effect

    umbrella = importlib.import_module(f"nodes.{package}")
    baseline = _baseline_exports(package)
    missing = sorted(name for name in baseline if not hasattr(umbrella, name))
    assert not missing, (
        f"nodes.{package} no longer exports {missing}; "
        f"0.7.3 exported {len(baseline)} names"
    )


@pytest.mark.parametrize("package", UMBRELLA_PACKAGES)
def test_the_baseline_is_not_empty(package: str) -> None:
    """Guard the guard: a baseline that silently reads empty passes forever.

    If the git archive stops working, every comparison above would compare
    against the empty set and report success.  This asserts the baseline
    actually has content.
    """
    baseline = _baseline_exports(package)
    assert len(baseline) >= 5, (
        f"0.7.3 nodes.{package} exported only {len(baseline)} names -- "
        "the baseline is probably broken, not the facade"
    )


def test_agent_package_exports_the_version_marker() -> None:
    """``from nodes.agent import __version__`` worked in 0.7.3.

    The name lives on the modern *package* (``custom_nodes.agent``), not on
    any of its sub-modules, so aggregating only the sub-modules drops it.
    """
    import nodes  # noqa: F401

    umbrella = importlib.import_module("nodes.agent")
    assert hasattr(umbrella, "__version__")
    assert hasattr(umbrella, "INTENT_KEYWORDS")


# --------------------------------------------------------------------------- #
# 2. Both entry paths must answer identically
# --------------------------------------------------------------------------- #


def _fingerprint(package: str) -> Dict[str, str]:
    """Which object each exported name resolves to, by qualified name."""
    umbrella = importlib.import_module(f"nodes.{package}")
    out: Dict[str, str] = {}
    for name in getattr(umbrella, "__all__", []) or []:
        value = getattr(umbrella, name, None)
        out[name] = f"{type(value).__module__}.{type(value).__name__}"
    return out


@pytest.mark.parametrize("package", UMBRELLA_PACKAGES)
def test_the_finder_path_and_the_eager_path_agree(package: str) -> None:
    """Rebuilding the umbrella from scratch must reproduce the same names.

    ``nodes/__init__.py`` installs the aliases at import time, so the
    umbrella the application actually sees was built by the eager path.  The
    finder path is what a late import would use.  If the two disagree, the
    outcome depends on import order -- an intermittent bug that only shows
    up under some entry points.
    """
    import nodes

    eager = _fingerprint(package)
    rebuilt = nodes._build_umbrella(f"nodes.{package}")
    rebuilt_names = {
        name
        for name in (getattr(rebuilt, "__all__", []) or [])
        if hasattr(rebuilt, name)
    }
    assert rebuilt_names == set(eager), (
        f"nodes.{package}: the eager facade exports {len(eager)} names "
        f"but rebuilding it yields {len(rebuilt_names)}"
    )


def test_the_shared_builder_is_used_by_both_paths() -> None:
    """The two paths must not carry separate copies of the aggregation.

    A duplicated loop is how the two drifted in the first place.  This
    asserts the finder delegates to the shared builder rather than
    re-implementing it.
    """
    import nodes

    source = Path(nodes.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    finder = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "_LegacyNodeFinder":
            finder = node
    assert finder is not None, "the legacy finder class is gone"

    create_module = None
    for node in finder.body:
        if isinstance(node, ast.FunctionDef) and node.name == "create_module":
            create_module = node
    assert create_module is not None, "the finder no longer builds umbrellas"

    called = {
        node.func.id
        for node in ast.walk(create_module)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_build_umbrella" in called, (
        "create_module re-implements the aggregation instead of calling "
        "the shared builder -- the two paths can drift again"
    )


# --------------------------------------------------------------------------- #
# 3. The aliased modules are the same objects, not copies
# --------------------------------------------------------------------------- #


def test_aliased_modules_are_the_same_object() -> None:
    """``nodes.agent.agent`` and ``custom_nodes.agent.agent`` are one module.

    The facade used to hand the import machinery the modern module's own
    ``__spec__``, whose ``name`` is the modern path; the machinery then
    re-executed the source file and registered the result under the modern
    key.  Two module objects for one file means ``monkeypatch`` lands on a
    copy the runtime never calls.
    """
    import nodes  # noqa: F401

    legacy = importlib.import_module("nodes.agent.agent")
    modern = importlib.import_module("custom_nodes.agent.agent")
    assert legacy is modern


def test_the_node_class_is_the_same_object_across_both_paths() -> None:
    """``isinstance`` must hold across the legacy and modern paths."""
    import nodes  # noqa: F401

    from custom_nodes.agent.agent import ScientificAgentNode as Modern
    from nodes.agent.agent import ScientificAgentNode as Legacy

    assert Legacy is Modern
    assert isinstance(Modern("n1", {}), Legacy)


def test_the_facade_is_installed_at_import_time() -> None:
    """A test module importing ``nodes.agent.planner`` during collection
    must not see ``ModuleNotFoundError``.

    Waiting for an explicit ``load_nodes()`` call would turn a missing
    alias into a *collection* error, which reads like a broken test file
    rather than a missing facade.
    """
    import nodes

    assert any(
        type(finder).__name__ == "_LegacyNodeFinder" for finder in sys_meta_path()
    )


def sys_meta_path() -> List[object]:
    import sys

    return list(sys.meta_path)


def test_the_legacy_loader_still_finds_every_node() -> None:
    """The facade must still discover and register all nodes.

    Imported through the *legacy* path on purpose: ``nodes.loader`` only
    resolves because the facade maps it onto ``custom_nodes.loader``.
    """
    from nodes.loader import get_registry

    registry = get_registry()
    types = registry.types()
    assert len(types) >= 100, f"only {len(types)} node types were registered"


# --------------------------------------------------------------------------- #
# 3. The command line entry point must survive the move too
# --------------------------------------------------------------------------- #
#
# ``python -m nodes.loader`` has been in the docs, in ``CONTRIBUTING.md`` and
# in ``docs/deployment.md`` since 0.7.3.  It is the command a user runs when a
# third party node does not show up, and the command the platform prints in
# its own troubleshooting table.  Moving the implementation must not have
# broken it -- and it did, twice, in ways no import test would have caught:
#
#   * ``runpy`` asks the *loader* for the module's code, not for an imported
#     module.  The facade's alias loader had no ``get_code``, so the command
#     died with ``AttributeError: '_AliasLoader' object has no attribute
#     'get_code'`` while ``from nodes.loader import get_registry`` worked.
#
#   * The wrapper in ``custom_nodes/loader.py`` *shadows* the identically
#     named function of the ``nodes`` package, and was written without the
#     ``plugins`` parameter.  Every ``--plugins`` run therefore raised
#     ``TypeError: load_nodes() takes 0 positional arguments but 1 was given``.
#
# Both are silent for ``import`` and loud for the command, which is exactly
# the class of defect that only a subprocess can catch.


def _run_loader(module: str, *args: str) -> subprocess.CompletedProcess:
    """Run ``python -m <module> <args>`` in a fresh interpreter."""
    import sys

    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.mark.parametrize("module", ["nodes.loader", "custom_nodes.loader"])
def test_loader_cli_runs_on_both_paths(module: str) -> None:
    """Both the legacy and the modern command must produce the listing."""
    result = _run_loader(module, "--stats")

    assert result.returncode == 0, (
        f"`python -m {module} --stats` failed with {result.returncode}:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "TOTAL" in result.stdout, (
        f"`python -m {module} --stats` printed no statistics table:\n"
        f"{result.stdout}"
    )


@pytest.mark.parametrize("module", ["nodes.loader", "custom_nodes.loader"])
def test_loader_cli_accepts_the_plugins_option(module: str) -> None:
    """``--plugins`` must not raise -- the wrapper shadows a 1-arg function.

    The option existed in 0.7.3 and points at a folder of third party nodes,
    which is precisely the situation a user hits when a node "is missing".
    """
    with tempfile.TemporaryDirectory() as tmp:
        result = _run_loader(module, "--stats", "--plugins", tmp)

    assert result.returncode == 0, (
        f"`python -m {module} --plugins <dir>` failed with {result.returncode}:\n"
        f"{result.stdout}\n{result.stderr}"
    )


def test_the_loader_wrapper_keeps_the_shadowed_signature() -> None:
    """``custom_nodes.loader.load_nodes`` must accept the plugins folder.

    The wrapper shadows ``nodes.load_nodes``.  A signature that is narrower
    than the function it shadows is a defect that only shows up at the call
    site, so it is asserted directly rather than inferred from the CLI.
    """
    import inspect

    from custom_nodes import loader as modern_loader

    parameters = inspect.signature(modern_loader.load_nodes).parameters
    assert "plugins_directory" in parameters, (
        "custom_nodes.loader.load_nodes dropped the plugins_directory "
        f"parameter; it now has {list(parameters)}"
    )

