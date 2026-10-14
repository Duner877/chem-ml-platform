"""Agent memory -- persistent scientific working memory.

Four layers, one JSON document::

    from memory import get_memory

    mem = get_memory()
    mem.set_preference("language", "zh")
    mem.start_experiment("请分析这个未知化合物，我有 LC-MS 和 NMR 数据")
    mem.record_step("plan", nodes=8)
    mem.record_finding("候选：咖啡因（置信度 0.91）", confidence=0.91)
    mem.end_experiment("completed")
    mem.save()

See :mod:`memory.store` for the full API.
"""

from __future__ import annotations

from memory.store import DEFAULT_PATH, MemoryStore, get_memory, memory

try:  # single source of truth (spec P0-04)
    from chemml_version import VERSION as __version__
except ImportError:  # pragma: no cover - package-standalone fallback
    __version__ = "0.7.2"

__all__ = [
    "MemoryStore",
    "get_memory",
    "memory",
    "DEFAULT_PATH",
    "__version__",
]
