"""Render :class:`~report_agent.builders.ReportContent` into documents.

Three output formats are supported, each with a self-contained implementation so
the report agent has no hard external dependencies:

* **Markdown** -- plain text, always available.
* **HTML**     -- styled single-file document (figures embedded as data URIs).
* **PDF**      -- produced with matplotlib's ``PdfPages`` backend (matplotlib is
  already a platform dependency for plotting), with figures on their own pages.
"""

from __future__ import annotations

import base64
import io
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .builders import ReportContent, ReportSection, _wrap_table

__all__ = [
    "RenderResult",
    "render_markdown",
    "render_html",
    "render_pdf",
    "render",
]


@dataclass
class RenderResult:
    """A rendered document plus its delivery metadata."""

    data: Any  # str for md/html, bytes for pdf
    mime: str
    ext: str
    engine: str


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #
def render_markdown(content: ReportContent) -> str:
    """Render the report as a Markdown string."""
    lines: List[str] = [f"# {content.title}", ""]
    if content.summary:
        lines.append(content.summary)
        lines.append("")
    for section in content.sections:
        lines.append(f"## {section.heading}")
        if section.body:
            lines.append("")
            lines.append(section.body)
        if section.table:
            lines.append("")
            lines.append("```")
            lines.append(_wrap_table(section.table))
            lines.append("```")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
def render_html(content: ReportContent) -> str:
    """Render the report as a self-contained HTML document."""
    parts: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>" + _esc(content.title) + "</title>",
        "<style>",
        "body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "max-width:860px;margin:40px auto;color:#1a1a1a;line-height:1.6;padding:0 16px;}",
        "h1{border-bottom:2px solid #1f6feb;padding-bottom:.3em;}",
        "h2{color:#1f6feb;margin-top:1.6em;}",
        "pre{background:#f6f8fa;border-radius:6px;padding:12px;overflow:auto;}",
        "img{max-width:100%;border:1px solid #ddd;border-radius:6px;margin:8px 0;}",
        "table{border-collapse:collapse;margin:8px 0;}",
        "td,th{border:1px solid #ddd;padding:6px 10px;}",
        "</style></head><body>",
        f"<h1>{_esc(content.title)}</h1>",
    ]
    if content.summary:
        parts.append(f"<p>{_esc(content.summary)}</p>")
    for section in content.sections:
        parts.append(f"<h2>{_esc(section.heading)}</h2>")
        if section.body:
            parts.append(f"<p>{_esc(section.body).replace(chr(10), '<br>')}</p>")
        if section.table:
            parts.append(_table_html(section.table))
        if section.figure:
            uri = "data:image/png;base64," + base64.b64encode(section.figure).decode("ascii")
            parts.append(f'<img src="{uri}" alt="{_esc(section.heading)}">')
    parts.append("</body></html>")
    return "\n".join(parts)


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _table_html(table: Dict[str, Any]) -> str:
    columns = table.get("columns", [])
    rows = table.get("rows", [])
    cells = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = ""
    for row in rows[:50]:
        body += "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in row) + "</tr>"
    if len(rows) > 50:
        body += f"<tr><td colspan='{len(columns)}'>... ({len(rows) - 50} more rows)</td></tr>"
    return f"<table><thead><tr>{cells}</tr></thead><tbody>{body}</tbody></table>"


# --------------------------------------------------------------------------- #
# PDF (matplotlib)
# --------------------------------------------------------------------------- #
def render_pdf(content: ReportContent, path: Optional[Path] = None) -> bytes:
    """Render the report to a PDF (matplotlib ``PdfPages``)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    target = Path(path) if path else Path("output") / "report.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)

    # Pre-compute a flat list of draw commands: (size, weight, text) or
    # ("figure", png_bytes).
    commands: List[Any] = [(15, "bold", content.title)]
    if content.summary:
        for wrapped in textwrap.wrap(content.summary, 95) or [""]:
            commands.append((9.5, "normal", wrapped))
    commands.append((9.5, "normal", ""))
    for section in content.sections:
        commands.append((12.5, "bold", section.heading))
        for wrapped in textwrap.wrap(section.body or "", 100) or [""]:
            commands.append((9.5, "normal", wrapped))
        if section.table:
            for line in _wrap_table(section.table).splitlines():
                commands.append((8.5, "normal", line))
        commands.append((9.5, "normal", ""))
        if section.figure:
            commands.append(("figure", section.figure))

    W, H = 8.27, 11.69  # A4 inches
    with PdfPages(str(target)) as pdf:
        figure = plt.figure(figsize=(W, H))
        axis = figure.add_axes([0, 0, 1, 1])
        axis.axis("off")
        y = H - 0.7
        for command in commands:
            if command[0] == "figure":
                # flush current page, draw the figure, then continue on a new page
                axis.set_xlim(0, 1)
                axis.set_ylim(0, 1)
                pdf.savefig(figure)
                plt.close(figure)
                figure = plt.figure(figsize=(W, H))
                axis = figure.add_axes([0, 0, 1, 1])
                axis.axis("off")
                y = H - 0.7
                try:
                    import matplotlib.image as mpimg

                    arr = mpimg.imread(io.BytesIO(command[1]), format="png")
                    axis.imshow(arr, extent=[0.08, 0.92, 0.08, 0.92], aspect="auto")
                except Exception:
                    pass
                pdf.savefig(figure)
                plt.close(figure)
                figure = plt.figure(figsize=(W, H))
                axis = figure.add_axes([0, 0, 1, 1])
                axis.axis("off")
                y = H - 0.7
                continue

            size, weight, text = command
            line_height = size * 1.5 / 72.0  # inches
            if y - line_height < 0.6:
                axis.set_xlim(0, 1)
                axis.set_ylim(0, 1)
                pdf.savefig(figure)
                plt.close(figure)
                figure = plt.figure(figsize=(W, H))
                axis = figure.add_axes([0, 0, 1, 1])
                axis.axis("off")
                y = H - 0.7
            axis.text(
                0.08,
                y / H,
                text,
                fontsize=size,
                fontweight=weight,
                va="top",
                ha="left",
                wrap=True,
            )
            y -= line_height
        axis.set_xlim(0, 1)
        axis.set_ylim(0, 1)
        pdf.savefig(figure)
        plt.close(figure)

    return target.read_bytes()


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def render(content: ReportContent, fmt: str = "markdown", path: Optional[Path] = None) -> RenderResult:
    """Render ``content`` in the requested ``fmt`` (markdown / html / pdf)."""
    fmt = str(fmt).lower()
    if fmt == "html":
        data = render_html(content)
        return RenderResult(data, "text/html", "html", "jinja-free html")
    if fmt == "pdf":
        data = render_pdf(content, path)
        return RenderResult(data, "application/pdf", "pdf", "matplotlib.pdf")
    data = render_markdown(content)
    return RenderResult(data, "text/markdown", "md", "markdown")
