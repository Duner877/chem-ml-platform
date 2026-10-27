"""REST endpoints describing the node catalogue."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from nodes import node_categories, node_specs, load_nodes

router = APIRouter(prefix="/nodes", tags=["nodes"])


@router.get("", response_model=List[Dict[str, Any]])
async def list_nodes(category: str = "", query: str = "") -> List[Dict[str, Any]]:
    """Every registered node, optionally filtered by category / keyword."""
    load_nodes()
    specs = node_specs()
    if category:
        specs = [spec for spec in specs if spec["category"] == category]
    if query:
        needle = query.strip().lower()
        specs = [
            spec
            for spec in specs
            if needle in spec["name"].lower()
            or needle in spec["type"].lower()
            or needle in spec["description"].lower()
            or any(needle in tag.lower() for tag in spec["tags"])
        ]
    return specs


@router.get("/categories")
async def categories() -> List[Dict[str, Any]]:
    """Node catalogue grouped by category (drives the palette sidebar)."""
    load_nodes()
    return node_categories()


@router.get("/{node_type}", response_model=Dict[str, Any])
async def node_detail(node_type: str) -> Dict[str, Any]:
    """Full specification of a single node type."""
    load_nodes()
    for spec in node_specs():
        if spec["type"] == node_type:
            return spec
    raise HTTPException(status_code=404, detail=f"unknown node type {node_type!r}")


@router.get("/registry/full", response_model=Dict[str, Any])
async def registry_full() -> Dict[str, Any]:
    """Complete node registry (authors, versions, module, validation status).

    Powers the frontend Node Marketplace.  Returns the catalogue produced by
    ``python -m node_registry --write``; when that file is missing it falls back
    to the in-process node specifications.
    """
    from node_registry import load_registry

    try:
        return load_registry()
    except Exception:
        load_nodes()
        specs = node_specs()
        return {
            "package": "Chem ML Platform",
            "total_nodes": len(specs),
            "categories": sorted({spec["category"] for spec in specs}),
            "nodes": [
                {
                    "node_name": spec["name"],
                    "type": spec["type"],
                    "version": spec["version"],
                    "category": spec["category"],
                    "description": spec["description"],
                    "tags": spec["tags"],
                    "author": "Duner",
                    "module": "",
                    "inputs": [p["name"] for p in spec["inputs"]],
                    "outputs": [p["name"] for p in spec["outputs"]],
                }
                for spec in specs
            ],
        }
