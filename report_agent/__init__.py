"""Report Agent -- assemble scientific reports from workflow results.

A thin, dependency-light layer that collects arbitrary scientific objects and
renders them as **Markdown**, **HTML** or **PDF**::

    from report_agent import build_report

    result = build_report(
        objects=[molecule, spectrum, table],
        title="Caffeine analysis",
        format="html",
    )
    result.data          # the rendered document (str / bytes)
    result.mime          # "text/html"
    result.engine         # "jinja-free html"

The PDF backend uses matplotlib (already a platform dependency), so no extra
package is required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from .builders import DEFAULT_LIMITATIONS, ReportContent, ReportSection, gather
from .renderers import RenderResult, render, render_html, render_markdown, render_pdf

__all__ = [
    "DEFAULT_LIMITATIONS",
    "ReportContent",
    "ReportSection",
    "RenderResult",
    "gather",
    "render",
    "render_markdown",
    "render_html",
    "render_pdf",
    "build_report",
]


def build_report(
    objects: List[Any],
    title: str = "",
    summary: str = "",
    format: str = "markdown",
    path: Optional[Path] = None,
    provenance: Any = None,
    limitations: Optional[List[str]] = None,
    workflow_meta: Optional[Dict[str, Any]] = None,
) -> RenderResult:
    """Collect ``objects`` and render a report in ``format``.

    ``provenance`` (a :class:`provenance.ProvenanceCollector`, its ``to_dict()``
    form or a list of records) adds the execution-provenance and evidence-grading
    sections; ``limitations`` overrides the default scientific-limitation list.
    """
    content = gather(
        objects,
        title=title,
        summary=summary,
        provenance=provenance,
        limitations=limitations,
        workflow_meta=workflow_meta,
    )
    return render(content, fmt=format, path=path)
