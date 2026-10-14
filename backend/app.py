"""Chem ML Platform v0.7.1 -- API factory.

The backend exposes the node registry, the workflow engine, the AI runtime, the
scientific foundation models, the data catalog and the simulation queue over
REST and WebSocket.  It is intentionally thin: every scientific computation
happens in the modules themselves, the API only marshals data and streams
events.

Security (v0.7.1, spec task D): all ``/api/*`` calls pass through
:class:`backend.security.AuthMiddleware`, which enforces a local session token
with per-route permission categories, and CORS is restricted to an explicit
allowlist -- never ``*``.

Layout
------
``backend/app.py``               this file (application factory + middleware)
``backend/security.py``          session token, permissions, audit log
``backend/routers/nodes.py``     node catalogue & introspection
``backend/routers/workflows.py`` workflow CRUD, validation and execution
``backend/routers/runs.py``      run history and artefact download
``backend/routers/ws.py``        WebSocket event stream for live execution
``backend/routers/ai.py``        AI providers & cloud/local switching
``backend/routers/agent.py``     agent tasks (state-machine driven)
``backend/routers/data.py``      scientific data catalog
``backend/routers/simulations.py`` simulation back-ends & job queue
``backend/routers/foundation.py`` scientific foundation models
``backend/routers/storage.py``   secure upload / workspace browsing
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

#: Repository root, so that ``nodes``, ``workflow_engine`` and friends resolve
#: regardless of the working directory the server was started from.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.security import AuthMiddleware, load_security_config  # noqa: E402

#: Single version source of truth (spec task P0-04) -- never hard-code it here.
from chemml_version import VERSION  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Discover every node before the first request is served."""
    from nodes.loader import get_registry

    registry = get_registry()
    app.state.registry = registry
    app.state.ready = True
    yield
    app.state.ready = False


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    security = load_security_config()

    # Release builds must not expose interactive API documentation: it is a
    # debugging surface, and a packaged desktop app has no reason to serve it
    # (spec P1-02 "正式模式不会默认开放调试端点").
    expose_debug = not security.is_release

    app = FastAPI(
        title="Chem ML Platform API",
        description=(
            "Node-based scientific workflow platform: scientific nodes, DAG "
            "execution engine, unified scientific foundation models, cloud / "
            "local AI switching, a scientific data catalog, quantum chemistry / "
            "MD / materials simulation, secure storage, provenance and a "
            "ComfyUI-like graph editor."
        ),
        version=VERSION,
        lifespan=lifespan,
        docs_url="/api/docs" if expose_debug else None,
        redoc_url="/api/redoc" if expose_debug else None,
        openapi_url="/api/openapi.json" if expose_debug else None,
    )
    app.state.security = security

    # Explicit CORS allowlist (P1-03) -- no wildcard, no credentials, minimal
    # methods/headers.  The desktop renderer is served same-origin so it needs
    # no CORS entry at all.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=security.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-ChemML-Token", "Authorization"],
    )

    from backend.routers import (
        ai, agent, data, foundation, nodes, runs, simulations, storage, workflows, ws,
    )

    app.include_router(nodes.router, prefix="/api")
    app.include_router(workflows.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(ws.router, prefix="/api")
    app.include_router(ai.router, prefix="/api")
    app.include_router(agent.router, prefix="/api")
    app.include_router(data.router, prefix="/api")
    app.include_router(simulations.router, prefix="/api")
    app.include_router(foundation.router, prefix="/api")
    app.include_router(storage.router, prefix="/api")

    @app.get("/api/health", tags=["meta"])
    async def health() -> dict:
        """Liveness probe: reports the number of registered node types."""
        from nodes.loader import get_registry

        return {
            "status": "ok",
            "version": VERSION,
            "nodes": len(get_registry()),
        }

    @app.get("/api/security/status", tags=["meta"])
    async def security_status() -> dict:
        """Honest, secret-free report of the active security posture."""
        return security.status()

    @app.get("/api/meta", tags=["meta"])
    async def meta() -> dict:
        """Frontend bootstrap payload: categories, node specs and runtime state."""
        from nodes import node_categories, node_specs

        return {
            "name": "Chem ML Platform",
            "version": VERSION,
            "categories": node_categories(),
            "nodes": node_specs(),
            "security": security.status(),
        }

    # Auth middleware is added *after* the routers so FastAPI's resolution order
    # keeps it outermost; the pure-ASGI implementation never consumes the body.
    app.add_middleware(AuthMiddleware, config=security)

    # Serve the pre-built React editor when it is present.  ``frontend/dist`` is
    # the single source of truth; ``static/`` is only a generated junction that
    # ``start-platform.bat`` / the Docker build create for deployment, kept as a
    # fallback for older layouts.  Mounted last so every ``/api/*`` route wins;
    # absent locally, where the Vite dev server serves the UI.
    from fastapi.staticfiles import StaticFiles

    for candidate in (ROOT / "frontend" / "dist", ROOT / "static"):
        if (candidate / "index.html").is_file():
            app.mount("/", StaticFiles(directory=str(candidate), html=True), name="frontend")
            break

    return app


app = create_app()
