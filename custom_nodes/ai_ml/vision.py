"""Vision models for microscopy, imaging and spectral maps.

Four back-ends are exposed through a single node:

``vit``
    Patch embedding + single head self-attention classification head.
``clip``
    Image / text contrastive scoring of user supplied candidate labels.
``sam``
    Otsu thresholding + connected component segmentation (mask output).
``dino``
    Self-distillation style embedding with PCA visualisation.

All of them are implemented with NumPy only so the node runs anywhere.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from workflow_engine.errors import NodeInputError
from workflow_engine.node_base import ParameterSpec, ScientificNode
from workflow_engine.objects import Image, Spectrum, Table, Text
from workflow_engine.ports import Port
from workflow_engine.registry import register_node

from custom_nodes._shared._helpers import _seed_vector, _unit, collect, find_image

__all__ = ["VisionNode", "VISION_MODELS", "segment_otsu", "connected_components"]


VISION_MODELS = ["vit", "clip", "sam", "dino"]

#: Generic label space used by the ViT head when the user gives no labels.
DEFAULT_LABELS = [
    "crystalline",
    "amorphous",
    "porous",
    "fibrous",
    "particulate",
    "layered",
]


# --------------------------------------------------------------------------- #
# Vision primitives
# --------------------------------------------------------------------------- #
def _as_array(image: Any) -> np.ndarray:
    """Return the 2-D array of an :class:`Image` (or any array-like)."""
    if isinstance(image, Image):
        return image.array()
    return np.asarray(image, dtype=float)


def _patch_embeddings(array: np.ndarray, patch: int) -> np.ndarray:
    """Split ``array`` into ``patch × patch`` blocks and return their statistics."""
    height, width = array.shape
    rows = max(1, height // patch)
    cols = max(1, width // patch)
    blocks: List[np.ndarray] = []
    for row in range(rows):
        for col in range(cols):
            block = array[row * patch : (row + 1) * patch, col * patch : (col + 1) * patch]
            if block.size == 0:
                continue
            blocks.append(
                np.array(
                    [
                        float(np.mean(block)),
                        float(np.std(block)),
                        float(np.max(block) - np.min(block)),
                        float(np.median(block)),
                    ]
                )
            )
    return np.vstack(blocks) if blocks else np.zeros((1, 4))


def _self_attention(tokens: np.ndarray, seed: int) -> Tuple[np.ndarray, np.ndarray]:
    """One deterministic self-attention layer (no learned weights)."""
    rng = np.random.default_rng(seed)
    dimension = tokens.shape[1]
    query = tokens @ rng.normal(scale=1.0 / math.sqrt(dimension), size=(dimension, dimension))
    key = tokens @ rng.normal(scale=1.0 / math.sqrt(dimension), size=(dimension, dimension))
    value = tokens @ rng.normal(scale=1.0 / math.sqrt(dimension), size=(dimension, dimension))
    scores = query @ key.T / math.sqrt(dimension)
    scores = scores - np.max(scores, axis=1, keepdims=True)
    weights = np.exp(scores)
    weights = weights / np.maximum(np.sum(weights, axis=1, keepdims=True), 1e-12)
    return weights @ value, weights


def segment_otsu(array: np.ndarray, bins: int = 256) -> float:
    """Otsu's between-class variance maximising threshold."""
    values = np.asarray(array, dtype=float).ravel()
    if values.size == 0:
        return 0.0
    low, high = float(np.min(values)), float(np.max(values))
    if high - low < 1e-12:
        return low
    histogram, edges = np.histogram(values, bins=bins, range=(low, high))
    centres = 0.5 * (edges[:-1] + edges[1:])
    total = float(np.sum(histogram))
    if total <= 0:
        return low

    weight_background = np.cumsum(histogram).astype(float)
    weight_foreground = total - weight_background
    mean_background = np.cumsum(histogram * centres) / np.maximum(weight_background, 1e-12)
    mean_foreground = (
        np.cumsum((histogram * centres)[::-1])[::-1] / np.maximum(weight_foreground, 1e-12)
    )
    variance = (weight_background / total) * (weight_foreground / total) * (
        mean_background - mean_foreground
    ) ** 2
    index = int(np.argmax(variance))
    return float(centres[index])


