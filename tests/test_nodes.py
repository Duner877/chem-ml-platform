"""Node level tests: catalogue integrity, parameters, scientific output."""

from __future__ import annotations

import pytest

from workflow_engine.objects import Molecule, Spectrum, Table, Text


# --------------------------------------------------------------------------- #
# catalogue
# --------------------------------------------------------------------------- #
def test_at_least_20_node_templates(registry):
    """Requirement #6: 20+ scientific node templates."""
    assert len(registry) >= 20, f"only {len(registry)} nodes registered"


def test_every_node_has_a_unique_type(registry):
    types = registry.types()
    assert len(types) == len(set(types))


def test_every_spec_is_complete(registry):
    """Names, categories, ports and parameters must be serialisable."""
    for node_type in registry.types():
        spec = registry.spec(node_type)
        assert spec["name"], node_type
        assert spec["category"], node_type
        assert isinstance(spec["inputs"], list)
        assert isinstance(spec["outputs"], list)
        assert isinstance(spec["parameters"], list)
        for port in spec["inputs"] + spec["outputs"]:
            assert port["name"]
            assert port["data_type"]
        for parameter in spec["parameters"]:
            assert parameter["name"]
            assert parameter["type"]


def test_required_categories_exist(registry):
    """The specification mandates these node families."""
    categories = {bucket["name"] for bucket in registry.categories()}
    for expected in (
        "Questions",
        "IO",
        "Analysis",
        "Report",
        "Instruments/Mass Spectrometry",
        "Instruments/NMR",
        "Instruments/Vibrational",
        "Instruments/Diffraction",
        "Instruments/Microscopy",
        "Instruments/Thermal",
        "Instruments/Electrochemistry",
        "Instruments/Particle",
        "Instruments/Surface",
        "Instruments/Electronic",
        "Instruments/Imaging",
        "AI/LLM",
        "AI/Foundation Models",
        "AI/Vision",
        "AI/ML",
        "Databases/Spectral",
        "Databases/Chemical",
        "Databases/Materials",
        "Simulation/Quantum",
        "Simulation/MD",
        "Simulation/Materials",
    ):
        assert expected in categories, f"missing category {expected}"


def test_registry_lookup_by_alias(registry):
    assert registry.resolve("UnknownID") == "UnknownCompoundIdentificationNode"
    assert registry.resolve("MatDiscovery") == "MaterialDiscoveryNode"
    assert registry.has("IRNode")
    assert not registry.has("DefinitelyNotANode")


# --------------------------------------------------------------------------- #
# scientific behaviour
# --------------------------------------------------------------------------- #
def test_ir_node_reports_a_functional_band(registry):
    node = registry.create("IRNode", "ir1", {"smiles": "CCO"})
    outputs = node.process({"sample": None}, None)
    spectrum = outputs["spectrum"]
    assert isinstance(spectrum, Spectrum)
    assert spectrum.technique in {"IR", "FTIR"}
    assert len(spectrum.peaks) > 0
    # ethanol must show the alcohol O-H and C-O stretches
    assignments = " ".join(peak.assignment for peak in spectrum.peaks)
    assert "O-H" in assignments
    assert "C-O" in assignments
    wavenumbers = [peak.x for peak in spectrum.peaks]
    assert 3200 <= max(wavenumbers) <= 3600


def test_nmr_node_predicts_a_spectrum(registry):
    node = registry.create("NMRNode", "nmr1", {"smiles": "CCO"})
    outputs = node.process({}, None)
    spectrum = outputs["spectrum"]
    assert spectrum.size > 100
    assert spectrum.x_unit.lower().startswith("ppm")


def test_xrd_node_indexes_a_cubic_lattice(registry):
    node = registry.create("XRDNode", "xrd1", {"formula": "LiFePO4"})
    spectrum = node.process({}, None)["spectrum"]
    assert spectrum.size > 500
    # the composition of the resolved material, reported in metadata
    assert spectrum.metadata.get("formula") == "Fe1Li1O4P1"
    assert len(spectrum.peaks) > 5
    assert all(0 < peak.x < 180 for peak in spectrum.peaks)


def test_descriptor_node_computes_molecular_properties(registry):
    node = registry.create("MolecularDescriptorsNode", "d1")
    molecule = registry.create("MoleculeInputNode", "m1", {"smiles": "CCO"}).process({}, None)["molecule"]
    outputs = node.process({"molecule": molecule}, None)
    table = outputs["table"]
    assert isinstance(table, Table)
    keys = {row[0] for row in table.rows}
    assert "MolWt" in keys
    assert "MolLogP" in keys


