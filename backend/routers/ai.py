"""AI runtime endpoints: provider status, cloud/local switching and completion."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import ai_runtime
from ai_runtime.config import MODE_LABELS, MODES, get_config, update_config

router = APIRouter(prefix="/ai", tags=["ai"])


class AIConfigPayload(BaseModel):
    """Partial update of the AI configuration (only provided fields change)."""

    mode: Optional[str] = Field(default=None, description="auto | cloud | local | open_source | chemistry | offline")
    provider: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None
    api_keys: Optional[Dict[str, str]] = None
    base_urls: Optional[Dict[str, str]] = None


class CompletePayload(BaseModel):
    prompt: str
    family: str = "auto"
    provider: str = ""
    context: str = ""
    model: str = ""


def _mask(config: Any) -> Dict[str, Any]:
    """Config as JSON, with API keys reduced to a set/unset flag."""
    payload = config.to_dict()
    payload["api_keys_set"] = {
        key: bool(value) for key, value in (config.api_keys or {}).items()
    }
    payload["api_keys"] = {key: ("***" if value else "") for key, value in (config.api_keys or {}).items()}
    return payload


@router.get("/modes")
async def modes() -> List[Dict[str, Any]]:
    """The selectable AI modes with their labels."""
    return [
        {"mode": mode, "labels": MODE_LABELS.get(mode, {})} for mode in MODES
    ]


@router.get("/providers")
async def providers() -> Dict[str, Any]:
    """Mode, forced provider and per-provider availability."""
    return ai_runtime.state()


@router.get("/config")
async def read_config() -> Dict[str, Any]:
    """The current AI configuration (keys masked)."""
    return _mask(get_config())


@router.put("/config")
async def write_config(payload: AIConfigPayload) -> Dict[str, Any]:
    """Update and persist the AI configuration."""
    fields = payload.model_dump(exclude_none=True)
    if "mode" in fields and fields["mode"] not in MODES:
        raise HTTPException(status_code=422, detail=f"unknown mode {fields['mode']!r}")
    if "api_keys" in fields:
        # Never overwrite a stored key with the masked placeholder the GET
        # endpoint returns, nor with an empty string.
        cleaned = {
            key: value
            for key, value in dict(fields["api_keys"]).items()
            if str(value) not in {"***", ""}
        }
        if cleaned:
            merged = dict(get_config().api_keys)
            merged.update(cleaned)
            fields["api_keys"] = merged
        else:
            fields.pop("api_keys")
    config = update_config(**fields)
    return _mask(config)


@router.post("/complete")
async def complete(payload: CompletePayload) -> Dict[str, Any]:
    """Answer a prompt with the first available provider of the family."""
    try:
        result = ai_runtime.complete(
            payload.prompt,
            family=payload.family or "auto",
            provider=payload.provider,
            context=payload.context,
            **({"model": payload.model} if payload.model else {}),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as 503
        raise HTTPException(status_code=503, detail=f"{type(exc).__name__}: {exc}") from exc
    return result.to_dict()


@router.post("/test")
async def test_provider(payload: CompletePayload) -> Dict[str, Any]:
    """Ping the runtime with a trivial prompt (handy for the GUI 'Test' button)."""
    try:
        result = ai_runtime.complete(
            payload.prompt or "Reply with the single word: ok",
            family=payload.family or "auto",
            provider=payload.provider,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}", "engine": ""}
    return {
        "ok": True,
        "engine": result.engine,
        "family": result.family,
        "model": result.model,
        "latency_ms": result.latency_ms,
        "text": result.text[:400],
    }
