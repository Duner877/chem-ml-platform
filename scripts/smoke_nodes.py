#!/usr/bin/env python
"""Instantiate and execute **every** registered node with synthetic inputs.

The script is the acceptance check for requirement *"所有文件必须可以运行"*:
a node that cannot be instantiated, cannot be introspected or raises at
execution time is reported as a failure.

Usage
-----
    python scripts/smoke_nodes.py                 # run everything
    python scripts/smoke_nodes.py --filter NMR    # only matching types
    python scripts/smoke_nodes.py --list          # just list the types
    python scripts/smoke_nodes.py --quiet         # only the summary
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from nodes.loader import get_registry  # noqa: E402
from workflow_engine.objects import (  # noqa: E402
    Component,
    CrystalStructure,
    Image,
    Material,
    Molecule,
    Peak,
    Reaction,
    ScientificReport,
    SpectralMatch,
    Spectrum,
    Table,
    Text,
)


# --------------------------------------------------------------------------- #
# synthetic data factory
# --------------------------------------------------------------------------- #
def make_spectrum() -> Spectrum:
    """A small synthetic mass spectrum."""
    x = np.arange(50.0, 500.0, 0.5)
    y = np.zeros_like(x)
    for centre, intensity in ((57.0, 30.0), (91.0, 65.0), (149.0, 100.0), (207.0, 42.0)):
        y += intensity * np.exp(-0.5 * ((x - centre) / 0.6) ** 2)
    spectrum = Spectrum.from_arrays(
        x, y, mode="MS", x_unit="m/z", y_unit=" intensity", name="sample MS"
    )
    spectrum.technique = "MS"
    spectrum.polarity = "positive"
    spectrum.precursor_mz = 207.0
    spectrum.peaks = [
        Peak(x=57.0, y=30.0, intensity=30.0, label="57.000"),
        Peak(x=91.0, y=65.0, intensity=65.0, label="91.000"),
        Peak(x=149.0, y=100.0, intensity=100.0, label="149.000"),
        Peak(x=207.0, y=42.0, intensity=42.0, label="207.000"),
    ]
    return spectrum


def make_molecule() -> Molecule:
    """Caffeine as a synthetic molecule object."""
    from nodes._helpers import build_molecule

    return build_molecule(
        "CN1C=NC2=C1C(=O)N(C)C(=O)N2", name="caffeine", confidence=0.9, with_coords=True
    )


def make_material() -> Material:
    """A synthetic cathode material."""
    from nodes._helpers import build_material

    return build_material(
        "LiFePO4",
        name="LFP",
        lattice={"a": 10.33, "b": 6.01, "c": 4.69,
                 "alpha": 90.0, "beta": 90.0, "gamma": 90.0},
        spacegroup="Pnma",
        crystal_system="orthorhombic",
        properties={"capacity_mAh_g": 170.0, "voltage_V": 3.45},
        phase="solid",
        synthesis="solid-state",
    )


def make_table() -> Table:
    """A small numeric table (no SMILES column)."""
    return Table(
        columns=["sample", "capacity", "retention"],
        rows=[["A", 168.2, 0.94], ["B", 152.7, 0.91], ["C", 175.4, 0.97]],
        name="measurements",
    )


def make_library() -> Table:
    """A molecule library table with the mandatory ``smiles`` column."""
    return Table(
        columns=["smiles", "name", "solubility"],
        rows=[
            ["CCO", "ethanol", 0.68],
            ["CCCO", "propanol", 0.42],
            ["c1ccccc1", "benzene", 0.11],
            ["CC(=O)O", "acetic acid", 0.91],
            ["CN1C=NC2=C1C(=O)N(C)C(=O)N2", "caffeine", 0.21],
        ],
        name="molecule library",
    )


def make_material_table() -> Table:
    """A candidate library for material discovery (formula column)."""
    return Table(
        columns=["formula", "name", "capacity_mAh_g", "voltage_V"],
        rows=[
            ["LiFePO4", "LFP", 170.0, 3.45],
            ["LiCoO2", "LCO", 274.0, 3.90],
            ["LiNi0.8Mn0.1Co0.1O2", "NMC811", 200.0, 3.75],
            ["LiMn2O4", "spinel", 148.0, 4.05],
        ],
        name="material candidates",
    )


def make_training_set() -> Table:
    """A regression table with a SMILES column and a numeric target."""
    return Table(
        columns=["smiles", "name", "target"],
        rows=[
            ["CCO", "ethanol", -0.31],
            ["CCCO", "propanol", 0.12],
            ["CCCCCO", "pentanol", 1.02],
            ["c1ccccc1", "benzene", 1.89],
            ["CO", "methanol", -0.85],
            ["CC(=O)O", "acetic acid", -0.17],
            ["CN1C=NC2=C1C(=O)N(C)C(=O)N2", "caffeine", 1.44],
            ["CCCCCC", "hexane", 2.31],
        ],
        name="training set",
    )


def make_image() -> Image:
    """A synthetic greyscale micrograph."""
    yy, xx = np.mgrid[0:64, 0:64]
    array = 0.5 + 0.5 * np.sin(xx / 6.0) * np.cos(yy / 8.0)
    return Image.from_array(array, pixel_size=2.5, pixel_unit="nm", name="micrograph")


def make_text() -> Text:
    """A short free-text note."""
    return Text(
        text="Unknown white solid isolated from the reaction crude; "
        "soluble in methanol, insoluble in hexane.",
        language="en",
        name="lab note",
    )


def make_match() -> SpectralMatch:
    """A synthetic library match container."""
    return SpectralMatch(
        query="207.09",
        library="MassBank",
        matches=[
            {"name": "caffeine", "score": 0.93, "formula": "C8H10N4O2"},
            {"name": "theophylline", "score": 0.71, "formula": "C7H8N4O2"},
        ],
        name="library hit",
    )


def make_report() -> ScientificReport:
    """A one section synthetic report."""
    report = ScientificReport(title="Synthetic report", abstract="generated by smoke test")
    report.add_section("Methods", "No wet-lab work was involved.")
    return report


def make_reaction() -> Reaction:
    """A synthetic reaction object."""
    return Reaction(
        reactants=["CC(=O)Cl", "c1ccccc1"],
        products=["CC(=O)c1ccccc1"],
        catalysts=["AlCl3"],
        conditions={"temperature_C": 25.0, "solvent": "DCM"},
        yield_percent=87.5,
        selectivity=0.96,
        name="Friedel-Crafts acylation",
    )


FACTORY: Dict[str, Any] = {
    "Spectrum": make_spectrum,
    "Molecule": make_molecule,
    "Material": make_material,
    "Table": make_table,
    "Image": make_image,
    "Text": make_text,
    "ScientificReport": make_report,
    "SpectralMatch": make_match,
    "Reaction": make_reaction,
}

#: Port *names* whose content is semantic rather than type driven.  A port
#: called ``library`` must receive a molecule library (a table with a SMILES
#: column), ``training`` a labelled regression set, and so on.
PORT_OVERRIDES: Dict[str, str] = {
    "library": "library",
    "training": "training_set",
    "train": "training_set",
    "training_set": "training_set",
    "training_data": "training_set",
    "candidates": "material_table",
    "candidate": "material_table",
    "composition": "text",
    "table": "training_set",
    "data": "library",
}

#: Port names whose override depends on the *node* rather than the port name.
#: ``UnknownCompoundIdentificationNode`` needs a molecule library, whereas
#: ``MaterialDiscoveryNode`` needs a material candidate table on the same port.
NODE_PORT_OVERRIDES: Dict[str, Dict[str, str]] = {
    "UnknownCompoundIdentificationNode": {"candidates": "library"},
    "MaterialDiscoveryNode": {"candidates": "material_table"},
}

#: Material-facing ports take a material candidate table; molecule facing ports
#: take the molecule library.  Decided by the *node* the port belongs to.
MATERIAL_NODES = {
    "MaterialDiscoveryNode",
}


def synthetic_value(data_type: str, port_name: str = "") -> Any:
    """Build a plausible value for an input port of ``data_type``."""
    override = PORT_OVERRIDES.get(str(port_name or "").strip().lower())
    if override:
        factory = {
            "library": make_library,
            "training_set": make_training_set,
            "material_table": make_material_table,
        }[override]
        return factory()
    factory = FACTORY.get(data_type)
    if factory is not None:
        return factory()
    if data_type in {"Any", "", "*"}:
        return make_spectrum()
    return make_spectrum()


#: Default parameters for nodes that cannot work from pure type information.
#: Without them the node legitimately refuses to run ("connect a molecule or
#: set the 'smiles' parameter"), which is *not* a bug -- but the smoke test
#: wants to exercise the code path, so the parameters are supplied here.
PARAM_OVERRIDES: Dict[str, Dict[str, Any]] = {
    # virtual instruments driven by a structure
    "IRNode": {"smiles": "CCO"},
    "RamanNode": {"smiles": "CCO"},
    "UVVisNode": {"smiles": "CC(=O)Oc1ccccc1C(=O)O"},
    "FluorescenceNode": {"smiles": "c1ccc2c(c1)ccc3c2ccc4c3cccc4"},
    "NMRNode": {"smiles": "CCO"},
    "XPSNode": {"composition": "LiFePO4", "formula": "LiFePO4"},
    "FunctionalGroupNode": {"smiles": "CC(=O)O"},
    # database connectors
    "PubChemNode": {"query": "caffeine"},
    "ChEMBLNode": {"query": "caffeine"},
    "ZINCNode": {"query": "caffeine"},
    "PDBNode": {"query": "1CRN"},
    "MassBankNode": {"query": "caffeine"},
    "MoNANode": {"query": "caffeine"},
    "GNPSNode": {"query": "caffeine"},
    "HMDBNode": {"query": "caffeine"},
    "BMRBNode": {"query": "caffeine"},
    "NISTNode": {"query": "caffeine"},
    "CODNode": {"query": "LiFePO4"},
    "ICSDNode": {"query": "LiFePO4"},
    "AFLOWNode": {"query": "LiFePO4"},
    "MaterialsProjectNode": {"query": "LiFePO4"},
    # file based nodes
    "SpectrumFileNode": {"path": str(ROOT / "datasets" / "demo" / "caffeine_ms.xy")},
    "TableFileNode": {"path": str(ROOT / "datasets" / "demo" / "molecule_library.csv")},
    "ImageFileNode": {"path": str(ROOT / "datasets" / "microscopy" / "lifepo4_sem" / "sample_01.png")},
    # v0.5.3 vendor / data layer nodes
    "VendorSpectrumNode": {
        "path": str(ROOT / "datasets" / "spectroscopy" / "shimadzu_spc" / "sample_01.spc")
    },
    # question nodes
    "UnknownCompoundIdentificationNode": {"query": "C8H10N4O2"},
    "MaterialDiscoveryNode": {"application": "lithium ion battery cathode"},
    # agent nodes
    "ScientificAgentNode": {"question": "请分析这个未知化合物"},
    "AgentPlanNode": {"question": "请分析这个未知化合物"},
}


def default_params(type_name: str) -> Dict[str, Any]:
    """Parameters that make a node executable in isolation."""
    return dict(PARAM_OVERRIDES.get(type_name, {}))


# --------------------------------------------------------------------------- #
# runner
# --------------------------------------------------------------------------- #
def build_inputs(node_cls, type_name: str = "") -> Dict[str, Any]:
    """Create synthetic inputs for every input port of ``node_cls``."""
    node_overrides = NODE_PORT_OVERRIDES.get(type_name, {})
    inputs: Dict[str, Any] = {}
    for port in node_cls.input_ports:
        name = port.name
        key = node_overrides.get(name) or PORT_OVERRIDES.get(name.lower())
        if key:
            factory = {
                "library": make_library,
                "training_set": make_training_set,
                "material_table": make_material_table,
            }[key]
            inputs[name] = [factory()] if port.multi else factory()
            continue
        value = synthetic_value(port.data_type, name)
        inputs[name] = [value] if port.multi else value
    return inputs


def run_one(type_name: str, node_cls) -> Tuple[bool, str]:
    """Instantiate, introspect and execute a single node class."""
    try:
        spec = node_cls.spec()
        if not spec.get("name") or not spec.get("category"):
            return False, "incomplete spec()"

        node = node_cls(
            node_id=f"smoke_{type_name}", params=default_params(type_name)
        )
        inputs = build_inputs(node_cls, type_name)
        outputs = node.process(inputs, ctx=None)

        if not isinstance(outputs, dict):
            return False, "process() did not return a dict"

        declared = [p.name for p in node_cls.output_ports]
        empty = [name for name in declared if outputs.get(name) is None]
        if declared and len(empty) == len(declared):
            return False, f"all outputs empty: {declared}"

        preview = None
        for name in declared:
            value = outputs.get(name)
            if value is None:
                continue
            if isinstance(value, list):
                value = value[0] if value else None
            if value is None:
                continue
            method = getattr(value, "summary", None)
            preview = method() if callable(method) else str(value)[:60]
            break
        return True, preview or "ok"
    except Exception as exc:  # noqa: BLE001 - the point of the script
        return False, f"{type(exc).__name__}: {exc}"


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filter", default="", help="only run matching node types")
    parser.add_argument("--list", action="store_true", help="list node types and exit")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    parser.add_argument("--traceback", action="store_true", help="print full tracebacks")
    args = parser.parse_args(argv)

    registry = get_registry()
    types = registry.types()
    if args.filter:
        needle = args.filter.lower()
        types = [name for name in types if needle in name.lower()]

    if args.list:
        for name in types:
            print(name)
        return 0

    results: List[Dict[str, Any]] = []
    started = time.time()
    for type_name in types:
        node_cls = registry.get(type_name)
        ok, detail = run_one(type_name, node_cls)
        if not ok and args.traceback:
            try:
                run_one(type_name, node_cls)
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        results.append({"type": type_name, "ok": ok, "detail": detail})
        if not args.quiet and not args.json:
            flag = "PASS" if ok else "FAIL"
            print(f"[{flag}] {type_name:<34} {detail}")

    failures = [item for item in results if not item["ok"]]
    elapsed = time.time() - started

    if args.json:
        print(
            json.dumps(
                {
                    "total": len(results),
                    "passed": len(results) - len(failures),
                    "failed": len(failures),
                    "elapsed_s": round(elapsed, 2),
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    else:
        print("-" * 100)
        print(
            f"{len(results) - len(failures)}/{len(results)} nodes executed "
            f"successfully in {elapsed:.2f}s"
        )
        for item in failures:
            print(f"  FAILED {item['type']}: {item['detail']}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
