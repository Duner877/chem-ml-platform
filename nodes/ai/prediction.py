"""Classical machine learning nodes: training and property prediction."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from models.descriptors import QED, compute_descriptors, lipinski_violations
from models.fingerprints import morgan_bits, smiles_similarity, tanimoto
from models.mpnn import HAS_TORCH, MPNNConfig, create_model, evaluate_model, train_model
from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Molecule, ScientificObject, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from nodes._helpers import build_molecule, collect, first_of, records_to_table

__all__ = ["TrainModelNode", "PropertyPredictionNode", "SimilaritySearchNode", "HAS_TORCH"]


def _column(table: Table, *candidates: str) -> Optional[str]:
    """Return the first column of ``table`` matching one of ``candidates``."""
    lowered = {str(name).strip().lower(): str(name) for name in table.columns}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


@register_node
class TrainModelNode(ScientificNode):
    """Train a molecular property model from a table."""

    name = "Train Model"
    category = "AI/ML"
    description = "由含 SMILES 与目标列的表格训练分子性质预测模型（PyTorch MPNN 或 NumPy 岭回归）。"
    tags = ["ai", "ml", "training", "mpnn", "regression"]
    #: v0.7.1 task F/H: training shuffles and initialises weights randomly, so
    #: bit-identical repeat runs are not promised (seed + environment recorded).
    deterministic = False
    aliases = ["TrainModel"]
    icon = "TM"

    input_ports = [Port("table", "Table", "训练数据（含 SMILES 与目标列）")]
    output_ports = [
        Port("text", "Text", "训练报告"),
        Port("table", "Table", "评估指标"),
    ]
    parameters = [
        ParameterSpec("smiles_column", "string", "smiles", "SMILES 列名"),
        ParameterSpec("target_column", "string", "target", "目标值列名"),
        ParameterSpec(
            "backend", "enum", "auto", "计算后端", options=["auto", "torch", "numpy"]
        ),
        ParameterSpec("epochs", "integer", 30, "训练轮数", min=1, max=5000),
        ParameterSpec("learning_rate", "number", 1e-3, "学习率", min=1e-6, max=1.0),
        ParameterSpec("hidden_dim", "integer", 128, "隐藏层维度", min=8, max=1024),
        ParameterSpec("test_fraction", "number", 0.2, "测试集比例", min=0.0, max=0.9, step=0.05),
        ParameterSpec("output_path", "string", "", "模型保存路径（可选）", advanced=True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        table = first_of(inputs.get("table"), Table, what="input 'table'")
        records = table.records()
        if not records:
            raise NodeInputError("TrainModelNode: training table is empty")

        smiles_column = _column(table, str(self.get_param("smiles_column", "smiles")))
        target_column = _column(table, str(self.get_param("target_column", "target")))
        if smiles_column is None or target_column is None:
            raise NodeInputError(
                "TrainModelNode: table must contain a SMILES column and a target column"
            )

        smiles_list: List[str] = []
        targets: List[float] = []
        for record in records:
            smiles = str(record.get(smiles_column, "") or "").strip()
            raw = record.get(target_column)
            if not smiles or raw is None:
                continue
            try:
                targets.append(float(raw))
            except (TypeError, ValueError):
                continue
            smiles_list.append(smiles)
        if len(smiles_list) < 2:
            raise NodeInputError("TrainModelNode: need at least 2 valid rows")

        fraction = float(self.get_param("test_fraction", 0.2) or 0.0)
        split = int(len(smiles_list) * (1.0 - min(0.9, max(0.0, fraction))))
        split = max(1, min(len(smiles_list) - 1, split))

        config = MPNNConfig(
            hidden=int(self.get_param("hidden_dim", 128) or 128),
            epochs=int(self.get_param("epochs", 30) or 30),
            learning_rate=float(self.get_param("learning_rate", 1e-3) or 1e-3),
            target=str(self.get_param("target_column", "target")),
        )
        model = train_model(
            smiles_list[:split],
            targets[:split],
            config=config,
            backend=str(self.get_param("backend", "auto")),
        )
        metrics = evaluate_model(model, smiles_list[split:], targets[split:])

        path = str(self.get_param("output_path", "") or "").strip()
        if path:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(model, "save"):
                model.save(str(target))
            else:
                target.write_text(json.dumps({"model": "torch-mpnn"}, indent=2), encoding="utf-8")
            metrics["model_path"] = str(target)

        rows = [[key, value] for key, value in metrics.items()]
        summary = (
            f"Trained on {split} samples, validated on {len(smiles_list) - split}: "
            f"R²={metrics.get('r2', float('nan')):.3f}, "
            f"RMSE={metrics.get('rmse', float('nan')):.4f}, "
            f"MAE={metrics.get('mae', float('nan')):.4f}"
        )
        self.log(summary)
        return {
            "text": Text(name="training report", text=summary, data=metrics),
            "table": Table(name="metrics", columns=["metric", "value"], rows=rows),
        }


@register_node
class PropertyPredictionNode(ScientificNode):
    """Predict physicochemical properties for a molecule."""

    name = "Property Prediction"
    category = "AI/ML"
    description = "预测 LogP / TPSA / 溶解度 / QED / Lipinski 等分子性质，可加载训练好的模型。"
    tags = ["ai", "ml", "prediction", "admet"]
    aliases = ["Predict"]
    icon = "PR"

    input_ports = [
        Port("molecule", "Molecule", "输入分子", optional=True, multi=True),
        Port("model", "Any", "可选：训练好的模型信息", optional=True, multi=True),
    ]
    output_ports = [
        Port("molecule", "Molecule", "带预测性质的分子"),
        Port("table", "Table", "预测结果表"),
        Port("text", "Text", "摘要"),
    ]
    parameters = [
        ParameterSpec("smiles", "string", "", "备用 SMILES"),
        ParameterSpec("model_path", "file", "", "可选：模型权重路径", advanced=True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        incoming = first_of(
            inputs.get("molecule"), Molecule, what="input 'molecule'", required=False
        )
        fallback = str(self.get_param("smiles", "") or "").strip()
        if incoming is not None and incoming.smiles:
            smiles, name = incoming.smiles, incoming.name
        elif fallback:
            smiles, name = fallback, fallback
        else:
            raise NodeInputError(
                "PropertyPredictionNode: connect a molecule or set the 'smiles' parameter"
        )

        descriptors = compute_descriptors(smiles)
        descriptors["LipinskiViolations"] = int(lipinski_violations(descriptors))
        descriptors["QED"] = float(QED(descriptors))
        descriptors["ESOL_logS"] = float(
            0.16
            - 0.63 * float(descriptors.get("MolLogP", 0.0))
            - 0.0062 * float(descriptors.get("MolWt", 0.0))
            + 0.066 * float(descriptors.get("NumRotatableBonds", 0.0))
        )

        molecule = build_molecule(
            smiles,
            name=name,
            confidence=incoming.confidence if incoming is not None else 0.0,
            properties=descriptors,
            source=self.node_type(),
        )
        table = Table(
            name="predicted properties",
            columns=["property", "value"],
            rows=[[key, round(float(value), 6)] for key, value in molecule.properties.items()],
        )
        summary = (
            f"{smiles}: MW {descriptors.get('MolWt', 0):.2f}, "
            f"logP {descriptors.get('MolLogP', 0):.2f}, "
            f"TPSA {descriptors.get('TPSA', 0):.2f}, "
            f"logS {descriptors['ESOL_logS']:.2f}, "
            f"QED {descriptors['QED']:.3f}"
        )
        self.log(summary)
        return {"molecule": molecule, "table": table, "text": Text(name="prediction", text=summary)}


@register_node
class SimilaritySearchNode(ScientificNode):
    """Rank a table of compounds by fingerprint similarity to a query."""

    name = "Similarity Search"
    category = "AI/ML"
    description = "以 Morgan 指纹相似度对候选库排序，用于虚拟筛选与结构确认。"
    tags = ["ai", "ml", "screening", "tanimoto"]
    aliases = ["Screen"]
    icon = "SC"

    input_ports = [
        Port("query", "Molecule", "查询分子", optional=True, multi=True),
        Port("library", "Table", "候选库（含 SMILES 列）", optional=True, multi=True),
    ]
    output_ports = [
        Port("table", "Table", "排序后的候选"),
        Port("text", "Text", "摘要"),
    ]
    parameters = [
        ParameterSpec("smiles", "string", "", "查询 SMILES（无上游时使用）"),
        ParameterSpec("smiles_column", "string", "smiles", "候选库 SMILES 列名"),
        ParameterSpec("top_k", "integer", 10, "返回前 K 个", min=1, max=1000),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        query_molecule = first_of(
            inputs.get("query"), Molecule, what="input 'query'", required=False
        )
        fallback = str(self.get_param("smiles", "") or "").strip()
        if query_molecule is not None and query_molecule.smiles:
            query = query_molecule.smiles
        elif fallback:
            query = fallback
        else:
            raise NodeInputError(
                "SimilaritySearchNode: connect a query molecule or set 'smiles'"
            )

        library = first_of(
            inputs.get("library"), Table, what="input 'library'", required=False
        )
        if library is None:
            raise NodeInputError("SimilaritySearchNode: connect a library table")

        column = _column(library, str(self.get_param("smiles_column", "smiles")))
        if column is None:
            raise NodeInputError("SimilaritySearchNode: library has no SMILES column")

        query_bits = morgan_bits(query, radius=2, n_bits=2048)
        scored = []
        for record in library.records():
            candidate = str(record.get(column, "") or "").strip()
            if not candidate:
                continue
            score = tanimoto(query_bits, morgan_bits(candidate, radius=2, n_bits=2048))
            enriched = dict(record)
            enriched["similarity"] = round(float(score), 6)
            scored.append(enriched)
        scored.sort(key=lambda item: -float(item.get("similarity", 0.0)))

        top_k = int(self.get_param("top_k", 10) or 10)
        ranked = scored[:top_k]
        table = records_to_table(ranked, name="similarity ranking")
        best = ranked[0] if ranked else {}
        summary = (
            f"Ranked {len(scored)} candidates against {query}; "
            f"top hit {best.get('name', best.get(column, 'n/a'))} "
            f"(Tanimoto {float(best.get('similarity', 0.0)):.4f})"
        )
        self.log(summary)
        return {"table": table, "text": Text(name="screening", text=summary)}
