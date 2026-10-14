"""Instrument vendor adapters (Thermo / Waters / Agilent / Bruker / Shimadzu).

Importing this package registers every adapter in the process wide
:class:`data_layer.registry.DataLayerRegistry`, which is what makes the
``Instrument -> Parser -> Vendor Adapter -> Scientific Object -> Feature
Extraction`` pipeline from the specification work end to end::

    from nodes.instruments import vendor_adapters  # noqa: F401
    from data_layer import ingest

    objects = ingest("datasets/mass_spectrometry/bruker_nmr/sample_01.d")

The adapter order matters: Bruker and Shimadzu are checked before the
directory-based Thermo/Waters/Agilent adapters because several vendors claim
the same ``.d`` / ``.raw`` extensions.
"""

from __future__ import annotations

from data_layer.registry import DataLayerRegistry, registry
from nodes.instruments.vendor_adapters.agilent import AgilentAdapter
from nodes.instruments.vendor_adapters.base import (
    VENDOR_ADAPTERS,
    VendorAdapter,
    centroid,
    extract_features,
    features_to_table,
    to_wavenumber,
)
from nodes.instruments.vendor_adapters.bruker import (
    BrukerAdapter,
    parse_bruker_parameter_file,
    read_bruker_1r,
)
from nodes.instruments.vendor_adapters.shimadzu import (
    ShimadzuAdapter,
    read_spc,
)
from nodes.instruments.vendor_adapters.thermo import ThermoAdapter
from nodes.instruments.vendor_adapters.waters import WatersAdapter

__all__ = [
    "AgilentAdapter",
    "BrukerAdapter",
    "ShimadzuAdapter",
    "ThermoAdapter",
    "WatersAdapter",
    "VendorAdapter",
    "centroid",
    "extract_features",
    "features_to_table",
    "to_wavenumber",
    "read_bruker_1r",
    "read_spc",
    "parse_bruker_parameter_file",
    "register_all",
    "describe_adapters",
]


def register_all(target_registry: DataLayerRegistry | None = None) -> list[str]:
    """Register every vendor adapter (idempotent) and return their names."""
    reg = target_registry or registry
    known = {type(adapter).__name__ for adapter in reg.adapters}
    added: list[str] = []
    for adapter_cls in (BrukerAdapter, ShimadzuAdapter, AgilentAdapter, ThermoAdapter, WatersAdapter):
        if adapter_cls.__name__ in known:
            continue
        reg.register(adapter_cls())
        known.add(adapter_cls.__name__)
        added.append(adapter_cls.__name__)
    return added


def describe_adapters() -> list[dict]:
    """JSON description of the registered vendor adapters."""
    return registry.describe()


#: Registration happens on import so that simply importing the node package is
#: enough to teach the data layer about proprietary containers.
register_all()
