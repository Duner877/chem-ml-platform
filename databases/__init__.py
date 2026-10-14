"""Data layer: vector store + offline reference library.

The platform can talk to PostgreSQL / MongoDB / FAISS (see
``docs/deployment.md``) but it never *requires* them: everything falls back to
the file system and to :mod:`databases.local_library`, which keeps the demo
workflows reproducible on a laptop with no network access.
"""

from __future__ import annotations

from .local_library import (
    COMPOUND_LIBRARY,
    CompoundRecord,
    library_stats,
    search_by_formula,
    search_by_mass,
    search_by_name,
    similar_spectra,
)
from .materials_library import (
    MATERIALS_LIBRARY,
    MaterialRecord,
    materials_stats,
    search_by_element,
    similar_cell,
)
from .vector_store import HAS_FAISS, VectorStore, cosine_matrix

__all__ = [
    "COMPOUND_LIBRARY",
    "CompoundRecord",
    "library_stats",
    "search_by_formula",
    "search_by_mass",
    "search_by_name",
    "similar_spectra",
    "MATERIALS_LIBRARY",
    "MaterialRecord",
    "materials_stats",
    "search_by_element",
    "similar_cell",
    "HAS_FAISS",
    "VectorStore",
    "cosine_matrix",
]
