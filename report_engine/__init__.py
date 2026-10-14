"""Report export engine (v0.7 -- spec section 13).

Exports run results into three formats -- Markdown, HTML and DOCX -- from
**real run data only**: the caller passes a :class:`ReportModel` whose fields
are filled from :class:`workflow_engine.engine.RunResult` plus optional
experiment metadata.  Nothing here invents content: missing sections are
omitted, and citations are never fabricated.

Integrity: every export returns an :class:`ExportResult` including the file
size and a SHA-256 digest, so callers can verify the artefact exists and is
non-empty after writing.
"""

from __future__ import annotations

import hashlib
import html as html_mod
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["ReportModel", "ReportSection", "ExportResult", "ReportExporter"]


@dataclass
class ReportSection:
    """One ordered section of the report."""

    title: str
    body: str = ""                 # markdown-ish text (rendered per format)
    table: Optional[List[List[str]]] = None   # optional table, first row = header
    image_path: Optional[str] = None          # optional artefact image reference
    image_caption: str = ""

    def render_markdown(self) -> str:
        parts = [f"## {self.title}", ""]
        if self.body:
            parts += [self.body, ""]
        if self.table:
            parts += [_md_table(self.table), ""]
        if self.image_path:
            caption = self.image_caption or "figure"
            parts += [f"![{caption}]({self.image_path})", ""]
        return "\n".join(parts)


@dataclass
class ReportModel:
    """Everything a report contains, sourced from a real run."""

    title: str = "Scientific Report"
    project: str = ""
    sample: str = ""
    research_question: str = ""
    methods: str = ""
    run_id: str = ""
    workflow_name: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    software_versions: Dict[str, str] = field(default_factory=dict)
    input_files: List[str] = field(default_factory=list)
    sections: List[ReportSection] = field(default_factory=list)
    conclusions: str = ""
    next_steps: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    references: List[str] = field(default_factory=list)   # user-provided only

    # -- build from engine -------------------------------------------------- #
    @classmethod
    def from_run(
        cls,
        run_result: Any,
        node_descriptions: Optional[Dict[str, str]] = None,
        **overrides: Any,
    ) -> "ReportModel":
        """Fill a model from a :class:`workflow_engine.engine.RunResult`."""
        descriptions = node_descriptions or {}
        sections: List[ReportSection] = []
        exec_rows: List[List[str]] = [["Node", "Type", "Status", "Duration (ms)"]]
        warnings: List[str] = []
        errors: List[str] = []
        for node_id, record in getattr(run_result, "records", {}).items():
            exec_rows.append(
                [
                    node_id,
                    getattr(record, "node_type", ""),
                    getattr(record, "status", ""),
                    f"{getattr(record, 'duration_ms', 0.0):.1f}",
                ]
            )
            warnings.extend(
                line for line in getattr(record, "logs", [])
                if str(line).lower().startswith("[warn")
            )
            if getattr(record, "error", ""):
                errors.append(f"{node_id}: {record.error}")
        if exec_rows:
            sections.append(
                ReportSection(
                    title="节点执行记录 / Node Execution Record",
                    table=exec_rows,
                )
            )
        for record in getattr(run_result, "records", {}).values():
            logs = [l for l in getattr(record, "logs", []) if not str(l).lower().startswith("[warn")]
            if logs:
                sections.append(
                    ReportSection(
                        title=f"节点日志 / {record.node_id}",
                        body="\n".join(f"- `{line}`" for line in logs[:50]),
                    )
                )
        model = cls(
            run_id=getattr(run_result, "run_id", ""),
            workflow_name=getattr(run_result, "workflow_name", ""),
            sections=sections,
            warnings=warnings,
            errors=errors,
            software_versions=dict(overrides.pop("software_versions", {}) or {}),
        )
        for key, value in overrides.items():
            if hasattr(model, key):
                setattr(model, key, value)
        return model


@dataclass
class ExportResult:
    """Integrity-verifiable export outcome."""

    path: str
    format: str
    bytes_written: int
    sha256: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "format": self.format,
            "bytes": self.bytes_written,
            "sha256": self.sha256,
        }


