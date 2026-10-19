"""Report generation nodes.

Three nodes turn arbitrary upstream results into a structured
:class:`~workflow_engine.objects.ScientificReport`:

``ReportBuilderNode``   collect spectra / molecules / materials / tables into
                        a sectioned report object.
``SummaryTableNode``    flatten mixed inputs into a single key/value table.
``ReportExportNode``    persist a report as Markdown, HTML, DOCX or JSON artefact.
``FigureExportNode``    render upstream spectra / tables as PNG figures.

All are dependency free -- they only use the scientific object protocol.
The DOCX writer is optional and requires ``python-docx``; when it is absent the
node raises a clear error instead of writing a fake document.  Figure export
additionally needs matplotlib, which the platform already depends on.
"""

from __future__ import annotations

import html
import io
import json
import re
import threading
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

__all__ = [
    "ReportBuilderNode",
    "SummaryTableNode",
    "ReportExportNode",
    "FigureExportNode",
]



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


# --------------------------------------------------------------------------- #
# 4. Figure export
# --------------------------------------------------------------------------- #
#: Long-form labels for the reference product figures.  A file named
#: ``figure.png`` cannot be told apart from ``figure_2.png`` a week later, and a
#: delivered set of figures whose names say only "figure" is not a deliverable.
FIGURE_KINDS: Dict[str, Dict[str, str]] = {
    "band_structure": {
        "title": "能带结构 / Band structure",
        "stem": "band_structure",
        "x_label": "k 路径 (2π/a)",
        "y_label": "E − E_F (eV)",
    },
    "dos": {
        "title": "态密度 / Density of states",
        "stem": "dos",
        "x_label": "E − E_F (eV)",
        "y_label": "态密度 (states/eV)",
    },
    "pdos": {
        "title": "投影态密度 / Projected density of states",
        "stem": "pdos",
        "x_label": "E − E_F (eV)",
        "y_label": "分轨道态密度 (states/eV)",
    },
    "relax_convergence": {
        "title": "弛豫收敛 / Relaxation convergence",
        "stem": "relax_convergence",
        "x_label": "弛豫步数 / relaxation step",
        "y_label": "数值 / value",
    },
    "auto": {"title": "", "stem": "figure", "x_label": "", "y_label": ""},
}

#: Trace colours.  Chosen to stay distinguishable in greyscale too, because a
#: figure that only reads by hue stops being readable when printed.
_TRACE_COLOURS = (
    "#1f6feb", "#d7263d", "#2a9d8f", "#e07b00", "#6a4c93", "#3f7d20",
)
_ZERO_LINE = "#8a8f98"


#: CJK-capable families, best first.  matplotlib's default is DejaVu Sans, which
#: has no Chinese glyphs: every CJK label renders as an empty box while the
#: figure is otherwise perfect, and the warning lands in a log nobody reads.
#: The platform's UI is Chinese, so a figure that cannot spell its own axis
#: labels is not a usable deliverable.
_CJK_FONTS = (
    "Microsoft YaHei", "Noto Sans SC", "Source Han Sans SC", "SimHei",
    "PingFang SC", "Heiti SC", "WenQuanYi Zen Hei", "Noto Sans CJK SC",
    "Source Han Sans CN", "SimSun",
)


