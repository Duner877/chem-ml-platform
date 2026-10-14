"""Vector store for spectral / molecular embeddings.

FAISS is used when it is installed; otherwise a NumPy brute force backend with
exactly the same public API is used.  The store is intentionally tiny: it is
meant for in-process retrieval augmentation (spectral library search, molecule
similarity, report retrieval), not for production scale indexing.
"""

from __future__ import annotations

import json
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

__all__ = ["VectorStore", "cosine_matrix", "HAS_FAISS"]

try:  # pragma: no cover - depends on the environment
    import faiss  # type: ignore

    HAS_FAISS = True
except ImportError:  # pragma: no cover
    faiss = None  # type: ignore[assignment]
    HAS_FAISS = False


def _as_matrix(vectors: Any) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim == 1:
        array = array.reshape(1, -1)
    return array


def cosine_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity between ``query`` rows and ``matrix`` rows."""
    query_norm = np.linalg.norm(query, axis=1, keepdims=True)
    matrix_norm = np.linalg.norm(matrix, axis=1, keepdims=True).T
    query_norm[query_norm == 0] = 1.0
    matrix_norm[matrix_norm == 0] = 1.0
    return (query / query_norm) @ (matrix / matrix_norm).T


class VectorStore:
    """Flat IP index over L2 normalised vectors."""

    def __init__(self, dim: int | None = None, backend: str = "auto") -> None:
        self.dim = dim
        self.backend = backend
        self.vectors: List[np.ndarray] = []
        self.ids: List[str] = []
        self.metadata: List[Dict[str, Any]] = []
        self._index = None

    # -- mutation ------------------------------------------------------------- #
    def add(
        self,
        vectors: Sequence[Sequence[float]] | np.ndarray,
        ids: Optional[Sequence[str]] = None,
        metadata: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> None:
        """Add vectors (rows) to the store."""
        matrix = _as_matrix(vectors)
        if self.dim is None:
            self.dim = int(matrix.shape[1])
        if matrix.shape[1] != self.dim:
            raise ValueError(
                f"Vector dimension {matrix.shape[1]} does not match store dim {self.dim}"
            )
        for offset, row in enumerate(matrix):
            self.vectors.append(row.astype(np.float32))
            self.ids.append(
                str(ids[offset]) if ids and offset < len(ids) else f"v{len(self.ids)}"
            )
            self.metadata.append(
                dict(metadata[offset])
                if metadata and offset < len(metadata)
                else {}
            )
        self._index = None

    def clear(self) -> None:
        """Remove every vector."""
        self.vectors.clear()
        self.ids.clear()
        self.metadata.clear()
        self._index = None

    # -- query ---------------------------------------------------------------- #
    def search(
        self, vectors: Sequence[Sequence[float]] | np.ndarray, top_k: int = 5
    ) -> List[List[Dict[str, Any]]]:
        """Return the ``top_k`` most similar entries for each query row."""
        if not self.vectors:
            return [[] for _ in range(np.asarray(vectors).shape[0] if np.ndim(vectors) > 1 else 1)]
        query = _as_matrix(vectors)
        matrix = np.vstack(self.vectors)
        scores = cosine_matrix(query, matrix)
        results: List[List[Dict[str, Any]]] = []
        for row in scores:
            order = np.argsort(-row)[: max(1, int(top_k))]
            results.append(
                [
                    {
                        "id": self.ids[index],
                        "score": round(float(row[index]), 4),
                        "metadata": dict(self.metadata[index]),
                    }
                    for index in order
                ]
            )
        return results

    # -- persistence ---------------------------------------------------------- #
    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as handle:
            pickle.dump(
                {
                    "dim": self.dim,
                    "ids": self.ids,
                    "metadata": self.metadata,
                    "vectors": [np.asarray(v) for v in self.vectors],
                },
                handle,
            )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "VectorStore":
        with Path(path).open("rb") as handle:
            payload = pickle.load(handle)
        store = cls(dim=payload["dim"])
        store.ids = list(payload["ids"])
        store.metadata = [dict(item) for item in payload["metadata"]]
        store.vectors = [np.asarray(item) for item in payload["vectors"]]
        return store

    def __len__(self) -> int:
        return len(self.vectors)
