"""Data layer registry: route a file to the adapter that can read it.

Usage::

    from data_layer import ingest, describe

    objects = ingest("datasets/mass_spectrometry/thermo_lcms/sample_01.mzML")
    for obj in objects:
        print(obj.summary(), obj.to_scientific_object())

``ingest`` returns a (possibly empty) list of
:class:`~data_layer.objects.ScientificDataObject`.  When nothing can read the
file the reason is available through :meth:`DataLayerRegistry.explain`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

from data_layer.adapters import DataSourceAdapter, GenericSpectrumAdapter
from data_layer.objects import ScientificDataObject

__all__ = ["DataLayerRegistry", "registry", "register_adapter", "ingest", "describe"]


class DataLayerRegistry:
    """Holds every data source adapter and dispatches reads."""

    def __init__(self) -> None:
        self._adapters: List[DataSourceAdapter] = []

    # -- registration ------------------------------------------------------ #
    def register(self, adapter: DataSourceAdapter | Type[DataSourceAdapter]) -> DataSourceAdapter:
        """Register an adapter instance (or class, which is instantiated)."""
        if isinstance(adapter, type):
            adapter = adapter()
        if not isinstance(adapter, DataSourceAdapter):
            raise TypeError("adapter must subclass DataSourceAdapter")
        self._adapters.append(adapter)
        return adapter

    # -- lookup ------------------------------------------------------------- #
    @property
    def adapters(self) -> List[DataSourceAdapter]:
        return list(self._adapters)

    def adapter_for(self, path: str | Path) -> Optional[DataSourceAdapter]:
        """The first adapter able to read ``path`` (``None`` when unsupported)."""
        for adapter in self._adapters:
            if adapter.can_handle(path):
                return adapter
        return None

    def explain(self, path: str | Path) -> str:
        """Human readable reason why ``path`` cannot be read."""
        suffix = Path(path).suffix.lower()
        if suffix in {".raw", ".d", ".fid", ".ser", ".1r", ".1rr", ".arw",
                      ".yep", ".qgd", ".lcd"}:
            return (
                f"{suffix} is a proprietary container; install the matching "
                "vendor adapter or export to mzML / JCAMP-DX / XY first."
            )
        return f"no adapter claims the extension {suffix!r}"

    # -- reading ------------------------------------------------------------ #
    def ingest(self, path: str | Path, **kwargs: Any) -> List[ScientificDataObject]:
        """Read ``path`` with the first matching adapter."""
        adapter = self.adapter_for(path)
        if adapter is None:
            return []
        return adapter.read(path, **kwargs)

    def ingest_many(
        self, paths: List[str | Path], **kwargs: Any
    ) -> List[ScientificDataObject]:
        """Read several files, skipping the ones no adapter claims."""
        collected: List[ScientificDataObject] = []
        for path in paths:
            collected.extend(self.ingest(path, **kwargs))
        return collected

    # -- introspection ------------------------------------------------------ #
    def describe(self) -> List[Dict[str, Any]]:
        """JSON description of every registered adapter."""
        return [
            {
                "name": adapter.name,
                "vendor": adapter.vendor,
                "extensions": list(adapter.extensions),
                "formats": list(adapter.formats),
                "description": adapter.description,
            }
            for adapter in self._adapters
        ]

    def __len__(self) -> int:
        return len(self._adapters)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<DataLayerRegistry {len(self._adapters)} adapters>"


#: Process wide registry, seeded with the generic adapter.
registry = DataLayerRegistry()
registry.register(GenericSpectrumAdapter())


def register_adapter(adapter: DataSourceAdapter | Type[DataSourceAdapter]) -> DataSourceAdapter:
    """Register an adapter in the process wide data layer registry."""
    return registry.register(adapter)


def ingest(path: str | Path, **kwargs: Any) -> List[ScientificDataObject]:
    """Read ``path`` into universal data objects."""
    return registry.ingest(path, **kwargs)


def describe() -> List[Dict[str, Any]]:
    """JSON description of the registered adapters."""
    return registry.describe()
