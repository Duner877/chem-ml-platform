"""Turn arbitrary scientific objects into report sections.

:mod:`report_agent.builders` is format agnostic: it inspects each incoming
:class:`~workflow_engine.objects.ScientificObject` and produces a flat list of
:class:`ReportSection` blocks (heading, text, optional figure, optional table)
that the renderers turn into Markdown / HTML / PDF.
"""

from __future__ import annotations

import io
import textwrap
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow_engine.objects import (
    Image,
    Material,
    Molecule,
    ScientificReport,
    Spectrum,
    Table,
    Text,
)

__all__ = ["ReportSection", "ReportContent", "gather", "provenance_sections", "DEFAULT_LIMITATIONS"]


#: Platform-wide limitations that a v0.7.1 report must state explicitly
#: (task J: distinguish measured / inferred / approximated / unverified).
DEFAULT_LIMITATIONS: List[str] = [
    "内部近似计算（内置引擎）与外部真实科研软件执行已分别标注，二者不可互相替代。",
    "未经真实外部软件环境验证的连接器返回的是内部近似结果，不得视为专业软件计算。",
    "模型中未通过基准验证的算法其准确率未获保证；置信度在单通道场景下未经跨候选标定，不能当作概率使用。",
    "报告中的谱图与结构为计算结果或模型推断，除非明确标注为实测数据，否则不代表实验测量。",
    "样例数据的来源与许可见 datasets/README.md；非实测数据不得用于支持科学结论。",
]


@dataclass
class ReportSection:
    """One block of a report."""

    heading: str
    body: str = ""
    figure: Optional[bytes] = None
    table: Optional[Dict[str, Any]] = None


@dataclass
class ReportContent:
    """A fully assembled, renderer-ready report."""

    title: str = "Chem ML Platform Report"
    summary: str = ""
    sections: List[ReportSection] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Provenance / limitations (v0.7.1 tasks H and J)
