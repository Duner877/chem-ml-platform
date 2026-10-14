"""Report generation nodes.

Three nodes turn arbitrary upstream results into a structured
:class:`~workflow_engine.objects.ScientificReport`:

``ReportBuilderNode``   collect spectra / molecules / materials / tables into
                        a sectioned report object.
``SummaryTableNode``    flatten mixed inputs into a single key/value table.
``ReportExportNode``    persist a report as Markdown, HTML, DOCX or JSON artefact.

All three are dependency free -- they only use the scientific object protocol.
The DOCX writer is optional and requires ``python-docx``; when it is absent the
node raises a clear error instead of writing a fake document.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any, Dict, List

from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import (
    Image,
    Material,
    Molecule,
    ScientificObject,
    ScientificReport,
    SpectralMatch,
    Spectrum,
    Table,
    Text,
)
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import collect, render_report_markdown, write_artifact

__all__ = ["ReportBuilderNode", "SummaryTableNode", "ReportExportNode"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _label(obj: Any, fallback: str = "item") -> str:
    """Best effort human label for any scientific object."""
    name = str(getattr(obj, "name", "") or "").strip()
    if name:
        return name
    for attribute in ("title", "smiles", "formula", "query"):
        value = getattr(obj, attribute, "")
        if value:
            return str(value)
    value = getattr(obj, "text", "")
    if value:
        return str(value).strip().splitlines()[0][:60]
    return fallback


def _flatten(records: List[Dict[str, Any]], prefix: str = "") -> List[List[Any]]:
    """Flatten nested dictionaries into ``(path, value)`` rows."""
    rows: List[List[Any]] = []
    for record in records:
        for key, value in record.items():
            path = f"{prefix}{key}"
            if isinstance(value, dict) and value:
                rows.extend(_flatten([value], prefix=f"{path}."))
            elif isinstance(value, (list, tuple)) and value and not all(
                isinstance(item, (int, float, str)) for item in value
            ):
                rows.append([path, "; ".join(str(item) for item in value[:6])])
            else:
                if isinstance(value, (list, tuple)):
                    value = ", ".join(str(item) for item in value)
                rows.append([path, value])
    return rows


# --------------------------------------------------------------------------- #
# 1. Report builder
# --------------------------------------------------------------------------- #
@register_node
class ReportBuilderNode(ScientificNode):
    """Assemble upstream results into a structured scientific report."""

    name = "Report Builder"
    category = "Report"
    description = "把上游的谱图、分子、材料、表格与文本结果汇总为一份结构化科学报告。"
    tags = ["report", "汇总", "summary", "document"]
    icon = "file-text"

    input_ports = [
        Port("spectrum", "Spectrum", optional=True, multi=True),
        Port("molecule", "Molecule", optional=True, multi=True),
        Port("material", "Material", optional=True, multi=True),
        Port("table", "Table", optional=True, multi=True),
        Port("text", "Text", optional=True, multi=True),
        Port("match", "SpectralMatch", optional=True, multi=True),
    ]
    output_ports = [
        Port("report", "ScientificReport"),
        Port("text", "Text"),
    ]
    parameters = [
        ParameterSpec("title", "string", "Scientific Report"),
        ParameterSpec("abstract", "text", ""),
        ParameterSpec(
            "language",
            "enum",
            "zh",
            options=[("zh", "中文"), ("en", "English")],
        ),
        ParameterSpec("include_tables", "boolean", True),
        ParameterSpec("max_rows", "integer", 12, min=1, max=200),
        ParameterSpec("include_provenance", "boolean", True, "写入执行溯源、证据分级与结果局限"),
        ParameterSpec("limitations", "text", "", "自定义结果局限（每行一条，留空用平台默认）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        title = str(self.get_param("title") or "Scientific Report")
        language = str(self.get_param("language") or "zh")
        max_rows = int(self.get_param("max_rows") or 12)
        include_tables = bool(self.get_param("include_tables"))
        include_provenance = bool(self.get_param("include_provenance", True))
        raw_limitations = str(self.get_param("limitations", "") or "")
        limitations = [line.strip() for line in raw_limitations.splitlines() if line.strip()] or None

        report = ScientificReport(title=title)
        report.abstract = str(self.get_param("abstract") or "").strip()
        report.metadata["language"] = language

        spectra = [
            item
            for item in collect(inputs.get("spectrum"))
            if isinstance(item, Spectrum)
        ]
        molecules = [
            item
            for item in collect(inputs.get("molecule"))
            if isinstance(item, Molecule)
        ]
        materials = [
            item
            for item in collect(inputs.get("material"))
            if isinstance(item, Material)
        ]
        tables = [item for item in collect(inputs.get("table")) if isinstance(item, Table)]
        texts = [item for item in collect(inputs.get("text")) if isinstance(item, Text)]
        matches = [
            item
            for item in collect(inputs.get("match"))
            if isinstance(item, SpectralMatch)
        ]

        heading = {
            "spectra": "光谱数据" if language == "zh" else "Spectra",
            "molecules": "分子结构" if language == "zh" else "Molecules",
            "materials": "材料候选" if language == "zh" else "Materials",
            "tables": "数据表" if language == "zh" else "Tables",
            "notes": "分析说明" if language == "zh" else "Notes",
            "matches": "数据库匹配" if language == "zh" else "Database matches",
        }

        if spectra:
            lines = [
                f"- **{_label(spec, 'spectrum')}** — {spec.summary()}" for spec in spectra
            ]
            report.add_section(heading["spectra"], "\n".join(lines))

        if molecules:
            lines = []
            for molecule in molecules:
                bits = [f"**{_label(molecule, 'molecule')}**"]
                if molecule.formula:
                    bits.append(f"formula `{molecule.formula}`")
                if molecule.average_mass is not None:
                    bits.append(f"MW {molecule.average_mass:.2f}")
                if molecule.confidence:
                    bits.append(f"confidence {molecule.confidence:.2f}")
                lines.append("- " + ", ".join(bits))
            report.add_section(heading["molecules"], "\n".join(lines))

        if materials:
            lines = []
            for material in materials:
                lines.append(
                    f"- **{_label(material, 'material')}** — {material.summary()}"
                )
            report.add_section(heading["materials"], "\n".join(lines))

        if matches:
            lines = []
            for match in matches:
                best = match.best() or {}
                lines.append(
                    "- **{}** ({}): {}".format(
                        match.query or "query",
                        match.library or "library",
                        best.get("name", "n/a"),
                    )
                )
            report.add_section(heading["matches"], "\n".join(lines))

        if include_tables and tables:
            for table in tables:
                rows = [list(row) for row in table.rows[:max_rows]]
                report.add_section(
                    _label(table, "table"),
                    "",
                    tables=[
                        {"columns": list(table.columns), "rows": rows},
                    ],
                )

        if texts:
            body = "\n\n".join(str(item.text or "").strip() for item in texts if item.text)
            report.add_section(heading["notes"], body)

        if not report.sections:
            report.add_section(
                "结果" if language == "zh" else "Results",
                "未接收到任何上游数据。" if language == "zh" else "No upstream data received.",
            )

        # v0.7.1 (tasks H/J): append execution provenance, evidence grading and
        # the scientific-limitation statement so the report is self-documenting.
        if include_provenance:
            from report_agent.builders import DEFAULT_LIMITATIONS, provenance_sections

            # ``render_report_markdown`` renders ``report.limitations`` itself, so
            # skip the duplicated limitations section produced by the shared
            # builder and keep only the provenance / evidence-grading blocks.
            report.limitations = list(limitations) if limitations else list(DEFAULT_LIMITATIONS)
            for extra in provenance_sections(
                getattr(ctx, "provenance", None),
                getattr(ctx, "workflow_meta", None),
                limitations,
            ):
                if extra.heading.startswith("结果局限"):
                    continue
                report.sections.append(
                    {
                        "heading": extra.heading,
                        "text": extra.body,
                        "figures": [],
                        "tables": [extra.table] if extra.table else [],
                    }
                )
            meta = dict(getattr(ctx, "workflow_meta", {}) or {})
            if meta:
                report.provenance = meta

        # ``report_id`` keeps concurrent ReportBuilder nodes inside one run
        # from writing to the same ``report.md`` artefact.
        markdown_path = write_artifact(
            ctx, f"report_{report.report_id}.md", render_report_markdown(report)
        )
        report.markdown_path = markdown_path

        text = Text(
            text=render_report_markdown(report),
            language=language,
            name=f"{title} (markdown)",
        )
        text.metadata["report_id"] = report.report_id

        self.log(f"report: {report.summary()}")
        return {"report": report, "text": text}


# --------------------------------------------------------------------------- #
# 2. Summary table
# --------------------------------------------------------------------------- #
@register_node
class SummaryTableNode(ScientificNode):
    """Flatten mixed upstream objects into one key/value summary table."""

    name = "Summary Table"
    category = "Report"
    description = "将任意上游科学对象压平为一张“指标 / 数值”汇总表，便于直接与报告或导出节点衔接。"
    tags = ["report", "table", "汇总", "summary"]
    icon = "table"

    input_ports = [
        Port("spectrum", "Spectrum", optional=True, multi=True),
        Port("molecule", "Molecule", optional=True, multi=True),
        Port("material", "Material", optional=True, multi=True),
        Port("table", "Table", optional=True, multi=True),
        Port("image", "Image", optional=True, multi=True),
    ]
    output_ports = [Port("table", "Table")]
    parameters = [
        ParameterSpec("max_rows", "integer", 60, min=1, max=1000),
        ParameterSpec("include_metadata", "boolean", True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        max_rows = int(self.get_param("max_rows") or 60)
        include_metadata = bool(self.get_param("include_metadata"))

        rows: List[List[Any]] = []
        for key in ("spectrum", "molecule", "material", "table", "image"):
            for index, item in enumerate(collect(inputs.get(key))):
                label = f"{key}[{index}]"
                rows.append([label, "type", type(item).__name__])
                rows.append([label, "name", _label(item, key)])
                if isinstance(item, Spectrum):
                    rows.append([label, "points", item.size])
                    rows.append([label, "technique", item.technique or item.mode])
                    rows.append([label, "peaks", len(item.peaks)])
                elif isinstance(item, Molecule):
                    rows.append([label, "formula", item.formula])
                    rows.append([label, "smiles", item.smiles])
                    if item.average_mass is not None:
                        rows.append([label, "mw", round(item.average_mass, 4)])
                    rows.append([label, "confidence", round(item.confidence, 4)])
                    for name, value in list(item.properties.items())[:12]:
                        rows.append([label, name, value])
                elif isinstance(item, Material):
                    rows.append([label, "phase", item.phase])
                    for name, value in list(item.properties.items())[:12]:
                        rows.append([label, name, value])
                elif isinstance(item, Table):
                    rows.append([label, "rows", len(item.rows)])
                    rows.append([label, "columns", ", ".join(map(str, item.columns))])
                elif isinstance(item, Image):
                    rows.append([label, "size", f"{item.width}x{item.height}"])
                if include_metadata:
                    meta = getattr(item, "metadata", {}) or {}
                    rows.extend(_flatten([meta], prefix=f"{label}.meta"))

        table = Table(
            columns=["object", "metric", "value"],
            rows=rows[:max_rows],
            name="Summary",
        )
        self.log(f"summary table: {table.summary()}")
        return {"table": table}


# --------------------------------------------------------------------------- #
# 3. Report export
# --------------------------------------------------------------------------- #
@register_node
class ReportExportNode(ScientificNode):
    """Persist a scientific report as Markdown / HTML / JSON artefact."""

    name = "Report Export"
    category = "Report"
    description = "把结构化报告落盘为 Markdown / HTML / DOCX / JSON 产物文件，返回路径文本。"
    tags = ["report", "export", "导出", "artifact"]
    #: v0.7.1 task E/F: writes artefact files into the run directory.
    capabilities = ["writes_files"]
    icon = "download"

    input_ports = [
        Port("report", "ScientificReport", optional=True),
        Port("text", "Text", optional=True, multi=True),
    ]
    output_ports = [Port("text", "Text")]
    parameters = [
        ParameterSpec(
            "format",
            "enum",
            "markdown",
            options=[
                ("markdown", "Markdown (.md)"),
                ("html", "HTML (.html)"),
                ("docx", "Word (.docx)"),
                ("json", "JSON (.json)"),
            ],
        ),
        ParameterSpec("filename", "string", "report"),
        ParameterSpec("embed_css", "boolean", True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        fmt = str(self.get_param("format") or "markdown").lower()
        filename = str(self.get_param("filename") or "report").strip() or "report"
        embed_css = bool(self.get_param("embed_css"))

        report = None
        for item in collect(inputs.get("report")):
            if isinstance(item, ScientificReport):
                report = item
                break

        if report is None:
            texts = [item for item in collect(inputs.get("text")) if isinstance(item, Text)]
            if not texts:
                raise ValueError("ReportExportNode requires a report or text input")
            report = ScientificReport(title=f"{filename} notes")
            report.add_section(
                "Notes", "\n\n".join(str(item.text or "") for item in texts)
            )

        if fmt == "json":
            content = json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str)
            suffix = "json"
        elif fmt == "html":
            content = _render_html(report, embed_css=embed_css)
            suffix = "html"
        elif fmt == "docx":
            path = _export_docx(report, ctx, filename)
            text = Text(text=path, name=f"{filename}.docx")
            text.metadata["format"] = "docx"
            text.metadata["report_id"] = report.report_id
            self.log(f"exported {path}")
            return {"text": text}
        else:
            content = render_report_markdown(report)
            suffix = "md"

        path = write_artifact(ctx, f"{filename}.{suffix}", content)
        text = Text(text=path, name=f"{filename}.{suffix}")
        text.metadata["format"] = suffix
        text.metadata["report_id"] = report.report_id
        self.log(f"exported {path}")
        return {"text": text}


def _export_docx(report: ScientificReport, ctx: Any, filename: str) -> str:
    """Export a :class:`ScientificReport` to DOCX via :mod:`report_engine`.

    Raises a clear, actionable error when ``python-docx`` is missing instead of
    writing a file that only *looks* like a real export (task J: reports must not
    misrepresent their own integrity).
    """
    try:
        from report_engine import ReportExporter, ReportModel
        from report_engine import ReportSection as _EngineSection
    except Exception as exc:  # pragma: no cover - import-time defensive
        raise RuntimeError(f"DOCX 导出不可用：{exc}") from exc

    meta = dict(getattr(report, "provenance", {}) or {})
    model = ReportModel(
        title=report.title,
        run_id=str(meta.get("run_id", "")),
        workflow_name=str(meta.get("name", "")),
        limitations=list(getattr(report, "limitations", []) or []),
        references=list(report.references or []),
    )
    if report.abstract:
        model.research_question = report.abstract
    for section in report.sections:
        table_rows = None
        tables = section.get("tables") or []
        if tables:
            first = tables[0]
            columns = [str(column) for column in (first.get("columns") or [])]
            rows = [
                ["" if value is None else str(value) for value in row]
                for row in (first.get("rows") or [])
            ]
            if columns:
                table_rows = [columns] + rows
        model.sections.append(
            _EngineSection(
                title=str(section.get("heading", "Section")),
                body=str(section.get("text", "")),
                table=table_rows,
            )
        )

    if ctx is not None and hasattr(ctx, "artifact_path"):
        target = Path(ctx.artifact_path(f"{filename}.docx"))
    else:
        out_dir = Path("output")
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{filename}.docx"

    # ``export_docx`` needs the destination directory and a relative filename.
    result = ReportExporter(target.parent).export_docx(model, target.name)
    return result.path


_CSS = """
:root { color-scheme: light; }
body { font-family: "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
       margin: 2.5rem auto; max-width: 860px; line-height: 1.65; color: #1f2937; }
h1 { font-size: 1.9rem; border-bottom: 2px solid #e5e7eb; padding-bottom: .4rem; }
h2 { font-size: 1.3rem; margin-top: 2rem; color: #0f766e; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
th, td { border: 1px solid #e5e7eb; padding: .45rem .7rem; text-align: left; }
th { background: #f3f4f6; font-weight: 600; }
code { background: #f3f4f6; padding: .1rem .3rem; border-radius: 3px; }
"""


def _render_html(report: ScientificReport, embed_css: bool = True) -> str:
    """Render a report as a self contained HTML document."""
    parts: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="zh"><head><meta charset="utf-8">',
        f"<title>{html.escape(report.title)}</title>",
    ]
    if embed_css:
        parts.append(f"<style>{_CSS}</style>")
    parts.append("</head><body>")
    parts.append(f"<h1>{html.escape(report.title)}</h1>")
    if report.abstract:
        parts.append(f"<p><em>{html.escape(report.abstract)}</em></p>")
    for section in report.sections:
        heading = str(section.get("heading", "Section"))
        parts.append(f"<h2>{html.escape(heading)}</h2>")
        text = str(section.get("text", "")).strip()
        if text:
            for block in text.split("\n\n"):
                parts.append(f"<p>{html.escape(block).replace(chr(10), '<br>')}</p>")
        for figure in section.get("figures", []) or []:
            parts.append(f'<p><img src="{html.escape(str(figure))}" alt="figure"></p>')
        for table in section.get("tables", []) or []:
            columns = list(table.get("columns", []) or [])
            rows = list(table.get("rows", []) or [])
            if not columns:
                continue
            parts.append("<table><thead><tr>")
            parts.append("".join(f"<th>{html.escape(str(c))}</th>" for c in columns))
            parts.append("</tr></thead><tbody>")
            for row in rows:
                cells = "".join(
                    "<td>{}</td>".format(
                        "" if v is None else html.escape(str(v))
                    )
                    for v in row
                )
                parts.append(f"<tr>{cells}</tr>")
            parts.append("</tbody></table>")
    if report.references:
        parts.append("<h2>References</h2><ul>")
        for reference in report.references:
            parts.append(f"<li>{html.escape(str(reference))}</li>")
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)
