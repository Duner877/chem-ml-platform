"""A small, dependency-free SMILES parser.

The parser builds a molecular graph (atoms + bonds) good enough for descriptor
calculation, formula assignment and the message passing network of
:mod:`models.mpnn`.  It supports:

* organic subset atoms (``B C N O P S F Cl Br I`` and aromatic ``b c n o p s``)
* bracketed atoms ``[13NH4+]`` (isotope, symbol, H count, charge, chirality)
* bond symbols ``- = # $ : / \\``
* branches ``( )``, ring closures ``1`` .. ``9`` and ``%nn``
* disconnected fragments ``.``

Stereochemistry markers are consumed and stored in ``atom["chiral"]`` but are
not used for any calculation.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "MolecularGraph",
    "parse_smiles",
    "to_smiles",
    "validate_smiles",
    "SmilesParseError",
    "ORGANIC_SUBSET",
    "AROMATIC_SUBSET",
    "COVALENT_VALENCES",
]

ORGANIC_SUBSET = ("Cl", "Br", "B", "C", "N", "O", "P", "S", "F", "I", "H")
AROMATIC_SUBSET = ("b", "c", "n", "o", "p", "s", "se", "as")

#: Maximum number of bonds an element of the organic subset can form.
COVALENT_VALENCES: Dict[str, int] = {
    "B": 3,
    "C": 4,
    "N": 3,
    "O": 2,
    "P": 3,
    "S": 2,
    "F": 1,
    "Cl": 1,
    "Br": 1,
    "I": 1,
    "H": 1,
}

_AROMATIC_VALENCES: Dict[str, int] = {
    "b": 3,
    "c": 3,
    "n": 3,
    "o": 2,
    "p": 3,
    "s": 2,
    "se": 2,
    "as": 3,
}

_BOND_ORDERS = {
    "-": 1.0,
    "=": 2.0,
    "#": 3.0,
    "$": 4.0,
    ":": 1.5,
    "/": 1.0,
    "\\": 1.0,
}

_BOND_SYMBOL = {1.0: "", 2.0: "=", 3.0: "#", 4.0: "$", 1.5: ":"}

_TOKEN_RE = re.compile(
    r"""
      (\[[^\]]*\])                          # bracketed atom
    | (Cl|Br|Si|Se|As|B|C|N|O|P|S|F|I)      # organic subset (upper case)
    | (se|as|b|c|n|o|p|s)                   # aromatic subset
    | ([-=#:$\\/])                          # bond symbols
    | ([()])                                # branches
    | (%[0-9]{2}|[0-9])                     # ring bonds
    | (\.)                                  # disconnection
    """,
    re.VERBOSE,
)

_BRACKET_RE = re.compile(
    r"^\[(?P<isotope>\d+)?(?P<symbol>[A-Za-z][a-z]?)"
    r"(?P<chiral>@{1,2})?(?P<hcount>H\d*)?"
    r"(?P<charge>[+-]{1,2}\d*|[+-]\d+)?\]$"
)


class SmilesParseError(ValueError):
    """Raised when a SMILES string cannot be parsed."""


class MolecularGraph:
    """Container for the parsed structure with a few convenience helpers."""

    def __init__(self, atoms: List[Dict[str, Any]], bonds: List[Dict[str, Any]]):
        self.atoms = atoms
        self.bonds = bonds

    # -- basic properties ---------------------------------------------------- #
    @property
    def num_atoms(self) -> int:
        return len(self.atoms)

    @property
    def num_bonds(self) -> int:
        return len(self.bonds)

    def adjacency(self) -> Dict[int, List[Tuple[int, float]]]:
        """Adjacency list with bond orders."""
        neighbours: Dict[int, List[Tuple[int, float]]] = {
            i: [] for i in range(self.num_atoms)
        }
        for bond in self.bonds:
            neighbours[bond["a"]].append((bond["b"], float(bond["order"])))
            neighbours[bond["b"]].append((bond["a"], float(bond["order"])))
        return neighbours

    def degrees(self) -> List[int]:
        adjacency = self.adjacency()
        return [len(adjacency[i]) for i in range(self.num_atoms)]

    def components(self) -> List[List[int]]:
        """Connected components (iterative BFS)."""
        adjacency = self.adjacency()
        seen: set = set()
        groups: List[List[int]] = []
        for start in range(self.num_atoms):
            if start in seen:
                continue
            queue = [start]
            seen.add(start)
            group: List[int] = []
            while queue:
                current = queue.pop(0)
                group.append(current)
                for neighbour, _ in adjacency[current]:
                    if neighbour not in seen:
                        seen.add(neighbour)
                        queue.append(neighbour)
            groups.append(sorted(group))
        return groups

    def rings(self) -> int:
        """Number of rings (cyclomatic number = bonds - atoms + components)."""
        return max(0, self.num_bonds - self.num_atoms + len(self.components()))

    def ring_atoms(self) -> set:
        """Atoms that belong to at least one cycle."""
        adjacency = self.adjacency()
        state = [0] * self.num_atoms  # 0 = unvisited, 1 = on stack, 2 = done
        in_ring: set = set()

        for start in range(self.num_atoms):
            if state[start]:
                continue
            stack: List[Tuple[int, Optional[int], int]] = [(start, None, 0)]
            path: List[int] = []
            while stack:
                node, parent, phase = stack.pop()
                if phase == 0:
                    if state[node] == 1:
                        continue
                    state[node] = 1
                    path.append(node)
                    stack.append((node, parent, 1))
                    for neighbour, _ in adjacency[node]:
                        if neighbour == parent:
                            continue
                        if state[neighbour] == 1:
                            index = path.index(neighbour)
                            in_ring.update(path[index:])
                        elif state[neighbour] == 0:
                            stack.append((neighbour, node, 0))
                else:
                    state[node] = 2
                    if path and path[-1] == node:
                        path.pop()
        return in_ring

    def aromatic_rings(self) -> int:
        """Approximate number of aromatic rings."""
        aromatic_in_ring = {
            i
            for i in self.ring_atoms()
            if i < self.num_atoms and self.atoms[i].get("aromatic")
        }
        if not aromatic_in_ring:
            return 0
        return max(1, int(round(len(aromatic_in_ring) / 6.0)))

    def formula(self) -> "Counter[str]":
        """Element counts including implicit hydrogens."""
        counts: Counter[str] = Counter()
        for atom in self.atoms:
            counts[atom["element"]] += 1
            hydrogens = int(atom.get("hydrogens", 0) or 0)
            if hydrogens:
                counts["H"] += hydrogens
        return counts

    def formula_string(self) -> str:
        """Hill notation of :meth:`formula` (``C`` first, then ``H``)."""
        counts = self.formula()
        ordered: List[Tuple[str, int]] = []
        if "C" in counts:
            ordered.append(("C", counts.pop("C")))
            if "H" in counts:
                ordered.append(("H", counts.pop("H")))
        ordered.extend(sorted(counts.items()))
        return "".join(
            f"{element}{number if number > 1 else ''}" for element, number in ordered
        )

    def to_dict(self) -> Dict[str, Any]:
        return {"atoms": list(self.atoms), "bonds": list(self.bonds)}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<MolecularGraph {self.num_atoms} atoms, {self.num_bonds} bonds>"


# --------------------------------------------------------------------------- #
# Tokenisation
# --------------------------------------------------------------------------- #
def _tokenize(smiles: str) -> List[str]:
    tokens: List[str] = []
    text = str(smiles or "").strip()
    position = 0
    while position < len(text):
        match = _TOKEN_RE.match(text, position)
        if match is None:
            raise SmilesParseError(
                f"Unexpected character {text[position]!r} at position {position} "
                f"in SMILES {smiles!r}"
            )
        tokens.append(match.group(0))
        position = match.end()
    return tokens


def _parse_bracket(token: str) -> Dict[str, Any]:
    match = _BRACKET_RE.match(token)
    if match is None:
        raise SmilesParseError(f"Cannot parse bracket atom {token!r}")
    symbol = match.group("symbol")
    charge_token = match.group("charge") or ""
    charge = 0
    if charge_token:
        sign = -1 if charge_token[0] == "-" else 1
        digits = re.sub(r"[^0-9]", "", charge_token)
        if digits:
            charge = sign * int(digits)
        else:
            charge = sign * len(charge_token.rstrip("0123456789") or charge_token[0])
    hcount_token = match.group("hcount") or ""
    hydrogens = 0
    if hcount_token:
        digits = re.sub(r"[^0-9]", "", hcount_token)
        hydrogens = int(digits) if digits else 1
    return {
        "index": 0,
        "element": symbol[0].upper() + symbol[1:],
        "aromatic": symbol.islower(),
        "charge": charge,
        "hydrogens": hydrogens,
        "isotope": int(match.group("isotope")) if match.group("isotope") else None,
        "chiral": match.group("chiral") or "",
        # Bracketed atoms always state their hydrogen count explicitly,
        # so the implicit valence model must not overwrite it.
        "explicit_h": True,
    }


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #
def parse_smiles(smiles: str) -> MolecularGraph:
    """Parse ``smiles`` and return a :class:`MolecularGraph`."""
    text = str(smiles or "").strip()
    if not text:
        raise SmilesParseError("Empty SMILES string")

    atoms: List[Dict[str, Any]] = []
    bonds: List[Dict[str, Any]] = []
    pending_bond: Optional[str] = None
    previous: Optional[int] = None
    ring_open: Dict[int, Tuple[int, Optional[str]]] = {}
    branch_stack: List[Optional[int]] = []

    for token in _tokenize(text):
        if token == "(":
            branch_stack.append(previous)
            continue
        if token == ")":
            previous = branch_stack.pop() if branch_stack else previous
            continue
        if token == ".":
            previous = None
            pending_bond = None
            continue
        if token in _BOND_ORDERS:
            pending_bond = token
            continue
        if token.startswith("%") or token.isdigit():
            ring_id = int(token[1:]) if token.startswith("%") else int(token)
            if previous is None:
                raise SmilesParseError(
                    f"Ring closure {token!r} without a preceding atom in {text!r}"
                )
            if ring_id in ring_open:
                other, other_bond = ring_open.pop(ring_id)
                symbol = pending_bond or other_bond or ""
                order = _BOND_ORDERS.get(symbol, 1.0)
                bonds.append(
                    {
                        "a": other,
                        "b": previous,
                        "order": order,
                        "aromatic": order == 1.5,
                    }
                )
            else:
                ring_open[ring_id] = (previous, pending_bond)
            pending_bond = None
            continue

        # -- atoms ------------------------------------------------------------ #
        if token.startswith("["):
            atom = _parse_bracket(token)
        elif token in ORGANIC_SUBSET:
            atom = {
                "index": 0,
                "element": token,
                "aromatic": False,
                "charge": 0,
                "hydrogens": 0,
                "isotope": None,
                "chiral": "",
            }
        else:
            element = token[0].upper() + token[1:]
            atom = {
                "index": 0,
                "element": element,
                "aromatic": True,
                "charge": 0,
                "hydrogens": 0,
                "isotope": None,
                "chiral": "",
            }
        index = len(atoms)
        atom["index"] = index
        atoms.append(atom)

        if previous is not None:
            previous_aromatic = bool(atoms[previous].get("aromatic"))
            if pending_bond:
                order = _BOND_ORDERS[pending_bond]
            elif previous_aromatic and atom["aromatic"]:
                order = 1.5
            else:
                order = 1.0
            bonds.append(
                {"a": previous, "b": index, "order": order, "aromatic": order == 1.5}
            )
        previous = index
        pending_bond = None

    _assign_implicit_hydrogens(atoms, bonds)
    return MolecularGraph(atoms, bonds)


def _assign_implicit_hydrogens(
    atoms: List[Dict[str, Any]], bonds: List[Dict[str, Any]]
) -> None:
    """Fill ``atom["hydrogens"]`` using a simple valence model."""
    neighbours: Dict[int, List[float]] = {i: [] for i in range(len(atoms))}
    for bond in bonds:
        neighbours[bond["a"]].append(float(bond["order"]))
        neighbours[bond["b"]].append(float(bond["order"]))

    for atom in atoms:
        if atom.get("explicit_h"):
            # Bracketed atoms already state their hydrogen count.
            continue
        element = atom.get("element", "C")
        if atom.get("aromatic"):
            valence = _AROMATIC_VALENCES.get(element.lower(), 3)
            used = float(len(neighbours[atom["index"]]))
        else:
            valence = COVALENT_VALENCES.get(element, 4)
            used = float(sum(neighbours[atom["index"]]))
        charge = abs(int(atom.get("charge", 0) or 0))
        atom["hydrogens"] = max(0, int(round(valence - used - charge)))


def validate_smiles(smiles: str) -> tuple[bool, str]:
    """Return ``(is_valid, message)`` for ``smiles``."""
    try:
        graph = parse_smiles(smiles)
    except SmilesParseError as exc:
        return False, str(exc)
    if graph.num_atoms == 0:
        return False, "SMILES contains no atoms"
    return True, f"OK: {graph.formula_string()} ({graph.num_atoms} heavy atoms)"


# --------------------------------------------------------------------------- #
# Writer (deterministic, non-canonical)
# --------------------------------------------------------------------------- #
def to_smiles(graph: MolecularGraph) -> str:
    """Serialise a :class:`MolecularGraph` back to SMILES.

    A depth first traversal assigns the main chain, branches are wrapped in
    parentheses and every back edge receives a ring-closure digit (``%nn``
    above 9).  The result is deterministic but *not* a canonical SMILES.
    """
    if graph.num_atoms == 0:
        return ""

    def _atom_token(atom: Dict[str, Any]) -> str:
        element = atom.get("element", "C")
        aromatic = bool(atom.get("aromatic"))
        hydrogens = int(atom.get("hydrogens", 0) or 0)
        charge = int(atom.get("charge", 0) or 0)
        needs_bracket = (
            charge != 0
            or atom.get("isotope") is not None
            or atom.get("chiral")
            or (not aromatic and element not in ORGANIC_SUBSET and hydrogens > 0)
        )
        if not needs_bracket:
            return element.lower() if aromatic else element
        body = element.lower() if aromatic else element
        if hydrogens:
            body += "H" + (str(hydrogens) if hydrogens > 1 else "")
        if charge:
            magnitude = abs(charge)
            sign = "+" if charge > 0 else "-"
            suffix = str(magnitude) if magnitude > 1 else ""
            body += sign + suffix
        return "[" + body + "]"

    adjacency = graph.adjacency()
    for key in adjacency:
        adjacency[key].sort(key=lambda item: (-item[1], item[0]))

    visited = [False] * graph.num_atoms
    used_edges: set = set()
    ring_counter = [1]
    ring_digits: Dict[int, List[str]] = defaultdict(list)

    def _next_digit() -> str:
        value = ring_counter[0]
        ring_counter[0] += 1
        return "%" + format(value, "02d") if value >= 10 else str(value)

    def _walk(node: int) -> str:
        visited[node] = True
        children: List[Tuple[int, float]] = []
        for neighbour, order in adjacency[node]:
            key = (min(node, neighbour), max(node, neighbour))
            if visited[neighbour] or key in used_edges:
                if key not in used_edges:
                    # Back edge -> ring closure, digit on both endpoints.
                    used_edges.add(key)
                    digit = _next_digit()
                    ring_digits[node].append(
                        _BOND_SYMBOL.get(float(order), "") + digit
                    )
                    ring_digits[neighbour].append(digit)
                continue
            children.append((neighbour, order))

        if not children:
            return _atom_token(graph.atoms[node]) + "".join(ring_digits[node])

        # The continuation is the neighbour with the largest degree: it keeps
        # the main chain long and pushes substituents into branches.
        degrees = graph.degrees()
        cont_index = max(
            range(len(children)),
            key=lambda i: (degrees[children[i][0]], -children[i][0]),
        )
        cont_neighbour, cont_order = children[cont_index]
        used_edges.add((min(node, cont_neighbour), max(node, cont_neighbour)))
        continuation = _BOND_SYMBOL.get(float(cont_order), "") + _walk(cont_neighbour)

        branches: List[str] = []
        for index, (neighbour, order) in enumerate(children):
            if index == cont_index or visited[neighbour]:
                continue
            used_edges.add((min(node, neighbour), max(node, neighbour)))
            branches.append(
                "(" + _BOND_SYMBOL.get(float(order), "") + _walk(neighbour) + ")"
            )

        return (
            _atom_token(graph.atoms[node])
            + "".join(ring_digits[node])
            + "".join(branches)
            + continuation
        )

    fragments: List[str] = []
    for start in range(graph.num_atoms):
        if not visited[start]:
            fragments.append(_walk(start))
    return ".".join(fragments)