def connected_components(mask: np.ndarray) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Label the ``True`` regions of ``mask`` (8-connectivity, iterative BFS).

    Returns ``(labels, regions)`` where ``labels`` is an ``int`` array (``-1``
    for background) and ``regions`` one statistics record per component.
    """
    labels = np.full(mask.shape, -1, dtype=int)
    regions: List[Dict[str, Any]] = []
    current = 0
    height, width = mask.shape
    for row in range(height):
        for col in range(width):
            if not mask[row, col] or labels[row, col] != -1:
                continue
            queue = deque([(row, col)])
            labels[row, col] = current
            pixels: List[Tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                pixels.append((y, x))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if dy == 0 and dx == 0:
                            continue
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < height and 0 <= nx < width:
                            if mask[ny, nx] and labels[ny, nx] == -1:
                                labels[ny, nx] = current
                                queue.append((ny, nx))
            ys = [p[0] for p in pixels]
            xs = [p[1] for p in pixels]
            regions.append(
                {
                    "label": current,
                    "area_px": len(pixels),
                    "centroid_y": round(float(np.mean(ys)), 3),
                    "centroid_x": round(float(np.mean(xs)), 3),
                    "bbox_height": int(max(ys) - min(ys) + 1),
                    "bbox_width": int(max(xs) - min(xs) + 1),
                }
            )
            current += 1
    return labels, regions


# --------------------------------------------------------------------------- #
# Node
# --------------------------------------------------------------------------- #
@register_node
class VisionNode(ScientificNode):
    """Run a vision model on a micrograph or a chemical map."""

    name = "Vision Model"
    category = "AI/Vision"
    description = "对显微图像 / 化学成像图运行 ViT / CLIP / SAM / DINO 风格的视觉模型。"
    tags = ["ai", "vision", "vit", "clip", "sam", "dino"]
    aliases = ["Vision", "ViT", "CLIP", "SAM", "DINO"]
    icon = "VI"

    input_ports = [Port("image", "Any", "输入图像（无则生成示例图）", optional=True, multi=True)]
    output_ports = [
        Port("image", "Image", "输出图像 / 分割掩膜"),
        Port("table", "Table", "模型输出"),
        Port("text", "Text", "摘要"),
    ]

    parameters = [
        ParameterSpec(
            "model",
            "enum",
            "vit",
            "视觉模型",
            options=VISION_MODELS,
        ),
        ParameterSpec(
            "labels",
            "text",
            "crystalline,amorphous,porous",
            "候选标签（CLIP 用；每行或逗号分隔）",
        ),
        ParameterSpec("patch", "integer", 8, "ViT patch 尺寸", min=2, max=64, advanced=True),
        ParameterSpec("seed", "integer", 20240521, "随机种子", advanced=True),
    ]

    def execute(self, inputs: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        model = str(self.get_param("model", "vit")).lower()
        image = find_image(inputs.get("image"))
        if image is None:
            image = self._sample_image(model)

        array = _as_array(image)
        seed = int(self.get_param("seed", 20240521) or 20240521)

        if model == "clip":
            rows, output = self._run_clip(array)
        elif model == "sam":
            rows, output = self._run_sam(array)
        elif model == "dino":
            rows, output = self._run_dino(array, seed)
        else:
            rows, output = self._run_vit(array, seed, int(self.get_param("patch", 8) or 8))

        result_image = Image.from_array(
            output,
            pixel_size=image.pixel_size,
            pixel_unit=image.pixel_unit,
            name=f"{image.name or 'image'} ({model})",
            cmap=image.cmap,
            metadata={"model": model, "source": image.name},
        )

        table = Table(name=f"{model} output", columns=["field", "value"], rows=rows)
        summary = f"{model.upper()} on {int(array.shape[1])}×{int(array.shape[0])} px image, {len(rows)} output field(s)"
        self.log(summary)
        return {
            "image": result_image,
            "table": table,
            "text": Text(name=model, text=summary),
        }

    # -- back-ends ----------------------------------------------------------- #
    def _sample_image(self, model: str) -> Image:
        """Build a deterministic synthetic image used when nothing is connected."""
        rng = np.random.default_rng(7)
        grid = np.linspace(0.0, 1.0, 64)
        x, y = np.meshgrid(grid, grid)
        blobs = np.zeros_like(x)
        for index in range(3):
            cx = 0.25 + 0.25 * index
            cy = 0.35 + 0.2 * index
            blobs += np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / 0.01)
        noise = rng.normal(0.0, 0.03, x.shape)
        return Image.from_array(
            blobs + noise, pixel_size=1.0, pixel_unit="px", name=f"synthetic {model} image"
        )

    def _run_clip(self, array: np.ndarray) -> Tuple[List[List[Any]], np.ndarray]:
        """Score candidate text labels against image level features."""
        labels = _split_labels(str(self.get_param("labels", "") or "")) or list(DEFAULT_LABELS)
        image_embedding = _image_embedding(array, int(self.get_param("seed", 20240521) or 20240521))
        rows: List[List[Any]] = []
        scores: List[float] = []
        for label in labels:
            text_embedding = _unit(
                _seed_vector(label, image_embedding.shape[0], int(self.get_param("seed", 20240521) or 20240521))
            )
            score = float(np.dot(image_embedding, text_embedding))
            scores.append(score)
            rows.append([f"score::{label}", round(score, 6)])
        best_index = int(np.argmax(scores))
        rows.append(["top_label", labels[best_index]])
        rows.append(["top_score", round(float(scores[best_index]), 6)])
        return rows, _normalise(array)

    def _run_sam(self, array: np.ndarray) -> Tuple[List[List[Any]], np.ndarray]:
        """Threshold + connected components -> integer mask image."""
        threshold = segment_otsu(array)
        mask = array > threshold
        labels, regions = connected_components(mask)
        rows: List[List[Any]] = [
            ["threshold", round(float(threshold), 6)],
            ["regions", len(regions)],
        ]
        for region in regions[:20]:
            rows.append(
                [
                    f"region_{region['label']}",
                    f"area={region['area_px']}px, bbox={region['bbox_width']}x{region['bbox_height']}, "
                    f"centroid=({region['centroid_x']}, {region['centroid_y']})",
                ]
            )
        area_px = float(array.shape[0] * array.shape[1]) or 1.0
        coverage = float(np.sum(mask)) / area_px * 100.0
        rows.append(["coverage_pct", round(coverage, 3)])
        output = np.where(mask, array, 0.0)
        return rows, output

    def _run_dino(self, array: np.ndarray, seed: int) -> Tuple[List[List[Any]], np.ndarray]:
        """Self-distillation style patch embedding with PCA contrast image."""
        patch = max(2, int(self.get_param("patch", 8) or 8))
        tokens = _patch_embeddings(array, patch)
        if tokens.shape[0] < 2:
            return [["embedding_dim", 4]], _normalise(array)

        centred = tokens - tokens.mean(axis=0, keepdims=True)
        covariance = np.cov(centred, rowvar=False)
        values, vectors = np.linalg.eigh(covariance)
        order = np.argsort(values)[::-1]
        projection = centred @ vectors[:, order[:1]]
        grid_size = max(1, int(round(math.sqrt(tokens.shape[0]))))
        image = np.full((max(1, array.shape[0]), max(1, array.shape[1])), float(np.mean(projection)))
        height = min(image.shape[0], grid_size * patch)
        width = min(image.shape[1], grid_size * patch)
        surface = projection[: grid_size * grid_size].reshape(grid_size, grid_size)
        zoomed = np.kron(surface, np.ones((patch, patch)))[:height, :width]
        image[:height, :width] = zoomed
        rows = [
            ["tokens", int(tokens.shape[0])],
            ["embedding_dim", int(tokens.shape[1])],
            ["pca_variance_ratio", round(float(values[order[0]] / (np.sum(values) + 1e-12)), 6)],
        ]
        return rows, image

    def _run_vit(
        self, array: np.ndarray, seed: int, patch: int
    ) -> Tuple[List[List[Any]], np.ndarray]:
        """Patchify, attend and classify with the default label space."""
        tokens = _patch_embeddings(array, patch)
        attended, _weights = _self_attention(tokens, seed)
        pooled = attended.mean(axis=0)

        labels = _split_labels(str(self.get_param("labels", "") or "")) or list(DEFAULT_LABELS)
        scores = []
        for index, label in enumerate(labels):
            direction = _unit(_seed_vector(label, pooled.shape[0], seed))
            scores.append(float(np.dot(_unit(pooled), direction)))
        total = sum(math.exp(value) for value in scores) or 1.0
        probabilities = [math.exp(value) / total for value in scores]
        ranked = sorted(zip(labels, probabilities), key=lambda item: -item[1])
        rows = [["prediction", ranked[0][0]], ["probability", round(float(ranked[0][1]), 6)]]
        for label, probability in ranked[:10]:
            rows.append([f"p::{label}", round(float(probability), 6)])
        return rows, _normalise(array)


def _split_labels(raw: str) -> List[str]:
    """Split a label block into a clean list of labels."""
    import re

    tokens = re.split(r"[\n,;]+", raw)
    return [token.strip() for token in tokens if token.strip()]


def _image_embedding(array: np.ndarray, seed: int) -> np.ndarray:
    """Global image level feature used by the CLIP back-end."""
    tokens = _patch_embeddings(array, max(2, array.shape[0] // 8))
    pooled = tokens.mean(axis=0)
    return _unit(pooled)


def _normalise(array: np.ndarray) -> np.ndarray:
    """Scale an array into ``[0, 1]`` (constant images map to zeros)."""
    values = np.asarray(array, dtype=float)
    low, high = float(np.min(values)), float(np.max(values))
    if high - low < 1e-12:
        return np.zeros_like(values)
    return (values - low) / (high - low)
