"""Static check: no node module uses a class name it never imported.

Why this exists (v0.7.3, found while building workflow 10):

``nodes/io.py`` used ``ScientificReport`` inside ``ExportNode``'s markdown
branch while the module imported ``Image, Molecule, ScientificObject,
Spectrum, Table, Text`` -- and not that one.  Nothing caught it.  ``py_compile``
passes (the name is a legal global reference), the import-time check passes
(nothing is executed yet), and every previously shipped workflow exported JSON
or CSV, so the branch had never run.  The first workflow to export a report as
Markdown failed at runtime with ``name 'ScientificReport' is not defined``.

A missing import is invisible to every tool that does not *execute the exact
line*, and a platform whose whole point is running many combinations of nodes
cannot rely on someone happening to click that path.  So the check is static:
it reads the AST and compares loaded names against what the module actually
binds.  Cheap enough to run over the whole package, and it catches the class of
bug rather than one instance.

Deliberately conservative: it only looks at names starting with an uppercase
letter, which is where classes live.  Lowercase misses are left to the linter,
because parameter shadowing makes them far too noisy to flag here.

v0.7.4: the node implementations moved from ``nodes/`` into the device-grouped
``custom_nodes/`` packages.  The scan follows them there -- pointing it at the
old directory would have made it scan a single facade file and pass forever,
which is the failure mode a guard is supposed to prevent.
"""

from __future__ import annotations

import ast
import builtins
import pathlib
import typing

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
NODES = ROOT / "custom_nodes"
#: The legacy import facade.  It contains no node implementations, but it is
#: still Python source that must not reference a class it never imported.
LEGACY = ROOT / "nodes"


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name the module makes available as a global."""
    names = set(dir(builtins)) | set(dir(typing))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.alias):
            # ``from x import *`` -- unknowable statically, so trust it.
            names.add("*")
    return names


def _unbound_class_names(path: pathlib.Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _bound_names(tree)
    loaded = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    return {name for name in loaded - bound if name[:1].isupper()}


def _module_files() -> list[pathlib.Path]:
    """Every node source file, in both the new and the legacy tree.

    The scan must cover the legacy facade as well: it is Python source that
    names classes, and a missing import there fails exactly the same way.
    """
    files = [p for p in NODES.rglob("*.py") if "__pycache__" not in p.parts]
    files += [
        p for p in LEGACY.rglob("*.py") if "__pycache__" not in p.parts
    ]
    return sorted(files)


def test_the_scanner_would_have_caught_the_real_defect():
    """Guard the guard: the scanner must flag the bug it was written for.

    A static check that cannot fail is indistinguishable from no check.  This
    feeds it the exact pre-fix shape -- a module that uses a class it never
    imported -- and demands it be reported.
    """
    source = (
        "from workflow_engine.objects import Table\n"
        "\n"
        "def render(item):\n"
        "    if isinstance(item, ScientificReport):\n"
        "        return item.markdown()\n"
        "    return str(item)\n"
    )
    tree = ast.parse(source)
    bound = _bound_names(tree)
    loaded = {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    assert "ScientificReport" in {n for n in loaded - bound if n[:1].isupper()}


def test_it_ignores_a_properly_imported_name():
    source = (
        "from workflow_engine.objects import ScientificReport, Table\n"
        "\n"
        "def render(item):\n"
        "    if isinstance(item, ScientificReport):\n"
        "        return item.markdown()\n"
        "    return str(Table)\n"
    )
    tree = ast.parse(source)
    bound = _bound_names(tree)
    loaded = {
        n.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    assert not {n for n in loaded - bound if n[:1].isupper()}


def test_export_module_imports_what_it_uses():
    """The concrete regression: ``ExportNode`` renders ``ScientificReport``."""
    # v0.7.4: ``nodes/io.py`` became ``custom_nodes/data_io/io.py``.
    io_module = NODES / "data_io" / "io.py"
    text = io_module.read_text(encoding="utf-8")
    assert "isinstance(item, ScientificReport)" in text, (
        "if the markdown branch was renamed this test must be revisited, not "
        "quietly deleted"
    )
    assert not _unbound_class_names(io_module)


@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_no_node_module_uses_an_unimported_class(path: pathlib.Path):
    missing = _unbound_class_names(path)
    assert not missing, (
        f"{path.relative_to(ROOT)} uses {sorted(missing)} without importing it "
        "-- this only fails when that exact line runs"
    )
