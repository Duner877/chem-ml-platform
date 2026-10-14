"""General purpose helpers shared by the Chem ML Platform packages.

The helpers are dependency-light on purpose: only the standard library and
NumPy are required so that they can be imported from the workflow engine, the
node implementations, the SDK and the test-suite without bootstrapping the
whole stack.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

import numpy as np

# Absolute path of the repository root (the folder that contains
# ``backend``, ``nodes``, ``workflow_engine`` ...).
ROOT: Path = Path(__file__).resolve().parents[1]

# Where runtime artefacts (figures, reports, cached node results) are written.
OUTPUT_DIR: Path = ROOT / "output"


def now_iso() -> str:
    """Return the current UTC timestamp as an ISO-8601 string."""
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="milliseconds")


def ensure_dir(path: str | Path) -> Path:
    """Create ``path`` (including parents) if needed and return it."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def json_safe(obj: Any) -> Any:
    """Recursively convert ``obj`` into something ``json.dumps`` accepts."""
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (int,)):
        return int(obj)
    if isinstance(obj, (float,)):
        value = float(obj)
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        value = float(obj)
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(obj, (np.ndarray,)):
        return json_safe(obj.tolist())
    if isinstance(obj, dict):
        return {str(k): json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [json_safe(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (_dt.datetime, _dt.date)):
        return obj.isoformat()
    if hasattr(obj, "model_dump"):  # pydantic v2
        return json_safe(obj.model_dump())
    if hasattr(obj, "to_dict"):
        return json_safe(obj.to_dict())
    return str(obj)


def stable_hash(obj: Any, length: int = 16) -> str:
    """Deterministic hash of an arbitrary (JSON-safe) object."""
    payload = json.dumps(json_safe(obj), sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:length]


def new_id(prefix: str = "") -> str:
    """Short random identifier, optionally prefixed."""
    import uuid

    return f"{prefix}{uuid.uuid4().hex[:8]}"


def to_array(values: Iterable[float] | np.ndarray | None) -> np.ndarray:
    """Convert ``values`` to a 1-D float array (empty array when ``None``)."""
    if values is None:
        return np.zeros(0, dtype=float)
    if isinstance(values, np.ndarray):
        return np.asarray(values, dtype=float).ravel()
    return np.asarray(list(values), dtype=float).ravel()


def as_list(value: Any) -> list:
    """Wrap scalars into a list, leave ``None`` as an empty list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def safe_filename(text: str, default: str = "file") -> str:
    """Sanitise ``text`` so it can be used as a file name."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(text)).strip("_")
    return cleaned or default


def pretty_number(value: float, digits: int = 4) -> str:
    """Format a float without trailing noise (``1.0`` -> ``1``)."""
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(number) >= 1e5 or (abs(number) < 1e-4 and number != 0):
        return f"{number:.{digits}e}"
    return f"{round(number, digits):g}"


def chunk(items: list, size: int) -> Iterable[list]:
    """Split ``items`` into consecutive chunks of at most ``size``."""
    for i in range(0, len(items), max(1, size)):
        yield items[i : i + size]


def linear_resample(
    x: np.ndarray, y: np.ndarray, step: float | None = None, points: int | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Resample ``(x, y)`` onto a uniform grid using linear interpolation."""
    x = to_array(x)
    y = to_array(y)
    if x.size == 0 or y.size == 0:
        return x, y
    if x.size == 1:
        return x, y
    order = np.argsort(x)
    x, y = x[order], y[order]
    if step is None:
        if points is None:
            points = x.size
        grid = np.linspace(float(x.min()), float(x.max()), int(points))
    else:
        grid = np.arange(float(x.min()), float(x.max()) + step, float(step))
    return grid, np.interp(grid, x, y)
