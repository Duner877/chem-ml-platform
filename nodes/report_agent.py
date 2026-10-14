"""Report agent node: turn workflow outputs into a shareable document.

``ReportAgentNode`` collects every connected scientific object, builds a
structured :class:`~workflow_engine.objects.ScientificReport` and renders it in
the requested format (Markdown / HTML / PDF).  The rendered document is written
to the run artefact folder and its path recorded in the report metadata, so a
downstream :class:`~nodes.io.ExportNode` (or the REST artifact endpoint) can
serve it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from report_agent import gather, render
from report_agent.renderers import RenderResult
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import ScientificReport, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import collect, write_artifact

__all__ = ["ReportAgentNode"]

FORMATS = ["markdown", "html", "pdf"]


@register_node
class ReportAgentNode(ScientificNode):
    """Assemble a Markdown / HTML / PDF report from upstream objects."""

    name = "Report Agent"
    category = "Agent/Reporting"
    description = "汇总上游科学对象，自动生成 Markdown / HTML / PDF 研究报告并写入产物目录。"
    version = "0.7.1"
    tags = ["agent", "report", "markdown", "html", "pdf", "export"]
    capabilities = ["writes_files"]
    icon = "RA"

    input_ports = [Port("data", "Any", "待汇总的科学对象", optional=True, multi=True)]
    output_ports = [
        Port("report", "ScientificReport", "结构化报告对象"),
        Port("text", "Text", "渲染后的文档文本 / 路径"),
    ]

    parameters = [
        ParameterSpec("title", "string", "Chem ML Platform Report", "报告标题"),
        ParameterSpec("summary", "text", "", "报告摘要（可选）"),
        ParameterSpec("format", "enum", "markdown", "输出格式", options=FORMATS),
        ParameterSpec("filename", "string", "report", "产物文件名（不含扩展名）"),
        ParameterSpec("include_provenance", "boolean", True, "写入执行溯源、证据分级与结果局限"),
        ParameterSpec("limitations", "text", "", "自定义结果局限（每行一条，留空用平台默认）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        objects = collect(inputs.get("data"))
        title = str(self.get_param("title", "Chem ML Platform Report") or "Chem ML Platform Report")
        summary = str(self.get_param("summary", "") or "")
        fmt = str(self.get_param("format", "markdown") or "markdown").lower()
        filename = str(self.get_param("filename", "report") or "report").strip() or "report"
        include_provenance = bool(self.get_param("include_provenance", True))
        raw_limitations = str(self.get_param("limitations", "") or "")
        limitations = [line.strip() for line in raw_limitations.splitlines() if line.strip()] or None

        # v0.7.1 (task H/J): cite the live provenance collected by the engine.
        provenance = getattr(ctx, "provenance", None) if include_provenance else None
        workflow_meta = getattr(ctx, "workflow_meta", None) if include_provenance else None

        content = gather(
            objects,
            title=title,
            summary=summary,
            provenance=provenance,
            limitations=limitations,
            workflow_meta=workflow_meta,
        )
        result: RenderResult = render(content, fmt=fmt)

        # Persist the rendered document as a run artefact.
        extension = result.ext
        if ctx is not None:
            artifact_path = write_artifact(ctx, f"{filename}.{extension}", result.data)
        else:
            out_dir = Path("output")
            out_dir.mkdir(parents=True, exist_ok=True)
            artifact_path = str(out_dir / f"{filename}.{extension}")
            if isinstance(result.data, bytes):
                Path(artifact_path).write_bytes(result.data)
            else:
                Path(artifact_path).write_text(result.data, encoding="utf-8")

        # Build the structured report object for downstream nodes.
        report = ScientificReport(title=title, abstract=summary)
        for section in content.sections:
            report.add_section(
                section.heading,
                section.body,
                figures=[section.figure] if section.figure else None,
                tables=[section.table] if section.table else None,
            )
        if fmt == "markdown":
            report.markdown_path = artifact_path
        elif fmt == "html":
            report.html_path = artifact_path
        report.metadata.update(
            {
                "format": fmt,
                "engine": result.engine,
                "mime": result.mime,
                "artifact": artifact_path,
                "section_count": len(content.sections),
                "provenance_included": bool(include_provenance),
                "workflow_meta": dict(workflow_meta or {}),
            }
        )

        text_body = result.data if isinstance(result.data, str) else content.title
        text = Text(
            name="report",
            text=text_body,
            data={
                "format": fmt,
                "engine": result.engine,
                "mime": result.mime,
                "path": artifact_path,
                "sections": len(content.sections),
            },
        )

        self.log(f"ReportAgentNode: wrote {fmt} report -> {artifact_path}")
        return {"report": report, "text": text}
