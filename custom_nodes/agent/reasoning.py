"""Agent reasoning: interpret what the workflow actually produced.

The reasoner is the last stage of the agent pipeline.  It reads a
:class:`~workflow_engine.engine.RunResult` and extracts the scientific content:
candidate structures with confidences, ranked materials, spectral features,
and the artefacts that were written.  Everything is reported with an explicit
confidence and the evidence it rests on -- an agent that cannot say *why* it
concluded something is not useful in a lab.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from workflow_engine.objects import ScientificReport, Spectrum, Table, Text

__all__ = ["Finding", "Reasoner", "reason"]


class Finding:
    """One conclusion plus the evidence and confidence behind it."""

    __slots__ = ("text", "confidence", "evidence", "source_node")

    def __init__(
        self,
        text: str,
        confidence: float = 0.0,
        evidence: str = "",
        source_node: str = "",
    ) -> None:
        self.text = str(text)
        self.confidence = float(confidence)
        self.evidence = str(evidence)
        self.source_node = str(source_node)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 3),
            "evidence": self.evidence,
            "source_node": self.source_node,
        }

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<Finding {self.text[:48]!r} conf={self.confidence:.2f}>"


def _clip(value: float, low: float = 0.0, high: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return low
    return max(low, min(high, number))


class Reasoner:
    """Turn a run result into findings and a narrative."""

    def __init__(self, language: str = "zh") -> None:
        self.language = str(language or "zh")

    # -- entry point -------------------------------------------------------- #
    def reason(self, result: Any) -> Dict[str, Any]:
        """Analyse a run result (dict or :class:`RunResult`)."""
        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result or {})
        records = payload.get("records", {}) or {}
        findings: List[Finding] = []

        for node_id, record in records.items():
            if not isinstance(record, dict):
                continue
            if record.get("status") != "completed":
                continue
            findings.extend(self._from_record(node_id, record))

        failed = [
            node_id for node_id, record in records.items()
            if isinstance(record, dict) and record.get("status") == "failed"
        ]
        findings.sort(key=lambda item: item.confidence, reverse=True)
        return {
            "language": self.language,
            "status": payload.get("status", ""),
            "nodes_executed": len(records),
            "nodes_failed": failed,
            "findings": [item.to_dict() for item in findings],
            "narrative": self._narrative(payload, findings, failed),
            "artifacts": list(payload.get("artifacts", []) or []),
        }

    # -- per node extraction ------------------------------------------------ #
    def _from_record(self, node_id: str, record: Dict[str, Any]) -> List[Finding]:
        outputs = record.get("outputs", {}) or {}
        found: List[Finding] = []
        for port, value in outputs.items():
            found.extend(self._from_value(node_id, port, value))
        for message in record.get("logs", []) or []:
            found.append(
                Finding(
                    text=str(message),
                    confidence=0.3,
                    evidence="node log",
                    source_node=node_id,
                )
            )
        return found

    def _from_value(self, node_id: str, port: str, value: Any) -> List[Finding]:
        if value is None:
            return []
        # Tables: the most information dense artefact.
        if isinstance(value, dict) and "columns" in value and "rows" in value:
            return self._from_table(node_id, port, value)
        if isinstance(value, dict) and "sections" in value:
            return self._from_report(node_id, port, value)
        if isinstance(value, dict) and "candidates" in value:
            return self._from_match(node_id, port, value)
        if isinstance(value, dict) and ("x" in value and "y" in value):
            return self._from_spectrum(node_id, port, value)
        if isinstance(value, dict) and "text" in value:
            return self._from_text(node_id, port, value)
        return []

    def _from_table(self, node_id: str, port: str, table: Dict[str, Any]) -> List[Finding]:
        rows = table.get("rows", []) or []
        columns = table.get("columns", []) or []
        if not rows:
            return []
        preview = ", ".join(str(column) for column in columns[:6])
        return [
            Finding(
                text=f"{node_id} 产出 {len(rows)} 行结果（列: {preview}）",
                confidence=0.6,
                evidence=f"table port {port!r}",
                source_node=node_id,
            )
        ]

    def _from_report(self, node_id: str, port: str, report: Dict[str, Any]) -> List[Finding]:
        sections = report.get("sections", []) or []
        title = str(report.get("title", "") or node_id)
        if not sections:
            return []
        first = sections[0]
        text = str(first.get("text", "") or first.get("title", ""))[:200]
        return [
            Finding(
                text=f"{title}: {text}",
                confidence=0.7,
                evidence=f"report port {port!r}, {len(sections)} sections",
                source_node=node_id,
            )
        ]

    def _from_match(self, node_id: str, port: str, match: Dict[str, Any]) -> List[Finding]:
        candidates = match.get("candidates", []) or []
        if not candidates:
            return []
        best = candidates[0]
        name = str(best.get("name") or best.get("smiles") or best.get("molecule") or "?")
        score = _clip(best.get("score", best.get("confidence", 0.0)))
        return [
            Finding(
                text=f"最佳候选：{name}（得分 {score:.2f}）",
                confidence=_clip(0.4 + 0.6 * score),
                evidence=f"match port {port!r}, {len(candidates)} candidates",
                source_node=node_id,
            )
        ]

    def _from_spectrum(self, node_id: str, port: str, spectrum: Dict[str, Any]) -> List[Finding]:
        peaks = spectrum.get("peaks", []) or []
        mode = str(spectrum.get("mode") or spectrum.get("technique") or "spectrum")
        if not peaks:
            points = len(spectrum.get("x", []) or [])
            return [
                Finding(
                    text=f"{mode} 谱图采集完成（{points} 个数据点）",
                    confidence=0.4,
                    evidence=f"spectrum port {port!r}",
                    source_node=node_id,
                )
            ]
        strongest = max(peaks, key=lambda peak: float(peak.get("y", 0.0) or 0.0))
        return [
            Finding(
                text=(
                    f"{mode} 谱图：{len(peaks)} 个峰，最强峰位于 "
                    f"{float(strongest.get('x', 0.0)):.2f}"
                ),
                confidence=0.5,
                evidence=f"spectrum port {port!r}",
                source_node=node_id,
            )
        ]

    def _from_text(self, node_id: str, port: str, text: Dict[str, Any]) -> List[Finding]:
        body = str(text.get("text", "") or "").strip()
        if not body:
            return []
        return [
            Finding(
                text=body[:300],
                confidence=0.5,
                evidence=f"text port {port!r}",
                source_node=node_id,
            )
        ]

    # -- narrative ---------------------------------------------------------- #
    def _narrative(
        self,
        payload: Dict[str, Any],
        findings: List[Finding],
        failed: List[str],
    ) -> str:
        if self.language.startswith("en"):
            lines = [
                f"Workflow {payload.get('workflow_name', '')!r} finished with status "
                f"{payload.get('status', '')} in "
                f"{float(payload.get('duration_ms', 0) or 0):.0f} ms."
            ]
            if findings:
                lines.append("Key findings:")
                lines.extend(
                    f"  - [{item.confidence:.2f}] {item.text}" for item in findings[:8]
                )
            else:
                lines.append("No quantitative finding could be extracted.")
            if failed:
                lines.append("Failed nodes: " + ", ".join(failed))
            return "\n".join(lines)

        lines = [
            f"工作流 {payload.get('workflow_name', '')!r} 以状态 {payload.get('status', '')} "
            f"结束，耗时 {float(payload.get('duration_ms', 0) or 0):.0f} ms。"
        ]
        if findings:
            lines.append("主要结论：")
            lines.extend(
                f"  - [{item.confidence:.2f}] {item.text}" for item in findings[:8]
            )
        else:
            lines.append("未能从结果中提取定量结论。")
        if failed:
            lines.append("失败节点：" + "、".join(failed))
        return "\n".join(lines)

    # -- report conversion -------------------------------------------------- #
    def to_report(self, analysis: Dict[str, Any], title: str = "AI 分析报告") -> ScientificReport:
        """Package an analysis into a :class:`ScientificReport`."""
        sections: List[Dict[str, Any]] = [
            {"title": "结论摘要", "text": analysis.get("narrative", "")}
        ]
        for index, finding in enumerate(analysis.get("findings", [])[:10], start=1):
            sections.append(
                {
                    "title": f"结论 {index}（置信度 {finding['confidence']:.2f}）",
                    "text": finding["text"],
                    "evidence": finding.get("evidence", ""),
                    "source_node": finding.get("source_node", ""),
                }
            )
        if analysis.get("nodes_failed"):
            sections.append(
                {
                    "title": "失败节点",
                    "text": "、".join(analysis["nodes_failed"]),
                }
            )
        return ScientificReport(
            title=title,
            sections=sections,
            metadata={"language": analysis.get("language", "zh")},
        )


def reason(result: Any, language: str = "zh") -> Dict[str, Any]:
    """Shorthand for :meth:`Reasoner.reason`."""
    return Reasoner(language).reason(result)