def _apply_cjk_font() -> str | None:
    """Point matplotlib at an installed CJK font.  Returns the family used."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.font_manager as font_manager

        installed = {font.name for font in font_manager.fontManager.ttflist}
        for family in _CJK_FONTS:
            if family in installed:
                # Prepending to the family list matters: matplotlib walks it in
                # order, and DejaVu would otherwise keep winning the fallback
                # for every character it happens to have.
                matplotlib.rcParams["font.sans-serif"] = [family] + list(
                    matplotlib.rcParams.get("font.sans-serif", [])
                )
                matplotlib.rcParams["font.family"] = "sans-serif"
                # CJK glyphs in the same run as Latin math are commonly joined
                # by a thin space that reads as a missing glyph in the figure.
                matplotlib.rcParams["axes.unicode_minus"] = False
                return family
    except Exception:  # pragma: no cover - depends on the environment
        return None
    return None


def _require_matplotlib() -> Any:
    """Import matplotlib on the Agg backend, with an actionable error.

    A figure node that silently skips its output when matplotlib is missing
    would leave a workflow that *reports success* and delivers five of the six
    files it promised.
    """
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        _apply_cjk_font()
        return plt
    except Exception as exc:  # pragma: no cover - depends on the environment
        raise RuntimeError(
            f"绘图需要 matplotlib，但导入失败：{exc}。"
            "请安装 matplotlib 后重试（pip install matplotlib）。"
        ) from exc


def _figure_stem(name: str, default: str = "figure") -> str:
    """Sanitise a file stem **without** discarding Chinese characters.

    ``workflow_engine.utils.safe_filename`` is ASCII-only by design -- it exists
    to keep arbitrary text safe on any filesystem, and it maps ``能带图`` to an
    empty string.  That is right for user text and wrong for a file the user is
    meant to recognise by name: the delivered figures are named ``Al_能带图``,
    ``Al_态密度_DOS``, and so on.  Windows, macOS and Linux all accept those
    names; what actually has to be removed is the path separator, the control
    characters and the Windows-reserved ``<>:"/\\|?*``.
    """
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name or ""))
    cleaned = cleaned.strip().strip(".")
    cleaned = re.sub(r"\s+", "_", cleaned)
    return cleaned or default


#: matplotlib is not thread safe.  Its mathtext parser -- reached by every log
#: axis tick label, so by any relaxation figure -- keeps module-level scratch
#: state, and two nodes rendering concurrently corrupt it into
#: ``ParseException: Expected end of text`` raised from the middle of a tick
#: string.  The engine runs same-generation nodes in parallel, so three
#: relaxation figures rendering at once is the *normal* case, not an edge case,
#: and it failed two of three with no useful diagnostic.  Serialising the render
#: is the fix; the figures are milliseconds each.
_MPL_LOCK = threading.RLock()



def _finite_series(values: List[float]) -> List[float]:
    return [float("nan") if v is None else float(v) for v in values]


def _draw_band_structure(axes: Any, spectrum: Spectrum) -> None:
    """Bands on the k path, with the high-symmetry ticks the run resolved.

    The tick labels travel in ``metadata`` because they are properties of the
    path, not of the y values.  Without them the figure is a set of lines
    against a meaningless continuous axis -- the reader cannot tell where Γ is,
    and a band structure without a marked Γ is not a band structure.
    """
    xs = [float(v) for v in spectrum.x]
    width = min([len(xs)] + [len(row) for row in spectrum.curves]) if spectrum.curves else 0
    for index, row in enumerate(spectrum.curves):
        colour = _TRACE_COLOURS[index % len(_TRACE_COLOURS)]
        axes.plot(xs[:width], [float(v) for v in row[:width]],
                  color=colour, linewidth=0.9)
    axes.axhline(0.0, color=_ZERO_LINE, linewidth=0.8, linestyle="--")
    meta = spectrum.metadata or {}
    labels = [str(item) for item in (meta.get("tick_labels") or [])]
    positions = [float(v) for v in (meta.get("tick_positions") or [])]
    # Pair labels with positions defensively: a tick list longer than the label
    # list would otherwise shift every label onto the wrong high-symmetry point.
    for label, position in zip(labels, positions):
        axes.axvline(position, color=_ZERO_LINE, linewidth=0.5, alpha=0.6)
        axes.text(position, 1.0, f" {label}", transform=axes.get_xaxis_transform(),
                  fontsize=7, va="bottom", ha="left", color="#4b5563")
    fermi = meta.get("fermi_ev")
    if fermi is not None:
        axes.set_title(
            f"{spectrum.name or 'band structure'}   (E_F = {float(fermi):.3f} eV)"
        )


def _draw_dos(axes: Any, spectrum: Spectrum) -> None:
    """Total DOS, plus the orbital channels when the run resolved them.

    Orbital-resolved data arrives in ``metadata["pdos"]["curves"]``; the plain
    total is kept in ``y``.  Drawing the total as a filled envelope behind the
    channels makes the hybridisation at E_F visible without a second figure.
    """
    meta = spectrum.metadata or {}
    pdos = meta.get("pdos") or {}
    xs = pdos.get("x") or spectrum.x
    orbital_labels = [str(item) for item in (pdos.get("orbitals") or [])]
    curves = pdos.get("curves") or []
    if curves and orbital_labels:
        totals = [float(sum(column)) for column in zip(*curves)] if curves else []
        if totals:
            axes.plot(xs, totals, color="#1f6feb", linewidth=1.4,
                      label="total", zorder=3)
        for index, row in enumerate(curves):
            colour = _TRACE_COLOURS[(index + 1) % len(_TRACE_COLOURS)]
            label = (
                orbital_labels[index] if index < len(orbital_labels) else f"c{index}"
            )
            axes.plot(xs, [float(v) for v in row], color=colour, linewidth=0.9,
                      label=label, zorder=2)
        axes.legend(fontsize=7, frameon=False, ncols=min(5, len(orbital_labels) + 1))
    else:
        if not spectrum.y:
            raise ValueError("态密度谱没有可绘制的数据（y 为空）")
        axes.plot(spectrum.x, spectrum.y, color="#1f6feb", linewidth=1.2)
        axes.fill_between(spectrum.x, spectrum.y, color="#1f6feb", alpha=0.18)
    axes.axvline(0.0, color=_ZERO_LINE, linewidth=0.8, linestyle="--")


def _set_log_bounds(axes: Any, values: List[float]) -> None:
    """Pad a log axis around ``values`` by half a decade each side.

    matplotlib's autoscale cannot recover from a leading NaN, and the default
    decade grid puts the axis far from the data.  Bounding explicitly is what
    makes the trace visible; the alternative is a figure with an empty panel
    and no diagnostic.
    """
    positive = [float(v) for v in values if float(v) > 0.0]
    if not positive:
        return
    low = min(positive) / 10.0 ** 0.5
    high = max(positive) * 10.0 ** 0.5
    axes.set_ylim(low, high)


def _draw_convergence(axes: Any, spectrum: Spectrum, table: Any = None, trace: int = 0) -> None:
    """Energy / force / stress against the relaxation step.

    Each series gets its own y axis: energy lives at ~-16.7 eV while the force
    spans five orders of magnitude, so one shared axis renders the force and
    stress traces as flat lines on the baseline and the figure claims
    convergence it cannot show.

    The force and stress axes are logarithmic.  A relaxation's residual force
    falls geometrically -- 0.72, 0.15, 0.0098, 0.0005 eV/Å -- and on a linear
    axis the last four steps are indistinguishable from zero, which is exactly
    the opposite of what the figure exists to show.  A log axis also cannot
    display a zero or a negative ordinate, which is why the start-of-run gap
    (an unmeasured value, not a zero) is honoured by simply beginning the line
    where the data begins.

    No zero reference line is drawn here.  The energy trace sits at -17.6 eV,
    so a line at zero stretches the axis to a 17 eV range and flattens the
    entire energy curve into a horizontal rule -- a figure that renders the
    quantity it is about as a straight line.
    """
    labels = [str(item) for item in (spectrum.curve_labels or [])]
    series = spectrum.traces()
    units = ("eV", "eV/Å", "GPa")
    # ``trace > 0`` isolates one series into its own figure.  The delivered set
    # wants energy, force and stress as three separate products, and a
    # three-axis overlay is the wrong answer for all three: they differ in unit
    # *and* by three to four orders of magnitude, so the smallest one is a flat
    # line on its own axis no matter how the axes are arranged.
    if trace > 0 and trace <= len(series):
        series = [series[trace - 1]]
        labels = [labels[trace - 1]] if trace - 1 < len(labels) else [f"trace {trace - 1}"]
        units = (units[trace - 1],) if trace - 1 < len(units) else units
    axes2 = axes.twinx() if len(series) > 1 else None
    axes3 = axes.twinx() if len(series) > 2 else None
    handles = []
    legend_labels = []
    for index, row in enumerate(series):
        # The *source* index decides the scale, not the position in the
        # isolated subset: force and stress need a log axis whichever slot they
        # occupy, and energy does not.  Deciding on ``index`` would give an
        # isolated force plot a linear axis and an isolated energy plot a log one.
        source_index = (trace - 1) if (trace > 0 and len(series) == 1) else index
        target = axes if index == 0 else (axes2 if index == 1 else axes3)
        colour = _TRACE_COLOURS[source_index % len(_TRACE_COLOURS)]
        label = labels[index] if index < len(labels) else f"trace {index}"
        line, = target.plot(
            spectrum.x, _finite_series(row), color=colour, linewidth=1.1,
            marker="o", markersize=2.6, label=label,
        )
        handles.append(line)
        legend_labels.append(label)
        unit = units[index] if index < len(units) else ""
        target.set_ylabel(f"{label}\n({unit})", color=colour, fontsize=8)
        target.tick_params(axis="y", labelcolor=colour, labelsize=7)
        target.grid(True, linewidth=0.4, alpha=0.35)
        if source_index > 0:
            # Magnitude, not the signed value: a log axis has no room for a
            # negative ordinate, and the residual force is genuinely negative
            # (the cell is under tension at every step of a relaxation that
            # started compressed).  Plotting the signed values on this scale
            # drops the whole trace -- matplotlib silently omits non-positive
            # points, so the figure would show two of three curves with no
            # error and no warning.  The sign is reported in the axis label
            # rather than lost.
            magnitudes = [
                float("nan") if value != value else abs(float(value)) for value in row
            ]
            usable = [value for value in magnitudes if value == value and value > 0.0]
            if usable:
                line.set_ydata(magnitudes)
                line.set_label(f"|{label}|")
                legend_labels[index] = f"|{label}|"
                target.set_ylabel(f"|{label}|\n({unit})", color=colour, fontsize=8)
                # The leading NaN (the start-of-run gap) leaves matplotlib with
                # nothing to scale against, so it falls back to decade ticks
                # around 1 and clips every real value -- the relaxation's final
                # force is ~5e-4 eV/A, three decades below the axis it is
                # plotted on, so the trace vanishes with no error.  The bounds
                # are set from the data instead.
                _set_log_bounds(target, usable)
                # Scale last: ``set_yscale`` validates against the data already
                # on the axes, so switching it before the bounds are in place
                # emits "Data has no positive values, and therefore cannot be
                # log-scaled" -- a warning about a plot that is about to be
                # drawn correctly.
                target.set_yscale("log")

    if axes3 is not None:
        # Two twinned axes share a side; the third would draw its labels on top
        # of the second's, so it is offset out of the way.
        axes3.spines["right"].set_position(("outward", 34))
    axes.legend(handles, legend_labels, fontsize=7, frameon=False, loc="best")
    for target in (axes, axes2, axes3):
        if target is not None:
            target.set_xlabel("relaxation step")


@register_node
class FigureExportNode(ScientificNode):
    """Render an upstream spectrum or table into a PNG product figure.

    Written because a DFT run whose numbers live only inside an HTML report is
    not finished: the deliverable is the *figures*.  The node picks the figure
    kind from the upstream object (band structure, DOS, PDOS, relaxation
    convergence) or from ``kind``, renders it with matplotlib and writes a PNG
    into the run's artefact folder.
    """

    name = "Figure Export"
    category = "Report"
    description = (
        "把上游能带 / 态密度 / 投影态密度 / 弛豫收敛结果渲染为独立 PNG 产物图。"
    )
    tags = ["figure", "png", "plot", "出图", "产物", "artifact"]
    capabilities = ["writes_files"]
    icon = "image"

    input_ports = [
        Port("spectrum", "Spectrum", "待出图的光谱（能带 / 态密度 / 收敛）", optional=True, multi=True),
        Port("table", "Table", "可绘制的表格（弛豫历史）", optional=True, multi=True),
    ]
    output_ports = [
        Port("text", "Text", "导出文件的路径清单"),
        Port("spectrum", "Spectrum", "透传的上游光谱"),
    ]
    parameters = [
        ParameterSpec(
            "kind", "enum", "auto", "图形类型（auto = 按上游对象推断）",
            options=[
                ("auto", "自动 / Auto"),
                ("band_structure", "能带结构 / Band structure"),
                ("dos", "态密度 / DOS"),
                ("pdos", "投影态密度 / PDOS"),
                ("relax_convergence", "弛豫收敛 / Relaxation convergence"),
            ],
        ),
        ParameterSpec("filename", "string", "", "文件名（留空按类型自动命名）"),
        ParameterSpec("title", "string", "", "图题（留空用默认标题）"),
        ParameterSpec(
            "trace", "integer", 0,
            "要画的第几条曲线（0 = 全部；弛豫收敛图常用 1 = 力、2 = 应力）",
            min=0, max=16, advanced=True,
        ),
        ParameterSpec("dpi", "integer", 140, "分辨率 dpi", min=72, max=400, advanced=True),
        ParameterSpec("figsize", "string", "7.0x4.6", "画布尺寸（英寸，宽x高）", advanced=True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        spectra = [item for item in collect(inputs.get("spectrum")) if isinstance(item, Spectrum)]
        tables = [item for item in collect(inputs.get("table")) if isinstance(item, Table)]
        if not spectra and not tables:
            raise ValueError("FigureExportNode 需要上游的 spectrum 或 table 输入")

        requested = str(self.get_param("kind", "auto") or "auto")
        plt = _require_matplotlib()

        written: List[str] = []
        kinds: List[str] = []
        # One figure per upstream object; a spectrum wins over a table because
        # it already carries the axis labels and units.
        sources: List[Any] = list(spectra) if spectra else list(tables)
        for index, source in enumerate(sources):
            kind = self._kind_for(requested, source, index)
            kinds.append(kind)
            filename = self._filename_for(kind, index, len(sources))
            payload = self._render(plt, source, kind, index)
            written.append(write_artifact(ctx, filename, payload))

        summary = Text(
            text="\n".join(written),
            name=f"{len(written)} figure(s): {', '.join(kinds)}",
        )
        summary.metadata.update({
            "format": "png",
            "figures": written,
            "kinds": kinds,
            "count": len(written),
        })
        self.log(f"wrote {len(written)} figure(s): {', '.join(written)}")
        return {
            "text": summary,
            "spectrum": spectra[0] if spectra else None,
        }

    # -- helpers ------------------------------------------------------------- #
    def _kind_for(self, requested: str, source: Any, index: int) -> str:
        if requested and requested != "auto":
            return requested
        if isinstance(source, Table):
            return "relax_convergence"
        mode = str(getattr(source, "mode", "") or "")
        if mode == "Bands":
            return "band_structure"
        if mode == "PDOS":
            return "pdos"
        if mode == "DOS":
            return "dos"
        if mode == "Convergence":
            return "relax_convergence"
        # Fall back on the orbit/peak shape so an unfamiliar upstream object
        # still gets the most plausible figure rather than a hard failure.
        return "dos" if getattr(source, "peaks", None) else "relax_convergence"

    def _filename_for(self, kind: str, index: int, total: int) -> str:
        stem = str(self.get_param("filename", "") or "").strip()
        if not stem:
            spec = FIGURE_KINDS.get(kind, FIGURE_KINDS["auto"])
            stem = str(spec.get("stem") or "figure")
        stem = _figure_stem(stem)
        if total > 1:
            return f"{stem}_{index + 1}.png"
        return f"{stem}.png"

    def _render(self, plt: Any, source: Any, kind: str, index: int) -> bytes:
        # Held for the whole draw: creating the figure, plotting, and closing it
        # all touch matplotlib's shared parser state.
        with _MPL_LOCK:
            return self._render_locked(plt, source, kind, index)

    def _render_locked(self, plt: Any, source: Any, kind: str, index: int) -> bytes:
        spec = FIGURE_KINDS.get(kind, FIGURE_KINDS["auto"])
        width, height = self._figsize()
        dpi = int(self.get_param("dpi", 140) or 140)
        figure, axes = plt.subplots(figsize=(width, height), dpi=dpi)
        try:
            if kind == "band_structure":
                self._require_spectrum(source, kind)
                _draw_band_structure(axes, source)
            elif kind in {"dos", "pdos"}:
                self._require_spectrum(source, kind)
                _draw_dos(axes, source)
            elif kind == "relax_convergence":
                self._draw_convergence(axes, source)
            else:  # pragma: no cover - guarded by _kind_for
                raise ValueError(f"未知的图形类型：{kind}")
            axes.set_title(self._title(spec, source))
            axes.set_xlabel(spec.get("x_label") or self._fallback_label(source, "x"))
            if kind != "relax_convergence":
                axes.set_ylabel(spec.get("y_label") or self._fallback_label(source, "y"))
                axes.axhline(0.0, color=_ZERO_LINE, linewidth=0.6, alpha=0.5)
                axes.grid(True, linewidth=0.4, alpha=0.3)
            figure.tight_layout()
            buffer = io.BytesIO()
            figure.savefig(buffer, format="png")
            return buffer.getvalue()
        finally:
            plt.close(figure)

    def _draw_convergence(self, axes: Any, source: Any) -> None:
        """Dispatch convergence drawing to a spectrum or a relaxation table."""
        if isinstance(source, Table):
            xs = [float(row[0]) for row in source.rows if row]
            energy = self._table_column(source, ("energy", "e (ev)"))
            force = self._table_column(source, ("force",))
            stress = self._table_column(source, ("stress",))
            if energy is None and force is None and stress is None:
                raise ValueError(
                    "弛豫表格没有 energy / force / stress 列，实际列为："
                    f"{[str(c) for c in source.columns]}"
                )
            series: List[List[float]] = []
            labels: List[str] = []
            for column, name in ((energy, "energy"), (force, "force"),
                                 (stress, "stress")):
                if column is not None:
                    series.append(column)
                    labels.append(name)
            spectrum = Spectrum(
                x=xs, curves=[[float("nan") if v is None else float(v) for v in row] for row in series],
                curve_labels=labels, mode="Convergence", y_unit="mixed units",
            )
            _draw_convergence(axes, spectrum, trace=self._trace_index())
            return
        _draw_convergence(axes, source, trace=self._trace_index())

    def _trace_index(self) -> int:
        """Which single trace to isolate (0 = plot them all)."""
        return max(0, int(self.get_param("trace", 0) or 0))

    @staticmethod
    def _table_column(table: Table, keys: tuple) -> List[Any] | None:
        """First column whose header contains any of ``keys``, as values."""
        columns = [str(c).lower() for c in table.columns]
        for index, header in enumerate(columns):
            if any(key in header for key in keys):
                return [row[index] if index < len(row) else None for row in table.rows]
        return None

    @staticmethod
    def _require_spectrum(source: Any, kind: str) -> None:
        if not isinstance(source, Spectrum):
            raise ValueError(f"{kind} 图形需要 Spectrum 输入，收到 {type(source).__name__}")
        if not source.x:
            raise ValueError(f"{kind} 图形需要非空的 x 轴，收到空光谱")
        if not source.curves and not source.y:
            raise ValueError(
                f"{kind} 图形需要可绘制的数据：该光谱既没有 curves 也没有 y"
            )

    def _title(self, spec: Dict[str, str], source: Any) -> str:
        custom = str(self.get_param("title", "") or "").strip()
        if custom:
            return custom
        name = str(getattr(source, "name", "") or "").strip()
        default = str(spec.get("title") or "").strip()
        # An isolated trace names its own figure.  Three convergence figures
        # all captioned "弛豫收敛" are indistinguishable once they sit in the
        # same folder -- which of the three is the force one is answerable only
        # by opening each file.
        if self._trace_index() > 0:
            labels = [str(item) for item in (getattr(source, "curve_labels", None) or [])]
            picked = self._trace_index() - 1
            zh = {"energy": "能量", "force": "力", "stress": "应力"}
            en = {"energy": "energy", "force": "residual force", "stress": "stress"}
            if picked < len(labels):
                key = labels[picked].strip("| ")
                default = (
                    f"弛豫{zh.get(key, key)}收敛 / Relaxation {en.get(key, key)} convergence"
                )
                # The spectrum's own name already ends in "relaxation
                # convergence"; concatenated it would read "…relaxation
                # convergence — 弛豫力收敛 / Relaxation residual force
                # convergence", so the cell and the lattice are kept instead.
                return f"{name.split(' relaxation')[0] or name} — {default}" if name else default
        if name and default:
            return f"{name} — {default}"
        return name or default or "figure"

    @staticmethod
    def _fallback_label(source: Any, axis: str) -> str:
        value = str(getattr(source, f"{axis}_unit", "") or "")
        return value or ("x" if axis == "x" else "intensity")

    def _figsize(self) -> tuple:
        raw = str(self.get_param("figsize", "7.0x4.6") or "").replace("×", "x").strip()
        try:
            width, _, height = raw.partition("x")
            w, h = float(width), float(height)
            if w > 0.5 and h > 0.5:
                return w, h
        except (TypeError, ValueError):
            pass
        return 7.0, 4.6