def test_similarity_node_ranks_a_library(registry):
    query = registry.create("MoleculeInputNode", "q", {"smiles": "CCO"}).process({}, None)["molecule"]
    library = Table.from_records(
        [
            {"smiles": "CCO", "name": "ethanol"},
            {"smiles": "c1ccccc1", "name": "benzene"},
            {"smiles": "CCCO", "name": "propanol"},
        ]
    )
    node = registry.create("SimilaritySearchNode", "s1", {"top_k": 3})
    table = node.process({"query": query, "library": library}, None)["table"]
    assert len(table.rows) == 3
    best = table.records()[0]
    assert best["smiles"] in {"CCO", "CCCO"}
    assert best["similarity"] >= table.records()[1]["similarity"]


def test_unknown_compound_identification(registry):
    """The question node fuses MS + NMR evidence into a ranked candidate list."""
    from scripts.smoke_nodes import make_spectrum

    node = registry.create(
        "UnknownCompoundIdentificationNode",
        "id1",
        {"query": "ethanol", "top_k": 3},
    )
    library = Table.from_records(
        [{"smiles": "CCO", "name": "ethanol"}, {"smiles": "CCCO", "name": "propanol"}]
    )
    outputs = node.process(
        {"ms": make_spectrum(), "candidates": library}, None
    )
    molecule = outputs["molecule"]
    assert isinstance(molecule, Molecule)
    assert molecule.smiles == "CCO"
    assert len(outputs["table"].rows) == 2


def test_material_discovery_ranks_candidates(registry):
    node = registry.create("MaterialDiscoveryNode", "md1", {"top_k": 3})
    library = Table.from_records(
        [
            {"formula": "LiFePO4", "name": "LFP"},
            {"formula": "LiCoO2", "name": "LCO"},
            {"formula": "LiMn2O4", "name": "spinel"},
        ]
    )
    outputs = node.process({"candidates": library}, None)
    assert outputs["material"].composition
    assert len(outputs["table"].rows) == 3


def test_llm_node_offline_fallback(registry):
    """Without an API key the LLM node answers from its internal reasoner."""
    node = registry.create(
        "LLMNode",
        "llm1",
        {"provider": "offline", "instruction": "分析这份 EI-MS 谱图的可能结构"},
    )
    text = node.process({}, None)["text"]
    assert isinstance(text, Text)
    assert len(text.text) > 20


def test_foundation_model_embeds_a_molecule(registry):
    node = registry.create("ChemBERTaNode", "cb1", {"smiles": "CCO", "embedding_dim": 128})
    molecule = registry.create("MoleculeInputNode", "m", {"smiles": "CCO"}).process({}, None)["molecule"]
    outputs = node.process({"molecule": molecule}, None)
    assert len(outputs["molecule"].embedding) == 128
    assert outputs["molecule"].formula == "C2H6O"


def test_report_nodes_roundtrip(registry):
    """ReportBuilder -> ReportExport produces a Markdown artefact."""
    builder = registry.create(
        "ReportBuilderNode", "rb1", {"title": "unit test", "language": "zh"}
    )
    text = Text(text="finding", name="note")
    outputs = builder.process({"text": text}, None)
    report = outputs["report"]
    assert report.sections

    exporter = registry.create(
        "ReportExportNode", "re1", {"format": "markdown", "filename": "unit_test_report"}
    )
    path = exporter.process({"report": report}, None)["text"].text
    assert path.endswith(".md")


def test_enum_parameter_accepts_value_and_label(registry):
    """Regression: enum options are (value, label) pairs."""
    node = registry.create("ReportExportNode", "re", {"format": "html"})
    assert node.get_param("format") == "html"
    node = registry.create("ReportExportNode", "re", {"format": "HTML (.html)"})
    assert node.get_param("format") == "html"


def test_table_file_node_strips_a_bom(registry):
    """Regression: a UTF-8 BOM must not corrupt the first column name."""
    node = registry.create(
        "TableFileNode", "tf", {"path": "datasets/demo/molecule_library.csv"}
    )
    table = node.process({}, None)["table"]
    assert table.columns[0] == "smiles"
    assert "smiles" in table.records()[0]
