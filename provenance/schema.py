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
    "key_dependency_versions",
    "platform_identity",
]

#: Bumped by v0.7.2 task P1-06: the schema now records the workflow definition
#: digest, the platform identity, the key dependency versions, the *actual*
#: execution mode per node, and run-level resource usage.  A reader can tell
#: from this string which set of fields to expect.
PROVENANCE_SCHEMA_VERSION = "0.7.2"


def content_digest(data: bytes) -> str:
    """SHA-256 content digest used for input/output references."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


#: Distributions whose version materially affects numerical results.  A run
#: record that omits these cannot be reproduced on another machine, so they are
#: recorded explicitly rather than left to the reader to guess.
KEY_DISTRIBUTIONS = (
    "numpy",
    "scipy",
    "pandas",
    "scikit-learn",
    "pydantic",
    "fastapi",
    "torch",
    "rdkit",
    "networkx",
)


def key_dependency_versions() -> Dict[str, str]:
    """Installed versions of the numerics-critical dependencies.

    Absence is recorded as ``"absent"`` rather than omitted: "this machine did
    not have RDKit" is itself part of the experimental record.
    """
    import importlib.metadata as md

    out: Dict[str, str] = {}
    for name in KEY_DISTRIBUTIONS:
        try:
            out[name] = md.version(name)
        except md.PackageNotFoundError:
            out[name] = "absent"
        except Exception:  # noqa: BLE001 - metadata can be corrupt; never fail a run
            out[name] = "unknown"
    return out


def platform_identity() -> Dict[str, str]:
    """Version / codename / commit of the platform itself."""
    out = {"version": "", "codename": "", "commit": ""}
    try:
        import chemml_version  # type: ignore

        out["version"] = str(getattr(chemml_version, "__version__", "") or "")
        out["codename"] = str(getattr(chemml_version, "__codename__", "") or "")
        out["commit"] = str(chemml_version.git_commit(short=True) or "")
    except Exception:  # noqa: BLE001 - provenance must never break a run
        pass
    return out


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
    #: v0.7.2 (task P1-06): versions of the numerics-critical dependencies.
    key_dependencies: Dict[str, str] = field(default_factory=dict)
    #: v0.7.2 (task P1-06): platform version / codename / commit.
    platform: Dict[str, str] = field(default_factory=dict)

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
    except Exception:  # noqa: BLE001 - torch absent / CUDA broken is recorded, not raised
        # Must not touch ``torch`` here: when the import above fails the name
        # never binds, and referencing it raised UnboundLocalError, which
        # aborted every workflow run on machines without torch.
        pass
    info.key_dependencies = key_dependency_versions()
    info.platform = platform_identity()
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
    #: v0.7.2 (task P1-06): what *actually* ran, as opposed to what the node
    #: class declares.  ``external`` / ``internal_approximation`` /
    #: ``synthetic_demo`` -- see ``workflow_engine.node_base``.
    execution_mode: str = ""
    #: v0.7.3 (audit P0-4): the modes this node could have used, and which one
    #: it uses when nothing overrides it.  A node can legitimately run several
    #: ways -- an LLM node goes to the network with a key and to the internal
    #: engine without one -- so the registry cannot publish a single answer,
    #: and ``execution_mode`` above is only the declaration.
    supported_execution_modes: List[str] = field(default_factory=list)
    default_execution_mode: str = ""
    #: v0.7.3 (audit P0-4): the concrete engine or program that did the work
    #: in *this* run ("ORCA 5.0", "internal:eht", "openai:gpt-4o-mini").  The
    #: mode says which kind of computation ran; this says which one.  A report
    #: that shows only the mode can say "internal_approximation" without ever
    #: naming the approximation that produced the numbers.
    engine_name: str = ""
    engine_version: str = ""
    #: v0.7.2 (task P1-06): declared capability level of the node class.
    capability_status: str = ""
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
