"""Chemical foundation model nodes -- thin adapters over :mod:`foundation`.

v0.6 moved the actual encoder math into the unified
:mod:`foundation` runtime so a model has **one** implementation shared by the
workflow nodes, the Agent and the GUI.  Each node here is only the workflow
surface: ports, parameters and the ``Molecule`` / ``Table`` / ``Text``
packaging.  The heavy lifting (ChemBERTa / GROVER / Graphormer / Uni-Mol /
Morgan encoders, descriptor bundle) lives in :mod:`foundation.molecular`.

The official checkpoints are distributed separately (they are hundreds of MB);
when they are absent the encoder runs with deterministic, seeded projections so
that the topology of a workflow can be validated end to end.  This is reported
in ``Text.data["engine"]``.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from foundation.base import FoundationModel
from foundation.molecular import (
    ChemBERTaModel,
    GraphormerModel,
    GROVERModel,
    UniMolModel,
    descriptor_bundle,
)
from models.smiles import MolecularGraph, parse_smiles
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import build_molecule, first_of

__all__ = [
    "ChemicalFoundationModelNode",
    "UniMolNode",
    "ChemBERTaNode",
    "GROVERNode",
    "GraphormerNode",
]

#: Node parameters that are forwarded to the matching foundation model attribute.
_FORWARDED = ("n_grams", "n_steps", "n_layers", "with_3d")


class ChemicalFoundationModelNode(ScientificNode):
    """Shared interface of the chemical foundation model nodes."""

    category = "AI/Foundation Models"
    #: v0.7.1 task F: when the real pretrained weights are not installed the
    #: encoder uses deterministic, seeded projections.  That is a genuine
    #: internal approximation, so the node is graded ``experimental`` -- never
    #: presented as a validated pretrained model.
    capabilities = ["experimental"]
    implementation_status = "experimental"
    #: The :mod:`foundation.molecular` class this node wraps.
    model_cls: type[FoundationModel] = ChemBERTaModel
    model_name = "generic"
    citation = ""

    input_ports = [Port("molecule", "Molecule", "输入分子", optional=True, multi=True)]
    output_ports = [
        Port("molecule", "Molecule", "带嵌入向量的分子"),
        Port("table", "Table", "嵌入与预测性质"),
        Port("text", "Text", "模型摘要"),
    ]

    parameters = [
        ParameterSpec("smiles", "string", "", "备用 SMILES（无上游分子时使用）"),
        ParameterSpec("embedding_dim", "integer", 256, "嵌入维度", min=16, max=2048),
        ParameterSpec(
            "task",
            "enum",
            "embedding",
            "任务类型",
            options=["embedding", "property_prediction"],
        ),
        ParameterSpec("checkpoint", "file", "", "可选：本地权重文件路径", advanced=True),
        ParameterSpec("seed", "integer", 20240521, "随机种子", advanced=True),
    ]

    # -- model -------------------------------------------------------------- #
    def model(self) -> FoundationModel:
        """A fresh foundation model instance configured from the node params."""
        instance = self.model_cls()
        for name in _FORWARDED:
            value = self.get_param(name, None)
            if value is not None and hasattr(instance, name):
                setattr(instance, name, value)
        return instance

    def encode(self, graph: MolecularGraph, dimension: int, seed: int) -> np.ndarray:
        """Return a unit length embedding for ``graph``."""
        return self.model().encode(graph, dimension=dimension, seed=seed)

    # -- execution ----------------------------------------------------------- #
    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        incoming = first_of(
            inputs.get("molecule"), Molecule, what="input 'molecule'", required=False
        )
        fallback = str(self.get_param("smiles", "") or "").strip()
        if incoming is not None and incoming.smiles:
            smiles = incoming.smiles
            name = incoming.name
        elif fallback:
            smiles, name = fallback, fallback
        else:
            raise NodeInputError(
                f"{self.node_type()}: connect a molecule or set the 'smiles' parameter"
            )

        graph = parse_smiles(smiles)
        dimension = int(self.get_param("embedding_dim", 256) or 256)
        seed = int(self.get_param("seed", 20240521) or 20240521)
        raw = np.asarray(self.encode(graph, dimension, seed), dtype=float)
        norm = float(np.linalg.norm(raw))
        embedding = raw / norm if norm > 0 else raw

        descriptors = descriptor_bundle(smiles)

        molecule = build_molecule(
            smiles,
            name=name,
            confidence=incoming.confidence if incoming is not None else 0.0,
            properties=descriptors,
            embedding=[float(value) for value in embedding],
            source=self.model_name,
        )

        numeric = {
            str(key): float(value)
            for key, value in descriptors.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        table = Table(
            name=f"{self.model_name} output",
            columns=["field", "value"],
            rows=[
                ["model", self.model_name],
                ["smiles", smiles],
                ["formula", molecule.formula],
                ["embedding_dim", len(embedding)],
                ["embedding_norm", round(float(np.linalg.norm(embedding)), 6)],
            ]
            + [[key, round(value, 6)] for key, value in numeric.items()],
        )

        summary = (
            f"{self.model_name}: {molecule.formula} "
            f"(MW {descriptors.get('MolWt', 0):.2f}, QED {descriptors['QED']:.3f}, "
            f"logS {descriptors['ESOL_logS']:.2f}) embedded into {len(embedding)} dims"
        )
        self.log(summary)
        return {
            "molecule": molecule,
            "table": table,
            "text": Text(
                name=self.model_name,
                text=summary,
                data={"engine": "seeded-projection", "model": self.model_name},
            ),
        }


# --------------------------------------------------------------------------- #
# Concrete models
# --------------------------------------------------------------------------- #
@register_node
class ChemBERTaNode(ChemicalFoundationModelNode):
    """ChemBERTa style SMILES encoder."""

    name = "ChemBERTa"
    category = "AI/Foundation Models"
    description = "基于 SMILES 子词哈希的化学语言模型编码器，输出分子嵌入与性质预测。"
    tags = ["ai", "foundation model", "chemberta", "smiles"]
    aliases = ["ChemBERTa"]
    icon = "CB"

    model_cls = ChemBERTaModel
    model_name = "ChemBERTa"
    citation = "Chithrananda et al., ChemBERTa (2020)"

    parameters = ChemicalFoundationModelNode.parameters + [
        ParameterSpec("n_grams", "integer", 2, "字符 n-gram 长度", min=1, max=4, advanced=True),
    ]


@register_node
class GROVERNode(ChemicalFoundationModelNode):
    """GROVER style message passing network."""

    name = "GROVER"
    category = "AI/Foundation Models"
    description = "基于图消息传递网络的分子表征模型，输出原子级与分子级嵌入。"
    tags = ["ai", "foundation model", "grover", "gnn", "message passing"]
    aliases = ["GROVER"]
    icon = "GR"

    model_cls = GROVERModel
    model_name = "GROVER"
    citation = "Rong et al., GROVER (NeurIPS 2020)"

    parameters = ChemicalFoundationModelNode.parameters + [
        ParameterSpec("n_steps", "integer", 3, "消息传递步数", min=1, max=8, advanced=True),
    ]


@register_node
class GraphormerNode(ChemicalFoundationModelNode):
    """Graphormer style graph transformer."""

    name = "Graphormer"
    category = "AI/Foundation Models"
    description = "图 Transformer 编码器：带度数与最短路径结构编码的自注意力分子表征。"
    tags = ["ai", "foundation model", "graphormer", "transformer"]
    aliases = ["Graphormer"]
    icon = "GH"

    model_cls = GraphormerModel
    model_name = "Graphormer"
    citation = "Ying et al., Do Transformers Really Perform Bad for Graph Representation? (NeurIPS 2021)"

    parameters = ChemicalFoundationModelNode.parameters + [
        ParameterSpec("n_layers", "integer", 2, "Transformer 层数", min=1, max=6, advanced=True),
    ]


@register_node
class UniMolNode(ChemicalFoundationModelNode):
    """Uni-Mol style three dimensional molecular encoder."""

    name = "Uni-Mol"
    category = "AI/Foundation Models"
    description = "三维分子编码器：基于原子间距离矩阵的几何感知注意力表征。"
    tags = ["ai", "foundation model", "unimol", "3d"]
    aliases = ["UniMol"]
    icon = "UM"

    model_cls = UniMolModel
    model_name = "Uni-Mol"
    citation = "Zhou et al., Uni-Mol (2022)"

    parameters = ChemicalFoundationModelNode.parameters + [
        ParameterSpec("with_3d", "boolean", True, "生成三维构象"),
    ]
