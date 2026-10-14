"""Universal Scientific Data Layer.

One envelope for every scientific datum that enters the platform, no matter
whether it originates from an instrument file, a database query or a built-in
simulator::

    from data_layer import ingest, wrap, ScientificDataObject

    # 1. raw file -> universal envelope -> typed scientific object
    objects = ingest("datasets/mass_spectrometry/thermo_lcms/sample_01.mzML")
    spectrum = objects[0].to_scientific_object()

    # 2. or wrap something you already have
    envelope = ScientificDataObject.wrap(
        spectrum, source="synthetic", format="simulated",
        data_pointer="output/run_1/artifacts/spectrum.json",
    )

Layout
------
=========================  ==================================================
``data_layer.objects``     :class:`ScientificDataObject` envelope + wrap/unwrap
``data_layer.metadata``    controlled vocabularies, provenance, normalisation
``data_layer.adapters``    :class:`DataSourceAdapter` base + generic reader
``data_layer.registry``    adapter registry and ``ingest()`` dispatcher
``data_layer.catalog``     persistent, searchable index of ingested objects
=========================  ==================================================
"""

from __future__ import annotations

from data_layer.adapters import (
    DataSourceAdapter,
    GenericSpectrumAdapter,
    sniff_format,
    sniff_vendor,
)
from data_layer.metadata import (
    CANONICAL_KEYS,
    DATA_TYPES,
    GENERIC_FORMATS,
    VENDORS,
    VENDOR_FORMATS,
    DataProvenance,
    infer_data_type,
    normalise_metadata,
)
from data_layer.catalog import CATALOG_PATH, DataCatalog, catalog, get_catalog
from data_layer.objects import ScientificDataObject, unwrap, wrap
from data_layer.registry import (
    DataLayerRegistry,
    describe,
    ingest,
    register_adapter,
    registry,
)

__version__ = "0.7.1"

__all__ = [
    "ScientificDataObject",
    "DataSourceAdapter",
    "GenericSpectrumAdapter",
    "DataLayerRegistry",
    "DataCatalog",
    "DataProvenance",
    "wrap",
    "unwrap",
    "ingest",
    "describe",
    "register_adapter",
    "registry",
    "catalog",
    "get_catalog",
    "CATALOG_PATH",
    "sniff_format",
    "sniff_vendor",
    "infer_data_type",
    "normalise_metadata",
    "VENDORS",
    "VENDOR_FORMATS",
    "GENERIC_FORMATS",
    "DATA_TYPES",
    "CANONICAL_KEYS",
    "__version__",
]