# --------------------------------------------------------------------------- #
def _normalise_provenance(provenance: Any) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Return ``(environment, node_records)`` from any supported provenance form."""
    if provenance is None:
        return {}, []
    if hasattr(provenance, "to_dict"):  # ProvenanceCollector
        provenance = provenance.to_dict()
    if isinstance(provenance, dict):
        environment = dict(provenance.get("environment") or {})
        nodes = provenance.get("nodes") or {}
        if isinstance(nodes, dict):
            records = [dict(v) for v in nodes.values()]
        elif isinstance(nodes, list):
            records = [dict(v) for v in nodes]
        else:
            records = []
        return environment, records
    if isinstance(provenance, (list, tuple)):
        return {}, [dict(item) for item in provenance if isinstance(item, dict)]
    return {}, []


def _evidence_class(record: Dict[str, Any]) -> str:
    """Classify one execution record into an honest evidence level."""
    if record.get("external_software"):
        return "外部软件真实执行"
    if record.get("fallback_used"):
        return "内部近似（外部软件降级回退）"
    if record.get("provider") or record.get("model"):
        return "模型推断"
    if record.get("status") in {"failed", "skipped"}:
        return "未完成（无结果）"
    return "内部确定性计算"


def provenance_sections(
    provenance: Any,
    workflow_meta: Optional[Dict[str, Any]],
    limitations: Optional[List[str]],
) -> List[ReportSection]:
    """Build the execution-provenance, evidence-grading and limitations sections."""
    environment, records = _normalise_provenance(provenance)
    meta = dict(workflow_meta or {})
    sections: List[ReportSection] = []

    # -- execution provenance ------------------------------------------------- #
    if meta or environment or records:
        lines: List[str] = []
        if meta:
            lines.append(
                f"工作流：{meta.get('name', '')}  版本：{meta.get('version', '') or 'n/a'}  "
                f"运行 ID：{meta.get('run_id', '')}"
            )
            lines.append(
                f"节点数：{meta.get('node_count', len(records))}  边数：{meta.get('edge_count', 'n/a')}"
            )
        if environment:
            lines.append(
                "运行环境：Python {} / {} {} / {} / torch {}".format(
                    environment.get("python_version", "?"),
                    environment.get("os_name", "?"),
                    environment.get("platform_release", ""),
                    environment.get("machine", ""),
                    environment.get("torch_version", "") or "n/a",
                )
            )
            if environment.get("cuda_available"):
                lines.append(
                    "GPU：" + (", ".join(environment.get("gpu_names") or []) or "CUDA")
                    + f" (CUDA {environment.get('cuda_version', '')})"
                )

        table: Optional[Dict[str, Any]] = None
        if records:
            columns = [
                "node_id", "node_type", "node_version", "status", "duration_ms",
                "device", "provider", "model", "fallback", "random_seed", "deterministic",
            ]
            rows = [
                [
                    record.get("node_id", ""),
                    record.get("node_type", ""),
                    record.get("node_version", ""),
                    record.get("status", ""),
                    round(float(record.get("duration_ms", 0.0) or 0.0), 1),
                    record.get("device", ""),
                    record.get("provider", ""),
                    record.get("model", ""),
                    record.get("fallback_reason", "") if record.get("fallback_used") else "",
                    record.get("random_seed", "") if record.get("random_seed") is not None else "",
                    "yes" if record.get("deterministic", True) else "no",
                ]
                for record in records
            ]
            table = {"columns": columns, "rows": rows}
        sections.append(
            ReportSection(
                heading="执行溯源 / Execution provenance",
                body="\n".join(lines) or "无可用的执行溯源记录。",
                table=table,
            )
        )

    # -- evidence grading ----------------------------------------------------- #
    if records:
        buckets: Dict[str, int] = {}
        for record in records:
            key = _evidence_class(record)
            buckets[key] = buckets.get(key, 0) + 1
        body_lines = ["每条结果按其来源分级，报告不得把近似或推断当作实测：", ""]
        for key in (
            "外部软件真实执行",
            "内部确定性计算",
            "内部近似（外部软件降级回退）",
            "模型推断",
            "未完成（无结果）",
        ):
            if buckets.get(key):
                body_lines.append(f"  · {key}：{buckets[key]} 个节点")
        sections.append(
            ReportSection(heading="证据分级 / Evidence provenance", body="\n".join(body_lines))
        )

    # -- limitations ---------------------------------------------------------- #
    items = list(limitations) if limitations else list(DEFAULT_LIMITATIONS)
    body = "\n".join(f"  - {item}" for item in items)
    sections.append(ReportSection(heading="结果局限 / Scientific limitations", body=body))
    return sections


def _plot_spectrum(spectrum: Spectrum) -> Optional[bytes]:
    """Render a spectrum to PNG bytes (matplotlib, no hard dependency on PIL)."""
    if not getattr(spectrum, "x", None) or not getattr(spectrum, "y", None):
        return None
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        figure, axes = plt.subplots(figsize=(7.0, 3.4), dpi=110)
        axes.plot(spectrum.x, spectrum.y, color="#1f6feb", linewidth=0.9)
        for peak in getattr(spectrum, "peaks", [])[:20]:
            axes.plot([peak.x], [peak.intensity or peak.y], "o", color="#d7263d", markersize=3)
        axes.set_title(spectrum.name or spectrum.mode)
        axes.set_xlabel(spectrum.x_unit or "x")
        axes.set_ylabel(spectrum.y_unit or "intensity")
        figure.tight_layout()
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png")
        plt.close(figure)
        return buffer.getvalue()
    except Exception:
        return None


def _image_png(image: Image) -> Optional[bytes]:
    try:
        return image.to_png_bytes()
    except Exception:
        return None


def _wrap_table(table: Dict[str, Any], width: int = 90) -> str:
    columns = table.get("columns", [])
    rows = table.get("rows", [])
    if not columns:
        return ""
    col_w = max(8, width // len(columns))
    header = " | ".join(str(c)[:col_w] for c in columns)
    lines = [header, "-+-".join("-" * min(col_w, len(str(c))) for c in columns)]
    for row in rows[:50]:
        lines.append(" | ".join(str(cell)[:col_w] for cell in row))
    if len(rows) > 50:
        lines.append(f"... ({len(rows) - 50} more rows)")
    return "\n".join(lines)


def gather(
    objects: List[Any],
    title: str = "",
    summary: str = "",
    provenance: Any = None,
    limitations: Optional[List[str]] = None,
    workflow_meta: Optional[Dict[str, Any]] = None,
) -> ReportContent:
    """Convert a list of scientific objects into :class:`ReportContent`."""
    content = ReportContent(
        title=title or "Chem ML Platform Report",
        summary=summary or "",
    )
    for obj in objects:
        if isinstance(obj, Spectrum):
            content.sections.append(
                ReportSection(
                    heading=obj.name or "Spectrum",
                    body=obj.summary(),
                    figure=_plot_spectrum(obj),
                )
            )
        elif isinstance(obj, Image):
            content.sections.append(
                ReportSection(
                    heading=obj.name or "Image",
                    body=obj.summary(),
                    figure=_image_png(obj),
                )
            )
        elif isinstance(obj, Molecule):
            props = getattr(obj, "properties", {}) or {}
            body = f"SMILES: {obj.smiles}\nFormula: {getattr(obj, 'formula', '') or ''}\n"
            if props:
                body += "\nProperties:\n"
                for key, value in list(props.items())[:30]:
                    body += f"  {key}: {value}\n"
            content.sections.append(
                ReportSection(
                    heading=obj.name or obj.smiles or "Molecule", body=body.strip()
                )
            )
        elif isinstance(obj, Material):
            props = getattr(obj, "properties", {}) or {}
            body = f"Formula: {getattr(obj, 'formula', '') or ''}\n"
            body += f"Space group: {getattr(obj, 'spacegroup', '') or 'n/a'}\n"
            if props:
                body += "\nProperties:\n"
                for key, value in list(props.items())[:30]:
                    body += f"  {key}: {value}\n"
            content.sections.append(
                ReportSection(
                    heading=obj.name or getattr(obj, "formula", "") or "Material",
                    body=body.strip(),
                )
            )
        elif isinstance(obj, Table):
            content.sections.append(
                ReportSection(
                    heading=obj.name or "Table",
                    body=textwrap.shorten(obj.summary(), width=400) if hasattr(obj, "summary") else "",
                    table={"columns": obj.columns, "rows": obj.rows},
                )
            )
        elif isinstance(obj, Text):
            content.sections.append(
                ReportSection(heading=obj.name or "Note", body=obj.text)
            )
        elif isinstance(obj, ScientificReport):
            for section in getattr(obj, "sections", []):
                content.sections.append(
                    ReportSection(
                        heading=section.get("heading", "Section"),
                        body=section.get("text", ""),
                    )
                )
    if not content.sections:
        content.sections.append(
            ReportSection(heading="Empty", body="No scientific objects were provided.")
        )
    # v0.7.1 (tasks H/J): always append execution provenance, evidence grading and
    # scientific limitations so a report can never be read as an unsupported claim.
    content.sections.extend(provenance_sections(provenance, workflow_meta, limitations))
    return content


def table_to_text(table: Dict[str, Any]) -> str:
    return _wrap_table(table)
