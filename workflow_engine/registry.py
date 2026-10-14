"""Node registry: discovery, instantiation and introspection."""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Type

from .errors import NodeNotFoundError
from .node_base import ScientificNode

__all__ = ["NodeRegistry", "registry", "register_node", "get_registry"]


class NodeRegistry:
    """Holds every known node class, indexed by type name and aliases."""

    def __init__(self) -> None:
        self._classes: Dict[str, Type[ScientificNode]] = {}
        self._aliases: Dict[str, str] = {}

    # -- registration ------------------------------------------------------ #
    def register(
        self,
        node_cls: Type[ScientificNode],
        type_name: Optional[str] = None,
        aliases: Optional[List[str]] = None,
    ) -> Type[ScientificNode]:
        if not (inspect.isclass(node_cls) and issubclass(node_cls, ScientificNode)):
            raise TypeError("A node must be a ScientificNode subclass")
        canonical = type_name or node_cls.__name__
        self._classes[canonical] = node_cls
        for alias in list(aliases or []) + list(getattr(node_cls, "aliases", [])):
            self._aliases[alias] = canonical
        return node_cls

    # -- lookup ------------------------------------------------------------- #
    def resolve(self, type_name: str) -> str:
        if type_name in self._classes:
            return type_name
        if type_name in self._aliases:
            return self._aliases[type_name]
        raise NodeNotFoundError(type_name, self._classes.keys())

    def get(self, type_name: str) -> Type[ScientificNode]:
        return self._classes[self.resolve(type_name)]

    def has(self, type_name: str) -> bool:
        try:
            self.resolve(type_name)
            return True
        except NodeNotFoundError:
            return False

    def create(
        self, type_name: str, node_id: str = "", params: Optional[Dict[str, Any]] = None
    ) -> ScientificNode:
        return self.get(type_name)(node_id=node_id, params=params)

    def types(self) -> List[str]:
        return sorted(self._classes)

    def __len__(self) -> int:
        return len(self._classes)

    def __contains__(self, type_name: str) -> bool:
        return self.has(type_name)

    def __iter__(self) -> Iterator[str]:
        return iter(self.types())

    # -- introspection ------------------------------------------------------ #
    def specs(self) -> List[Dict[str, Any]]:
        return [self._classes[name].spec() for name in self.types()]

    def categories(self) -> List[Dict[str, Any]]:
        buckets: Dict[str, List[Dict[str, Any]]] = {}
        for name in self.types():
            spec = self._classes[name].spec()
            buckets.setdefault(spec["category"], []).append(spec)
        return [
            {"name": key, "nodes": value, "count": len(value)}
            for key, value in sorted(buckets.items())
        ]

    def spec(self, type_name: str) -> Dict[str, Any]:
        return self.get(type_name).spec()

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Simple case-insensitive search over name/category/tags/description."""
        needle = (query or "").strip().lower()
        if not needle:
            return self.specs()
        results = []
        for name in self.types():
            cls = self._classes[name]
            haystack = " ".join(
                [
                    cls.name,
                    cls.category,
                    cls.description,
                    " ".join(cls.tags),
                    " ".join(cls.aliases),
                    name,
                ]
            ).lower()
            if needle in haystack:
                results.append(cls.spec())
        return results

    # -- discovery ---------------------------------------------------------- #
    def discover_package(self, package: str = "nodes") -> List[str]:
        """Import every module of ``package`` so that nodes self-register."""
        imported: List[str] = []
        try:
            pkg = importlib.import_module(package)
        except ImportError:
            return imported
        for module_info in pkgutil.walk_packages(
            pkg.__path__, prefix=f"{pkg.__name__}."
        ):
            name = module_info.name
            if ".tests" in name or name.endswith("._tests"):
                continue
            try:
                importlib.import_module(name)
                imported.append(name)
            except Exception as exc:  # pragma: no cover - plugin isolation
                print(f"[registry] failed to import {name}: {exc}")
        return imported

    def discover_plugins(self, directory: str | Path) -> List[str]:
        """Load ``*.py`` files from ``directory`` as external node plugins."""
        loaded: List[str] = []
        base = Path(directory)
        if not base.exists():
            return loaded
        for path in sorted(base.glob("*.py")):
            if path.name.startswith("_"):
                continue
            spec = importlib.util.spec_from_file_location(
                f"chemml_plugin_{path.stem}", path
            )
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(module)
                loaded.append(str(path))
            except Exception as exc:  # pragma: no cover - plugin isolation
                print(f"[registry] plugin {path} failed: {exc}")
        return loaded


#: Global registry used by the backend, the SDK and the test-suite.
registry = NodeRegistry()


def get_registry() -> NodeRegistry:
    """Return the global node registry."""
    return registry


def register_node(
    cls: Type[ScientificNode] | None = None,
    *,
    type_name: str | None = None,
    aliases: Optional[List[str]] = None,
):
    """Class decorator registering a node in the global registry.

    Usage::

        @register_node
        class MyNode(ScientificNode):
            ...

    """

    def decorator(node_cls: Type[ScientificNode]) -> Type[ScientificNode]:
        registry.register(node_cls, type_name=type_name, aliases=aliases)
        return node_cls

    if cls is None:
        return decorator
    return decorator(cls)
