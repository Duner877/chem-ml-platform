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
    set_credential,
    test_credential,
)

router = APIRouter(prefix="/credentials", tags=["credentials"])


class CredentialPayload(BaseModel):
    provider: str = Field(description="Provider id, e.g. openai / deepseek / ollama")
    secret: str = Field(description="The API key or, for a local provider, the base URL")
    base_url: str = Field(default="", description="Optional endpoint override")


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
        return set_credential(payload.provider, payload.secret, payload.base_url)
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