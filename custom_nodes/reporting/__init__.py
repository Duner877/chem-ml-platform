"""报告与出图节点分组。

报告构建、汇总表、文档导出与产物图绘制。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.reporting import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.reporting.report import (
    ReportBuilderNode,
    SummaryTableNode,
    ReportExportNode,
    FigureExportNode,
)
from custom_nodes.reporting.report_agent import (
    ReportAgentNode,
)

__all__ = [
    "ReportBuilderNode",
    "SummaryTableNode",
    "ReportExportNode",
    "FigureExportNode",
    "ReportAgentNode",
]
