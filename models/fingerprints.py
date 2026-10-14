"""Morgan / Weisfeiler-Lehman circular fingerprints.

The implementation follows the original Morgan algorithm: every atom starts
with an invariant derived from its element and environment, then for ``radius``
iterations the invariants of the neighbours are folded in.  Every intermediate
invariant is collected, which is exactly what extended connectivity
fingerprints (ECFP) do.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Set

from .smiles import MolecularGraph, parse_smiles

__all__ = [
    "morgan_fingerprint",
    "morgan_counts",
    "morgan_bits",
    "tanimoto",
    "dice",
    "smiles_similarity",
]

_MASK = 0xFFFFFFFF


def _initial_invariants(graph: MolecularGraph) -> List[int]:
    adjacency = graph.adjacency()
    invariants: List[int] = []
    for atom in graph.atoms:
        neighbours = adjacency[atom["index"]]
        payload = "|".join(
            [
                atom.get("element", "C"),
                str(int(atom.get("charge", 0) or 0)),
                str(int(atom.get("hydrogens", 0) or 0)),
                "1" if atom.get("aromatic") else "0",
                f"{sum(order for _, order in neighbours):.1f}",
                str(len(neighbours)),
            ]
        )
        invariants.append(
            int(hashlib.md5(payload.encode("utf-8")).hexdigest()[:8], 16) & _MASK
        )
    return invariants


def morgan_counts(
    graph: MolecularGraph | str, radius: int = 2
) -> "Counter[int]":
    """Return the multiset of circular substructure hashes."""
    if isinstance(graph, str):
        graph = parse_smiles(graph)
    adjacency = graph.adjacency()
    current = _initial_invariants(graph)
    counts: Counter[int] = Counter(current)

    for _ in range(max(0, int(radius))):
        updated: List[int] = []
        for index in range(len(current)):
            neighbours = sorted(
                current[neighbour] for neighbour, _ in adjacency[index]
            )
            payload = f"{current[index]}:" + ",".join(str(v) for v in neighbours)
            updated.append(
                int(hashlib.md5(payload.encode("utf-8")).hexdigest()[:8], 16) & _MASK
            )
        current = updated
        counts.update(updated)
    return counts


def morgan_bits(
    graph: MolecularGraph | str, radius: int = 2, n_bits: int = 2048
) -> Set[int]:
    """Fold :func:`morgan_counts` into a fixed size set of bit indices."""
    counts = morgan_counts(graph, radius=radius)
    return {hash_value % n_bits for hash_value in counts}


def morgan_fingerprint(
    graph: MolecularGraph | str, radius: int = 2, n_bits: int = 2048
) -> List[int]:
    """Return the fingerprint as a dense ``0/1`` list of length ``n_bits``."""
    bits = morgan_bits(graph, radius=radius, n_bits=n_bits)
    return [1 if index in bits else 0 for index in range(n_bits)]


def tanimoto(left: Iterable[int], right: Iterable[int]) -> float:
    """Tanimoto (Jaccard) similarity of two bit/index collections."""
    a, b = set(left), set(right)
    if not a and not b:
        return 1.0
    union = len(a | b)
    return float(len(a & b) / union) if union else 0.0


def dice(left: Iterable[int], right: Iterable[int]) -> float:
    """Dice similarity of two bit/index collections."""
    a, b = set(left), set(right)
    total = len(a) + len(b)
    return float(2 * len(a & b) / total) if total else 0.0


def smiles_similarity(first: str, second: str, radius: int = 2, n_bits: int = 2048) -> float:
    """Tanimoto similarity between two SMILES strings."""
    return tanimoto(
        morgan_bits(first, radius=radius, n_bits=n_bits),
        morgan_bits(second, radius=radius, n_bits=n_bits),
    )
