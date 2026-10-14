"""Subgraph based substructure search and functional group detection.

Two complementary tools are provided:

``has_substructure`` / ``count_substructure``
    Generic query.  Both the molecule and the query are converted to
    attributed graphs and matched with the VF2 implementation of NetworkX.
    Node attributes compared: ``element``, ``aromatic``, ``charge``.
    Bond orders must agree, with one exception: an aromatic bond (order 1.5)
    also matches a plain single bond, so that a Kekulé structure can be
    queried with an aromatic pattern.

``detect_functional_groups``
    A transparent rule engine that walks the atoms/bonds of the molecule and
    counts the functional groups that drive the IR / Raman predictors.
"""

from __future__ import annotations

import functools
from collections import Counter
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

import networkx as nx

from .smiles import MolecularGraph, parse_smiles

__all__ = [
    "to_networkx",
    "has_substructure",
    "count_substructure",
    "iter_substructure_matches",
    "FUNCTIONAL_GROUPS",
    "detect_functional_groups",
]

_NODE_ATTRIBUTES = ("element", "aromatic", "charge")


def to_networkx(graph: MolecularGraph) -> nx.Graph:
    """Convert a :class:`MolecularGraph` into a NetworkX graph."""
    network = nx.Graph()
    for atom in graph.atoms:
        network.add_node(
            atom["index"],
            element=atom.get("element", "C"),
            aromatic="1" if atom.get("aromatic") else "0",
            charge=int(atom.get("charge", 0) or 0),
            hydrogens=int(atom.get("hydrogens", 0) or 0),
        )
    for bond in graph.bonds:
        network.add_edge(
            bond["a"],
            bond["b"],
            aromatic="1" if bond.get("aromatic") else "0",
            order=float(bond.get("order", 1.0)),
        )
    return network


