"""v0.7 Phase F tests -- report export (spec sections 13, 22-H)."""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from report_engine import ExportResult, ReportExporter, ReportModel, ReportSection
from workflow_engine.engine import NodeExecutionRecord, RunResult, STATUS_COMPLETED


def make_model() -> ReportModel:
    model = ReportModel(
        title="咖啡因质谱分析报告",
        project="Demo 01",
        sample="caffeine",
        research_question="未知峰 m/z 194 是否为咖啡因？",
        methods="EI-MS 峰提取 + SavGol 平滑 + 分子库匹配",
        run_id="run_test_1",
        workflow_name="01_unknown_compound_identification",
        input_files=["datasets/demo/caffeine_ms.xy"],
        conclusions="候选列表按匹配度排序，排名第一为咖啡因（计算结果，非实验验证）。",
        next_steps=["使用标准品复测", "增加 NMR 证据"],
        limitations=["离线分子库仅 ~400 化合物"],
        warnings=["[warn] offline engine used"],
        software_versions={"python": "3.13", "chemml": "0.7.0"},
        references=["Smith et al. (2020) Example Journal"],
    )
    model.sections.append(
        ReportSection(
            title="节点执行记录",
            table=[["Node", "Status"], ["ms_file", "completed"], ["identify", "completed"]],
        )
    )
    return model


@pytest.fixture()
def exporter(tmp_path: Path) -> ReportExporter:
    return ReportExporter(tmp_path / "reports")


class TestMarkdown:
    def test_export_integrity(self, exporter):
        result = exporter.export_markdown(make_model())
        assert isinstance(result, ExportResult)
        assert result.bytes_written > 100
        text = Path(result.path).read_text(encoding="utf-8")
        assert "# 咖啡因质谱分析报告" in text
        assert "run_test_1" in text
        assert "| Node | Status |" in text
        assert "offline engine used" in text

    def test_no_fabricated_references(self, exporter):
        model = make_model()
        model.references = []
        text = exporter.export_markdown(model) and Path(
            exporter.output_dir / "report.md"
        ).read_text(encoding="utf-8")
        assert "参考文献" not in text


class TestHTML:
    def test_export_and_escaping(self, exporter):
        model = make_model()
        model.research_question = "<script>alert('xss')</script> 是咖啡因吗？"
        result = exporter.export_html(model)
        html = Path(result.path).read_text(encoding="utf-8")
        assert "<script>alert" not in html
        assert "&lt;script&gt;" in html
        assert "咖啡因" in html

    def test_table_rendered(self, exporter):
        html = Path(exporter.export_html(make_model()).path).read_text(encoding="utf-8")
        assert "<th>Node</th>" in html and "<td>ms_file</td>" in html


class TestDOCX:
    def test_export_and_open(self, exporter):
        result = exporter.export_docx(make_model())
        path = Path(result.path)
        assert result.bytes_written > 1000
        # python-docx files are valid zip archives; verify structure
        with zipfile.ZipFile(path) as zf:
            assert "word/document.xml" in zf.namelist()
            doc = zf.read("word/document.xml").decode("utf-8")
            assert "咖啡因质谱分析报告" in doc
            assert "run_test_1" in doc

    def test_digest_matches_file(self, exporter):
        result = exporter.export_docx(make_model())
        data = Path(result.path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == result.sha256


class TestFromRun:
    def test_model_from_run_result(self):
        run = RunResult(run_id="run_x", workflow_name="wf", status=STATUS_COMPLETED)
        rec = NodeExecutionRecord(
            node_id="ms_file", node_type="SpectrumFileNode",
            status=STATUS_COMPLETED, duration_ms=3.2,
            logs=["[warn] low intensity", "loaded 1200 points"],
        )
        run.records["ms_file"] = rec
        model = ReportModel.from_run(
            run, project="proj", research_question="q?"
        )
        assert model.run_id == "run_x"
        assert model.project == "proj"
        titles = [s.title for s in model.sections]
        assert any("节点执行记录" in t for t in titles)
        warnings = model.warnings
        assert any("low intensity" in w for w in warnings)
        # non-warning logs become node log sections, not warnings
        assert any("loaded 1200 points" in s.body for s in model.sections)
