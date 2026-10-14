"""Scientific foundation model endpoints: catalogue, embed, similarity, predict."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import foundation

router = APIRouter(prefix="/foundation", tags=["foundation"])


class EmbedPayload(BaseModel):
    items: List[str]
    model: str = ""
    modality: str = "molecule"
    dimension: Optional[int] = None


class SimilarityPayload(BaseModel):
    a: str
    b: str
    model: str = ""
    modality: str = "molecule"
    metric: str = "cosine"


class PredictPayload(BaseModel):
    items: List[str]
    property: str = "logp"
    model: str = ""


@router.get("/models")
async def models() -> Dict[str, Any]:
    """The foundation model catalogue with live availability."""
    rows = foundation.catalog()
    return {
        "count": len(rows),
        "modalities": foundation.MODALITIES,
        "models": rows,
    }


@router.post("/embed")
async def embed(payload: EmbedPayload) -> Dict[str, Any]:
    """Embed items into unit vectors."""
    try:
        vectors = foundation.embed(
            list(payload.items),
            model=payload.model,
            modality=payload.modality,
            dimension=payload.dimension,
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as 400
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {
        "count": len(vectors),
        "dimension": len(vectors[0]) if vectors else 0,
        "vectors": vectors,
    }


@router.post("/similarity")
async def similarity(payload: SimilarityPayload) -> Dict[str, Any]:
    """Similarity between two systems (0..1)."""
    try:
        value = foundation.similarity(
            payload.a,
            payload.b,
            model=payload.model,
            modality=payload.modality,
            metric=payload.metric,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {
        "a": payload.a,
        "b": payload.b,
        "metric": payload.metric,
        "similarity": round(float(value), 6),
    }


@router.post("/predict")
async def predict(payload: PredictPayload) -> Dict[str, Any]:
    """Predict a molecular property for every item."""
    try:
        rows = foundation.predict(
            list(payload.items), property=payload.property, model=payload.model
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=400, detail=f"{type(exc).__name__}: {exc}"
        ) from exc
    return {"count": len(rows), "property": payload.property, "rows": rows}
