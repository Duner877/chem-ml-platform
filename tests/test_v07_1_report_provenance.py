"""v0.7.1 report-export tests (task J).

A report must be *self-documenting*: it records the workflow / node versions,
parameters, execution backend, fallback and determinism, and it states the
scientific limitations instead of presenting approximations as measurements.
"""

from __future__ import annotations

import pytest

from report_agent import DEFAULT_LIMITATIONS, build_report
from report_agent.builders import gather, provenance_sections
from workflow_engine.objects import Molecule, Text


PROVENANCE = {
    "environment": {
        "python_version": "3.13.12",
        "os_name": "Windows",
        "platform_release": "11",
        "machine": "AMD64",
        "torch_version": "",
        "cuda_available": False,
    },
    "nodes": {
        "n1": {
            "node_id": "n1",
            "node_type": "ORCANode",
            "node_version": "0.7.1",
            "status": "completed",
            "duration_ms": 12.3,
            "fallback_used": True,
            "fallback_reason": "orca missing",
            "external_software": {},
            "provider": "",
            "model": "",
            "deterministic": True,
            "random_seed": 1017,
        },
        "n2": {
            "node_id": "n2",
            "node_type": "SomeExternalNode",
            "node_version": "0.7.1",
            "status": "completed",
            "duration_ms": 3.0,
            "external_software": {"orca": "6.0"},
            "fallback_used": False,
            "provider": "",
            "model": "",
            "deterministic": True,
        },
        "n3": {
            "node_id": "n3",
            "node_type": "LLMNode",
            "node_version": "0.7.1",
            "status": "completed",
            "duration_ms": 4.0,
            "provider": "local",
            "model": "llama",
            "external_software": {},
            "fallback_used": False,
        },
    },
}
META = {"name": "demo", "version": "0.7.1", "run_id": "run_x", "node_count": 3, "edge_count": 2}


class TestProvenanceSections:
    def test_sections_include_provenance_evidence_limitations(self):
        sections = provenance_sections(PROVENANCE, META, None)
        headings = " ".join(section.heading for section in sections)
        assert "执行溯源" in headings
        assert "证据分级" in headings
        assert "结果局限" in headings

    def test_evidence_grading_classifies_sources(self):
        sections = provenance_sections(PROVENANCE, META, None)
        body = next(s.body for s in sections if s.heading.startswith("证据分级"))
        assert "外部软件真实执行" in body
        assert "内部近似" in body
        assert "模型推断" in body

    def test_provenance_table_has_a_row_per_node(self):
        sections = provenance_sections(PROVENANCE, META, None)
        table = next(s.table for s in sections if s.heading.startswith("执行溯源"))
        assert table is not None
        assert len(table["rows"]) == 3
        assert "random_seed" in table["columns"]

    def test_custom_limitations_override_defaults(self):
        sections = provenance_sections(None, None, ["only this limitation"])
        body = next(s.body for s in sections if s.heading.startswith("结果局限"))
        assert "only this limitation" in body
        assert DEFAULT_LIMITATIONS[0] not in body

    def test_default_limitations_used_when_absent(self):
        sections = provenance_sections(None, None, None)
        body = next(s.body for s in sections if s.heading.startswith("结果局限"))
        assert DEFAULT_LIMITATIONS[0] in body


class TestRenderedDocuments:
    def _objects(self):
        return [Molecule(smiles="CCO", name="ethanol", formula="C2H6O"), Text(text="note", name="note")]

    def test_markdown_contains_provenance_and_limitations(self):
        result = build_report(
            self._objects(), title="T", format="markdown",
            provenance=PROVENANCE, workflow_meta=META,
        )
        for keyword in ("执行溯源", "证据分级", "结果局限", "内部近似", "模型推断"):
            assert keyword in result.data

    def test_html_contains_provenance_and_limitations(self):
        result = build_report(
            self._objects(), title="T", format="html",
            provenance=PROVENANCE, workflow_meta=META,
        )
        for keyword in ("执行溯源", "证据分级", "结果局限"):
            assert keyword in result.data

    def test_gather_without_provenance_still_states_limitations(self):
        content = gather(self._objects(), title="T")
        headings = [section.heading for section in content.sections]
        assert any(h.startswith("结果局限") for h in headings)

    def test_report_is_not_silently_empty(self):
        content = gather([], title="T")
        headings = [section.heading for section in content.sections]
        assert "Empty" in headings


class _StubContext:
    """Minimal execution context: only the artefact path is needed."""

    def __init__(self, base):
        self.base = base

    def artifact_path(self, filename: str, subdir: str = ""):
        directory = self.base / subdir if subdir else self.base
        directory.mkdir(parents=True, exist_ok=True)
        return directory / filename


class TestExportFormats:
    """Task J.1: Markdown / HTML / DOCX / JSON export must really work."""

    def _report(self, ctx):
        from nodes.report import ReportBuilderNode
        from workflow_engine.objects import Molecule, Table, Text

        builder = ReportBuilderNode("rb", {"title": "导出测试 — 中文", "language": "zh"})
        outputs = builder.execute(
            {
                "molecule": [Molecule(smiles="CCO", name="乙醇", formula="C2H6O")],
                "table": [Table(columns=["a", "b"], rows=[[1, 2], [3, 4]], name="t")],
                "text": [Text(text="特殊字符 α β ≤ 与长文件名测试", name="n")],
            },
            ctx,
        )
        return outputs["report"]

    def _export(self, fmt, ctx, report):
        from nodes.report import ReportExportNode

        node = ReportExportNode("e", {"format": fmt, "filename": f"r_{fmt}"})
        return node.process({"report": report}, ctx)["text"].text

    def test_markdown_html_json_docx_all_export(self, tmp_path):
        ctx = _StubContext(tmp_path)
        report = self._report(ctx)
        for fmt, suffix in (("markdown", "md"), ("html", "html"), ("json", "json"), ("docx", "docx")):
            path = self._export(fmt, ctx, report)
            assert path.endswith(f".{suffix}")
            from pathlib import Path

            assert Path(path).stat().st_size > 0

    def test_docx_is_a_real_office_container(self, tmp_path):
        import zipfile

        pytest.importorskip("docx")
        ctx = _StubContext(tmp_path)
        report = self._report(ctx)
        path = self._export("docx", ctx, report)
        assert zipfile.is_zipfile(path)
        with zipfile.ZipFile(path) as archive:
            assert "word/document.xml" in archive.namelist()

    def test_markdown_states_limitations(self, tmp_path):
        from pathlib import Path

        ctx = _StubContext(tmp_path)
        report = self._report(ctx)
        path = self._export("markdown", ctx, report)
        text = Path(path).read_text(encoding="utf-8")
        assert "结果局限" in text

