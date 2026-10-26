"""AI / 机器学习节点分组。

大语言模型、视觉模型、性质预测与模型训练。

本目录是一个**自包含的节点包**：把 ``.py`` 文件放进来即可被自动发现，
不需要改注册表或加载器。新增节点时请在本文件重新导出它的类名，
让 ``from custom_nodes.ai_ml import <Node>`` 这种写法保持可用。
"""
from __future__ import annotations

from custom_nodes.ai_ml.llm import (
    LLMNode,
)
from custom_nodes.ai_ml.prediction import (
    TrainModelNode,
    PropertyPredictionNode,
    SimilaritySearchNode,
)
from custom_nodes.ai_ml.vision import (
    VisionNode,
)

__all__ = [
    "LLMNode",
    "TrainModelNode",
    "PropertyPredictionNode",
    "SimilaritySearchNode",
    "VisionNode",
]