def _node_match(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """``first`` is the molecule node, ``second`` the query node."""
    for attribute in _NODE_ATTRIBUTES:
        if attribute not in second:
            continue
        if str(first.get(attribute)) != str(second.get(attribute)):
            return False
    return True


def _edge_match(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
    """Bond orders must agree; an aromatic bond also matches a single bond."""
    first_order = float(first.get("order", 1.0))
    second_order = float(second.get("order", 1.0))
    if abs(first_order - second_order) < 1e-6:
        return True
    if abs(first_order - 1.5) < 1e-6 and abs(second_order - 1.0) < 1e-6:
        return True
    if abs(second_order - 1.5) < 1e-6 and abs(first_order - 1.0) < 1e-6:
        return True
    return False


@functools.lru_cache(maxsize=512)
def _pattern_graph(pattern_smiles: str) -> nx.Graph:
    return to_networkx(parse_smiles(pattern_smiles))


def iter_substructure_matches(
    graph: MolecularGraph | str, pattern_smiles: str, limit: int = 200
) -> Iterator[Dict[int, int]]:
    """Yield ``{query_atom_index: molecule_atom_index}`` mappings."""
    molecule = parse_smiles(graph) if isinstance(graph, str) else graph
    pattern = _pattern_graph(pattern_smiles)
    if pattern.number_of_nodes() == 0 or pattern.number_of_nodes() > molecule.num_atoms:
        return
    matcher = nx.algorithms.isomorphism.GraphMatcher(
        to_networkx(molecule),
        pattern,
        node_match=_node_match,
        edge_match=_edge_match,
    )
    emitted = 0
    for mapping in matcher.subgraph_monomorphisms_iter():
        yield {value: key for key, value in mapping.items()}
        emitted += 1
        if emitted >= max(1, int(limit)):
            return


def has_substructure(graph: MolecularGraph | str, pattern_smiles: str) -> bool:
    """Return ``True`` when ``pattern_smiles`` occurs in ``graph``."""
    for _ in iter_substructure_matches(graph, pattern_smiles, limit=1):
        return True
    return False


def count_substructure(graph: MolecularGraph | str, pattern_smiles: str, limit: int = 500) -> int:
    """Count distinct occurrences of ``pattern_smiles``."""
    return sum(1 for _ in iter_substructure_matches(graph, pattern_smiles, limit=limit))


#: Ready-made queries for common functional groups (plain SMILES).
FUNCTIONAL_GROUPS: Dict[str, str] = {
    "carboxylic_acid": "CC(=O)O",
    "ester": "CC(=O)OC",
    "amide": "CC(=O)N",
    "ketone": "CC(=O)C",
    "aldehyde": "CC=O",
    "alcohol": "CO",
    "ether": "COC",
    "phenol": "Oc1ccccc1",
    "primary_amine": "CN",
    "nitrile": "CC#N",
    "alkyne": "CC#C",
    "alkene": "CC=C",
    "aromatic_ring": "c1ccccc1",
    "aryl_chloride": "Clc1ccccc1",
    "aryl_bromide": "Brc1ccccc1",
    "nitro": "C[N+](=O)[O-]",
    "sulfone": "CS(=O)(=O)C",
    "thiol": "CS",
}


# --------------------------------------------------------------------------- #
# Functional group rule engine
# --------------------------------------------------------------------------- #
def _element(graph: MolecularGraph, index: int) -> str:
    return str(graph.atoms[index].get("element", "C"))


def _hydrogens(graph: MolecularGraph, index: int) -> int:
    return int(graph.atoms[index].get("hydrogens", 0) or 0)


def _bond_orders(graph: MolecularGraph) -> Dict[Tuple[int, int], float]:
    orders: Dict[Tuple[int, int], float] = {}
    for bond in graph.bonds:
        orders[(bond["a"], bond["b"])] = float(bond["order"])
        orders[(bond["b"], bond["a"])] = float(bond["order"])
    return orders


def _carbonyl_carbons(graph: MolecularGraph) -> Set[int]:
    """Carbon atoms carrying a C=O double bond."""
    orders = _bond_orders(graph)
    carbons: Set[int] = set()
    for index in range(graph.num_atoms):
        if _element(graph, index) != "C":
            continue
        for neighbour, _ in graph.adjacency()[index]:
            if _element(graph, neighbour) == "O" and abs(
                orders.get((index, neighbour), 1.0) - 2.0
            ) < 1e-6:
                carbons.add(index)
                break
    return carbons


def _is_ester_or_acid_oxygen(graph: MolecularGraph, oxygen: int) -> bool:
    """True for the ``-O-`` of a carboxyl group (acid or ester)."""
    orders = _bond_orders(graph)
    for neighbour, order in graph.adjacency()[oxygen]:
        if _element(graph, neighbour) != "C" or abs(float(order) - 1.0) > 1e-6:
            continue
        for outer, outer_order in graph.adjacency()[neighbour]:
            if (
                _element(graph, outer) == "O"
                and abs(float(outer_order) - 2.0) < 1e-6
                and outer != oxygen
            ):
                return True
    return False


def detect_functional_groups(graph: MolecularGraph | str) -> Dict[str, int]:
    """Count the functional groups of ``graph``.

    The rules use only the molecular graph: element identity, bond order,
    aromaticity and the implicit hydrogen counts produced by the SMILES
    parser.  Carbonyl carbons are classified once (acid > ester > amide >
    aldehyde > ketone) so that a single C=O group is never counted twice.
    """
    molecule = parse_smiles(graph) if isinstance(graph, str) else graph
    if not molecule.atoms:
        return {}

    adjacency = molecule.adjacency()
    aromatic_index: Set[int] = {
        atom["index"] for atom in molecule.atoms if atom.get("aromatic")
    }
    orders = _bond_orders(molecule)
    counts: Counter = Counter()

    def bump(name: str, value: int = 1) -> None:
        counts[name] += int(value)

    # -- pass 1: carbonyl carbons ------------------------------------------ #
    claimed_oxygen: Set[int] = set()
    for index in range(molecule.num_atoms):
        if _element(molecule, index) != "C":
            continue
        double_oxygen = None
        for neighbour, order in adjacency[index]:
            if _element(molecule, neighbour) == "O" and abs(float(order) - 2.0) < 1e-6:
                double_oxygen = neighbour
                break
        if double_oxygen is None:
            continue
        claimed_oxygen.add(double_oxygen)

        substituents = [
            (neighbour, order)
            for neighbour, order in adjacency[index]
            if neighbour != double_oxygen
        ]
        other_oxygen = [
            neighbour
            for neighbour, order in substituents
            if _element(molecule, neighbour) == "O"
        ]
        nitrogen = [
            neighbour
            for neighbour, _ in substituents
            if _element(molecule, neighbour) == "N"
        ]
        hydroxyl_oxygen = [
            neighbour
            for neighbour in other_oxygen
            if _hydrogens(molecule, neighbour) > 0
        ]
        ether_like_oxygen = [
            neighbour
            for neighbour in other_oxygen
            if _hydrogens(molecule, neighbour) == 0
            and len(adjacency[neighbour]) == 2
        ]
        if hydroxyl_oxygen:
            bump("carboxylic_acid")
            claimed_oxygen.update(hydroxyl_oxygen)
        elif ether_like_oxygen:
            bump("ester")
            claimed_oxygen.update(ether_like_oxygen)
        elif nitrogen:
            bump("amide")
        elif _hydrogens(molecule, index) > 0:
            bump("aldehyde")
        else:
            bump("ketone")

    # -- pass 2: hetero atoms not part of a carboxyl group ------------------- #
    for index in range(molecule.num_atoms):
        element = _element(molecule, index)
        if element == "O":
            if index in claimed_oxygen:
                continue
            if _hydrogens(molecule, index) > 0:
                carbons = [
                    neighbour
                    for neighbour, _ in adjacency[index]
                    if _element(molecule, neighbour) == "C"
                ]
                if any(carbon in aromatic_index for carbon in carbons):
                    bump("phenol")
                else:
                    bump("alcohol")
            elif len(adjacency[index]) == 2:
                bump("ether")
        elif element == "N":
            hydrogens = _hydrogens(molecule, index)
            triple_carbon = any(
                _element(molecule, neighbour) == "C"
                and abs(float(order) - 3.0) < 1e-6
                for neighbour, order in adjacency[index]
            )
            if triple_carbon:
                bump("nitrile")
            elif hydrogens >= 2:
                bump("primary_amine")
            elif hydrogens == 1:
                if any(
                    _element(molecule, other) == "C"
                    and abs(float(order) - 2.0) < 1e-6
                    for other, order in adjacency[
                        next(n for n, _ in adjacency[index])
                    ]
                ):
                    bump("amide")
                else:
                    bump("secondary_amine")
            else:
                bump("tertiary_amine")
        elif element == "S":
            double_oxygen = sum(
                1
                for neighbour, order in adjacency[index]
                if _element(molecule, neighbour) == "O"
                and abs(float(order) - 2.0) < 1e-6
            )
            if double_oxygen >= 2:
                bump("sulfone")
            elif _hydrogens(molecule, index) > 0:
                bump("thiol")
            else:
                bump("thioether")

    # -- pass 3: unsaturation and skeleton ---------------------------------- #
    for bond in molecule.bonds:
        order = float(bond.get("order", 1.0))
        if abs(order - 2.0) < 1e-6:
            first, second = _element(molecule, bond["a"]), _element(molecule, bond["b"])
            if first == "C" and second == "C":
                counts["alkene"] += 1
        elif abs(order - 3.0) < 1e-6:
            first, second = _element(molecule, bond["a"]), _element(molecule, bond["b"])
            if first == "C" and second == "C":
                counts["alkyne"] += 1

    if aromatic_index:
        counts["aromatic_ring"] += 1
    elif "alkene" not in counts and "alkyne" not in counts:
        counts["alkane"] += 1

    return dict(counts)
