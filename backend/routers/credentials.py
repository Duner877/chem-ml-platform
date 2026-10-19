"""Credential endpoints: the GUI's API-key entry point.

Mounted at ``/api/credentials``.  Deliberately separate from ``/api/ai/config``
because the two answer different questions: the config endpoint edits *behaviour*
(mode, provider, model, temperature) while this one manages *secrets*.

Nothing here ever returns a stored secret.  The listing carries a mask, a length
and a source; the write endpoints take the value and give back the same mask.
A GUI that cannot display a key is a GUI nobody trusts with one.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ai_runtime.credentials import (
    PROVIDERS,
    credential_backend,
    delete_credential,
    list_credentials,
    list_provider_models,
    set_credential,
    set_provider_model,
    test_credential,
)

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialPayload(BaseModel):
    provider: str = Field(description="Provider id, e.g. openai / deepseek / ollama")
    secret: str = Field(description="The API key or, for a local provider, the base URL")
    base_url: str = Field(default="", description="Optional endpoint override")
    model: str = Field(
        default="",
        description="Optional model id to remember for this provider; empty clears it",
    )


class ModelChoicePayload(BaseModel):
    model: str = Field(default="", description="Model id to use, or empty to fall back to the default")


@router.get("")
async def read_all() -> Dict[str, Any]:
    """Every provider's status, plus where a newly added key would be stored.

    The ``backend`` field is what lets the GUI state the storage choice out
    loud -- a user who believes their key is in the OS keyring should be told
    when it is in a plain file instead.
    """
    return list_credentials()


@router.get("/providers")
async def read_providers() -> Dict[str, Any]:
    """The catalogue alone, for rendering a picker before anything is stored."""
    return {
        "backend": credential_backend(),
        "providers": [
            {
                "id": spec.id,
                "labels": {"zh": spec.label_zh, "en": spec.label_en},
                "kind": spec.kind,
                "env_var": spec.primary_env,
                "docs_url": spec.docs_url,
                "default_base_url": spec.default_base_url,
                "notes": {"zh": spec.notes_zh, "en": spec.notes_en},
                # Lets the GUI explain *before* a key is entered which model the
                # connectivity check will ask for -- the difference between
                # "key is wrong" and "this endpoint does not serve that model"
                # is otherwise only discoverable by getting it wrong.
                "probe_model": spec.probe_model,
                # Whether this provider publishes a model catalogue, so the GUI
                # can offer the button without asking and getting an error.
                "models_path": spec.models_path,
                "has_catalogue": bool(spec.models_path),
            }
            for spec in PROVIDERS
        ],
    }


@router.post("")
async def create(payload: CredentialPayload) -> Dict[str, Any]:
    """Store a credential and push it into the environment.

    Pushing matters: the providers read ``os.environ``, so a credential that was
    only written to disk would show as configured while the runtime kept falling
    back to offline.
    """
    try:
        result = set_credential(payload.provider, payload.secret, payload.base_url)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload.model:
        # Saving a key and a model in one call is the natural GUI gesture: pick
        # the provider, paste the key, choose the id.  Failing here must not
        # undo the key, so the model's own error is reported separately.
        try:
            set_provider_model(payload.provider, payload.model)
        except (KeyError, ValueError) as exc:
            result["model_warning"] = str(exc)
        else:
            result["model"] = payload.model
    return result


@router.get("/{provider}/models")
async def read_models(provider: str) -> Dict[str, Any]:
    """Fetch the model catalogue this credential can address.

    The response is a *catalogue*, flagged as such (``catalogue_only``).  NVIDIA
    NIM lists 81 ids while a large share of them answer HTTP 410 on an actual
    completion, so presenting the list as "available models" would be a claim
    the provider does not support; the connectivity test is what establishes
    whether a given id works.

    Returns 200 with ``ok: false`` for the same reason ``/{provider}/test``
    does: "this key has no catalogue" is a displayable answer, not a transport
    failure.
    """
    try:
        return list_provider_models(provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{provider}/model")
async def choose_model(provider: str, payload: ModelChoicePayload) -> Dict[str, Any]:
    """Remember which model this provider should serve by default."""
    try:
        return set_provider_model(provider, payload.model)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{provider}")
async def remove(provider: str) -> Dict[str, Any]:
    """Forget a credential everywhere it could be held."""
    try:
        return delete_credential(provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{provider}/test")
async def probe(provider: str) -> Dict[str, Any]:
    """Try the credential against its provider.

    Returns 200 with ``ok: false`` for a rejected key: "your key is wrong" is an
    answer the GUI has to display, not a transport-level error.  Only an unknown
    provider is a 404.
    """
    try:
        return test_credential(provider)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc