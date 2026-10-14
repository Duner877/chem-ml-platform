"""Example plugin: a melting-point note node.

This file demonstrates the complete node contract in the smallest useful
form: one optional input port, one output port, three parameters, a log line
and a graceful handling of a missing upstream connection.

Run it with::

    CHEMML_PLUGINS=examples/plugins python -m nodes.loader --query "Melting"
    CHEMML_PLUGINS=examples/plugins python scripts/smoke_nodes.py \\
        --filter MeltingPointNoteNode --traceback
"""

from __future__ import annotations

from typing import Any, Dict

from chemml_sdk import ParameterSpec, Port, ScientificNode, register_node
from workflow_engine.objects import Text


@register_node
class MeltingPointNoteNode(ScientificNode):
    """Format a melting-point record as a one-line text note.

    Scientific rationale
    --------------------
    Melting point is the cheapest purity / identity check in the synthetic
    lab.  Archiving it as a machine-readable line next to the spectrum makes
    the report self-contained, which is what this node produces.
    """

    name = "Melting Point Note"
    category = "Custom"
    description = "生成熔点记录备注（化合物 / 熔点 / 备注），用于报告归档。"
    version = "1.0.0"
    tags = ["demo", "thermal", "archive"]
    icon = "MP"

    input_ports = [
        Port("text", "Text", optional=True, description="可附加的上游说明"),
    ]
    output_ports = [
        Port("text", "Text", description="格式化后的备注"),
    ]
    parameters = [
        ParameterSpec("compound", "string", "", "化合物名称"),
        ParameterSpec("melting_point", "float", 0.0, "熔点 / °C", min=-273.15),
        ParameterSpec("note", "string", "", "额外备注（如 'lit. 234-236 °C'）"),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        compound = str(self.get_param("compound") or "unknown")
        melting_point = float(self.get_param("melting_point") or 0.0)
        note = str(self.get_param("note") or "")

        # ``text`` is an *optional* port: the key is simply absent when
        # nothing is connected, so read it with ``inputs.get``.
        upstream = inputs.get("text")
        if isinstance(upstream, list):  # multi=True ports arrive as lists
            upstream = upstream[0] if upstream else None
        suffix = ""
        if upstream is not None:
            suffix = f" | {getattr(upstream, 'text', upstream)}"

        self.log(f"formatting melting point record for {compound}")

        line = f"{compound}: mp = {melting_point:.1f} °C"
        if note:
            line += f" ({note})"
        line += suffix
        return {"text": Text(text=line, language="zh")}