class ReportExporter:
    """Writes :class:`ReportModel` to Markdown / HTML / DOCX."""

    def __init__(self, output_dir: str | Path):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # -- public API ---------------------------------------------------------- #
    def export_markdown(self, model: ReportModel, filename: str = "report.md") -> ExportResult:
        text = self.render_markdown(model)
        return self._write(filename, text.encode("utf-8"), "markdown")

    def export_html(self, model: ReportModel, filename: str = "report.html") -> ExportResult:
        return self._write(filename, self.render_html(model).encode("utf-8"), "html")

    def export_docx(self, model: ReportModel, filename: str = "report.docx") -> ExportResult:
        path = self.output_dir / filename
        try:
            from docx import Document
        except ImportError as exc:  # honest failure, no fake docx
            raise RuntimeError(
                "DOCX 导出需要 python-docx：pip install python-docx"
            ) from exc
        document = Document()
        document.add_heading(model.title, level=0)
        meta = document.add_paragraph()
        meta.add_run(
            f"Run ID: {model.run_id or 'n/a'} · Workflow: {model.workflow_name or 'n/a'} · "
            f"Generated: {model.generated_at}"
        )
        if model.project:
            document.add_heading("项目 / Project", level=1)
            document.add_paragraph(model.project)
        if model.sample:
            document.add_heading("样品 / Sample", level=1)
            document.add_paragraph(model.sample)
        if model.research_question:
            document.add_heading("研究问题 / Research Question", level=1)
            document.add_paragraph(model.research_question)
        if model.methods:
            document.add_heading("方法 / Methods", level=1)
            document.add_paragraph(model.methods)
        if model.input_files:
            document.add_heading("输入数据 / Input Data", level=1)
            for item in model.input_files:
                document.add_paragraph(item, style="List Bullet")
        for section in model.sections:
            document.add_heading(section.title, level=1)
            if section.body:
                document.add_paragraph(section.body)
            if section.table:
                self._add_docx_table(document, section.table)
            # images: referenced by relative path note (artifacts stay files)
        if model.warnings:
            document.add_heading("警告 / Warnings", level=1)
            for w in model.warnings:
                document.add_paragraph(w, style="List Bullet")
        if model.errors:
            document.add_heading("错误 / Errors", level=1)
            for e in model.errors:
                document.add_paragraph(e, style="List Bullet")
        if model.conclusions:
            document.add_heading("结论 / Conclusions", level=1)
            document.add_paragraph(model.conclusions)
        if model.limitations:
            document.add_heading("限制 / Limitations", level=1)
            for item in model.limitations:
                document.add_paragraph(item, style="List Bullet")
        if model.next_steps:
            document.add_heading("下一步 / Next Steps", level=1)
            for item in model.next_steps:
                document.add_paragraph(item, style="List Number")
        if model.references:
            document.add_heading("参考文献 / References", level=1)
            for item in model.references:
                document.add_paragraph(item, style="List Number")
        if model.software_versions:
            document.add_heading("软件版本 / Software Versions", level=1)
            for name, version in model.software_versions.items():
                document.add_paragraph(f"{name}: {version}", style="List Bullet")
        document.save(str(path))
        return self._result(path, "docx")

    # -- markdown -------------------------------------------------------------- #
    def render_markdown(self, model: ReportModel) -> str:
        parts = [
            f"# {model.title}",
            "",
            f"- **Run ID**: `{model.run_id or 'n/a'}`",
            f"- **Workflow**: {model.workflow_name or 'n/a'}",
            f"- **Generated**: {model.generated_at}",
            "",
        ]
        if model.project:
            parts += [f"**项目**: {model.project}", ""]
        if model.sample:
            parts += [f"**样品**: {model.sample}", ""]
        if model.research_question:
            parts += ["## 研究问题 / Research Question", "", model.research_question, ""]
        if model.methods:
            parts += ["## 方法 / Methods", "", model.methods, ""]
        if model.input_files:
            parts += ["## 输入数据 / Input Data", ""]
            parts += [f"- `{f}`" for f in model.input_files] + [""]
        for section in model.sections:
            parts += [section.render_markdown()]
        if model.warnings:
            parts += ["## 警告 / Warnings", ""] + [f"- {w}" for w in model.warnings] + [""]
        if model.errors:
            parts += ["## 错误 / Errors", ""] + [f"- {e}" for e in model.errors] + [""]
        if model.conclusions:
            parts += ["## 结论 / Conclusions", "", model.conclusions, ""]
        if model.limitations:
            parts += ["## 限制 / Limitations", ""] + [f"- {l}" for l in model.limitations] + [""]
        if model.next_steps:
            parts += ["## 下一步 / Next Steps", ""]
            parts += [f"{i}. {s}" for i, s in enumerate(model.next_steps, 1)] + [""]
        if model.references:
            parts += ["## 参考文献 / References", ""]
            parts += [f"[{i}] {r}" for i, r in enumerate(model.references, 1)] + [""]
        if model.software_versions:
            parts += ["## 软件版本 / Software Versions", ""]
            parts += [f"- {k}: {v}" for k, v in model.software_versions.items()] + [""]
        return "\n".join(parts).rstrip() + "\n"

    # -- html ------------------------------------------------------------------- #
    def render_html(self, model: ReportModel) -> str:
        """HTML with escaped user text (no script injection)."""
        esc = html_mod.escape

        def table_html(rows: List[List[str]]) -> str:
            head = "".join(f"<th>{esc(c)}</th>" for c in rows[0])
            body = "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                for row in rows[1:]
            )
            return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"

        sections: List[str] = []
        for section in model.sections:
            chunk = [f"<h2>{esc(section.title)}</h2>"]
            if section.body:
                chunk.append(f"<p>{_inline_md(esc(section.body))}</p>")
            if section.table:
                chunk.append(table_html(section.table))
            if section.image_path:
                caption = esc(section.image_caption or "figure")
                chunk.append(
                    f'<figure><img src="{esc(section.image_path)}" alt="{caption}">'
                    f"<figcaption>{caption}</figcaption></figure>"
                )
            sections.append("\n".join(chunk))

        def bullets(items: List[str]) -> str:
            return "<ul>" + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>"

        body_parts = [f"<h1>{esc(model.title)}</h1>"]
        meta = esc(
            f"Run ID: {model.run_id or 'n/a'} · Workflow: "
            f"{model.workflow_name or 'n/a'} · Generated: {model.generated_at}"
        )
        body_parts.append(f"<p class='meta'>{meta}</p>")
        if model.research_question:
            body_parts += [f"<h2>研究问题</h2><p>{esc(model.research_question)}</p>"]
        if model.methods:
            body_parts += [f"<h2>方法</h2><p>{esc(model.methods)}</p>"]
        if model.input_files:
            body_parts += ["<h2>输入数据</h2>", bullets(model.input_files)]
        body_parts += sections
        if model.warnings:
            body_parts += ["<h2>警告</h2>", bullets(model.warnings)]
        if model.errors:
            body_parts += ["<h2>错误</h2>", bullets(model.errors)]
        if model.conclusions:
            body_parts += [f"<h2>结论</h2><p>{esc(model.conclusions)}</p>"]
        if model.limitations:
            body_parts += ["<h2>限制</h2>", bullets(model.limitations)]
        if model.next_steps:
            body_parts += [
                "<h2>下一步</h2>",
                "<ol>" + "".join(f"<li>{esc(s)}</li>" for s in model.next_steps) + "</ol>",
            ]
        if model.references:
            body_parts += [
                "<h2>参考文献</h2>",
                "<ol>" + "".join(f"<li>{esc(r)}</li>" for r in model.references) + "</ol>",
            ]
        versions = "".join(
            f"<li>{esc(k)}: {esc(v)}</li>" for k, v in model.software_versions.items()
        )
        if versions:
            body_parts += [f"<h2>软件版本</h2><ul>{versions}</ul>"]

        return (
            "<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
            "<title>" + esc(model.title) + "</title><style>"
            "body{font-family:'Segoe UI',system-ui,sans-serif;max-width:860px;"
            "margin:2rem auto;padding:0 1rem;color:#1a1a2e;line-height:1.6}"
            "table{border-collapse:collapse;width:100%;margin:1rem 0}"
            "th,td{border:1px solid #ccd;padding:.35rem .6rem;text-align:left}"
            "th{background:#f0f2f8}tr:nth-child(even) td{background:#fafbfe}"
            "img{max-width:100%}.meta{color:#667;font-size:.9em}"
            "</style></head><body>" + "\n".join(body_parts) + "</body></html>"
        )

    # -- internals ------------------------------------------------------------------ #
    def _write(self, filename: str, data: bytes, fmt: str) -> ExportResult:
        path = self.output_dir / filename
        path.write_bytes(data)
        return self._result(path, fmt)

    def _result(self, path: Path, fmt: str) -> ExportResult:
        data = path.read_bytes()
        if not data:
            raise RuntimeError(f"export integrity check failed: {path} is empty")
        return ExportResult(
            path=str(path),
            format=fmt,
            bytes_written=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
        )

    @staticmethod
    def _add_docx_table(document: Any, rows: List[List[str]]) -> None:
        if not rows:
            return
        table = document.add_table(rows=len(rows), cols=len(rows[0]))
        table.style = "Light Grid Accent 1"
        for r, row in enumerate(rows):
            for c, value in enumerate(row):
                table.cell(r, c).text = str(value)


# --------------------------------------------------------------------------- #
def _md_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "|" + "|".join(["---"] * len(rows[0])) + "|"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows[1:])
    return "\n".join([header, sep, body])


_CODE_SPAN = re.compile(r"`([^`]+)`")


def _inline_md(text: str) -> str:
    """Escape-then-style inline code for the HTML body (input pre-escaped)."""
    return _CODE_SPAN.sub(r"<code>\1</code>", text)
