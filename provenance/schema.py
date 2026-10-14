"""Provenance schema (v0.7 -- spec section 11)."""

from __future__ import annotations

import hashlib
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

__all__ = [
    "PROVENANCE_SCHEMA_VERSION",
    "EnvironmentInfo",
    "ProvenanceRecord",
    "collect_environment",
    "content_digest",
]

PROVENANCE_SCHEMA_VERSION = "0.7.0"


def content_digest(data: bytes) -> str:
    """SHA-256 content digest used for input/output references."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


@dataclass
class EnvironmentInfo:
    """Snapshot of the machine the run executed on."""

    python_version: str = ""
    os_name: str = ""
    platform_release: str = ""
    machine: str = ""
    torch_version: str = ""
    cuda_available: bool = False
    cuda_version: str = ""
    gpu_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def collect_environment() -> EnvironmentInfo:
    """Best-effort environment snapshot (never raises)."""
    info = EnvironmentInfo(
        python_version=sys.version.split(" ")[0],
        os_name=platform.system(),
        platform_release=platform.release(),
        machine=platform.machine(),
    )
    try:  # torch is optional; absence is recorded, not an error
        import torch  # type: ignore

        info.torch_version = torch.__version__
        info.cuda_available = bool(torch.cuda.is_available())
        if info.cuda_available:
            info.cuda_version = str(getattr(torch.version, "cuda", "") or "")
            info.gpu_names = [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ]
    except Exception:
        pass
    return info


@dataclass
class ProvenanceRecord:
    """Full provenance of a single node execution."""

    schema_version: str = PROVENANCE_SCHEMA_VERSION
    run_id: str = ""
    node_id: str = ""
    node_type: str = ""
    node_version: str = ""

    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0

    input_sources: Dict[str, str] = field(default_factory=dict)   # port -> descriptor
    input_digests: Dict[str, str] = field(default_factory=dict)   # port -> sha256
    params: Dict[str, Any] = field(default_factory=dict)
    provider: str = ""                                            # AI provider used
    model: str = ""                                               # model identifier
    external_software: Dict[str, str] = field(default_factory=dict)
    environment: Dict[str, Any] = field(default_factory=dict)

    random_seed: Optional[int] = None
    deterministic: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    cache_hit: bool = False
    cache_key: str = ""
    fallback_used: bool = False
    fallback_reason: str = ""
    device: str = ""                                              # cpu / cuda:0 / ""

    output_artifacts: List[Dict[str, str]] = field(default_factory=list)
    output_digests: Dict[str, str] = field(default_factory=dict)

    status: str = "completed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """One-line human readable summary for logs."""
        bits = [f"{self.node_type}#{self.node_id}", self.status]
        if self.cache_hit:
            bits.append("cache")
        if self.fallback_used:
            bits.append(f"fallback({self.fallback_reason})" if self.fallback_reason else "fallback")
        if self.device:
            bits.append(f"device={self.device}")
        if self.provider:
            bits.append(f"{self.provider}:{self.model}")
        if self.errors:
            bits.append(f"errors={len(self.errors)}")
        return " | ".join(bits)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")
