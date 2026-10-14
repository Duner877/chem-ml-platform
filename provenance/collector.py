"""Provenance collector -- bridges the workflow engine to the schema.

The collector offers two integration levels:

* :func:`build_node_record` turns a completed :class:`NodeExecutionRecord`
  plus the node instance into a :class:`ProvenanceRecord` (used by tests and
  by the engine integration hook);
* :class:`ProvenanceCollector` is an engine event listener that accumulates
  records for a run and writes ``provenance.json`` when the run finishes.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import (
    EnvironmentInfo,
    ProvenanceRecord,
    collect_environment,
    content_digest,
    utc_now_iso,
)

__all__ = [
    "ProvenanceCollector",
    "build_node_record",
    "workflow_identity",
    "measure_resources",
    "apply_instance_facts",
]


def apply_instance_facts(record: ProvenanceRecord, instance: Any) -> None:
    """Copy the execution facts only a live node instance can know (task P1-06).

    Shared by the event-driven collector and by :func:`build_node_record` so the
    two can never disagree about a node's actual execution mode.
    """
    mode_fn = getattr(instance, "effective_execution_mode", None)
    if callable(mode_fn):
        try:
            mode, _note = mode_fn()
            record.execution_mode = str(mode or "")
        except Exception:  # noqa: BLE001 - diagnostics only
            record.execution_mode = str(getattr(instance, "execution_mode", "") or "")
    else:
        record.execution_mode = str(getattr(instance, "execution_mode", "") or "")
    record.capability_status = str(getattr(instance, "capability_status", "") or "")
    if not record.node_version:
        record.node_version = str(getattr(instance, "version", "") or "")
    record.deterministic = bool(getattr(instance, "deterministic", record.deterministic))
    if record.random_seed is None:
        record.random_seed = getattr(instance, "random_seed", None)


#: Fields excluded from a reproducibility digest, with the reason.
#:
#: Every :class:`~workflow_engine.objects.ScientificObject` carries a fresh
#: ``id`` (and often run-scoped paths/timestamps).  Digesting the raw
#: serialisation therefore *always* differs between two runs of the same
#: deterministic graph -- which would make the reproducibility check cry wolf on
#: every workflow and teach users to ignore it.  A reproducibility digest must
#: cover the scientific content, not the run's identity.
VOLATILE_DIGEST_KEYS = frozenset(
    {
        # run-scoped identity
        "id", "run_id", "node_id", "uuid", "oid",
        # wall-clock bookkeeping
        "created_at", "updated_at", "generated_at", "timestamp", "time",
        "started_at", "finished_at", "duration_ms", "duration_s",
        # where the run happened to be written
        "path", "paths", "file", "filename", "artifact_path", "provenance_path",
        "run_dir", "workdir", "cache_key",
    }
)


#: Shape of a platform-generated identifier, e.g. ``o_1a2b3c4d`` (object),
#: ``run_8ef77927``, ``rpt_0e3f8457``.  Matched against *values* rather than
#: key names on purpose: excluding every ``*_id`` would also throw away
#: scientifically meaningful identifiers such as a dataset or candidate id,
#: whereas a ``prefix_hex`` token is generated, not chosen.
GENERATED_ID_RE = re.compile(r"^[a-z]{1,6}_[0-9a-f]{6,}$")


def path_scrub_variants(path_like: Any) -> List[str]:
    """All spellings of a path that could appear inside recorded values.

    Windows APIs, JSON serialisers and user code disagree about separators, so a
    single literal is not enough: ``C:\\a\\b`` may be recorded as ``C:/a/b``.
    Longer forms are returned first so a full path is replaced before its
    prefix, which keeps the placeholder stable.
    """
    text = str(path_like or "")
    if not text:
        return []
    variants = {text, text.replace("\\", "/"), text.replace("/", "\\")}
    return sorted((v for v in variants if v), key=len, reverse=True)


def canonical_for_digest(value: Any, scrub: Any = ()) -> Any:
    """Recursively drop run-scoped identity, keeping scientific content.

    The transformations applied are deliberately narrow and inspectable:

    * keys in :data:`VOLATILE_DIGEST_KEYS` are removed at every level;
    * any string that matches :data:`GENERATED_ID_RE` is replaced, because such
      values (``run_id``, ``report_id``, object ids) are minted per run;
    * known run-scoped *literals* (the run id, the run directory) are replaced
      inside longer strings, because a report body legitimately quotes them;
    * lists keep their order, because order can be scientifically meaningful
      (a spectrum's bins, a ranked candidate list).
    """
    if isinstance(value, dict):
        return {
            key: canonical_for_digest(item, scrub)
            for key, item in value.items()
            if key not in VOLATILE_DIGEST_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [canonical_for_digest(item, scrub) for item in value]
    if isinstance(value, str):
        if GENERATED_ID_RE.match(value):
            return "<generated-id>"
        for term in scrub or ():
            if term:
                value = value.replace(term, "<run-scoped>")
        return value
    return value


def digest_value(value: Any, scrub: Any = ()) -> str:
    """Content digest of one node output, for the reproducibility record.

    Prefers the *canonical serialisation* of a scientific object over its
    ``repr``: two runs that produce the same molecule must digest the same even
    though the addresses (and generated ids) of the objects differ.  Byte values
    are hashed directly, which is what makes an output file verifiable.
    """
    if value is None:
        return ""

    def _dump(payload: Any) -> str:
        return content_digest(
            json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
        )

    if isinstance(value, (bytes, bytearray, memoryview)):
        return content_digest(bytes(value))
    for attr in ("model_dump", "to_dict", "dict"):
        fn = getattr(value, attr, None)
        if callable(fn):
            try:
                return _dump(canonical_for_digest(fn(), scrub))
            except Exception:  # noqa: BLE001 - fall through to the other forms
                break
    if isinstance(value, str):
        return content_digest(str(canonical_for_digest(value, scrub)).encode("utf-8"))
    if isinstance(value, (int, float, bool)):
        return content_digest(str(value).encode("utf-8"))
    if isinstance(value, (dict, list, tuple)):
        return _dump(canonical_for_digest(value, scrub))
    return content_digest(repr(value).encode("utf-8"))


def file_digest(path: Any) -> str:
    """SHA-256 of a file on disk, or ``""`` when it cannot be read."""
    try:
        target = Path(str(path))
        if not target.is_file():
            return ""
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"
    except OSError:
        return ""


def _peak_rss_bytes() -> tuple:
    """Peak resident memory of this process, or ``(None, reason)``.

    Only standard-library probes are used.  Where the host forbids the query
    (some hardened Windows sandboxes answer 0 from ``GetProcessMemoryInfo``),
    the reason is returned so the record states *why* the number is absent
    instead of silently omitting a field a reader would expect.
    """
    import os

    # Linux: the kernel exposes the high-water mark as plain text.
    try:
        with open("/proc/self/status", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) * 1024, ""
    except OSError:
        pass
    # POSIX (macOS / BSD): ru_maxrss, already in bytes on macOS.
    try:
        import resource  # type: ignore

        usage = resource.getrusage(resource.RUSAGE_SELF)
        factor = 1 if sys.platform == "darwin" else 1024
        return int(usage.ru_maxrss) * factor, ""
    except Exception:  # noqa: BLE001 - no resource module on Windows
        pass
    # Windows: PROCESS_MEMORY_COUNTERS via psapi / kernel32.
    try:
        import ctypes
        from ctypes import wintypes

        class _PMC(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetCurrentProcess()
        for lib in (kernel32, ctypes.windll.psapi):  # type: ignore[attr-defined]
            fn = getattr(lib, "K32GetProcessMemoryInfo", None) or getattr(
                lib, "GetProcessMemoryInfo", None
            )
            if fn is None:
                continue
            counters = _PMC()
            counters.cb = ctypes.sizeof(_PMC)
            if fn(handle, ctypes.byref(counters), counters.cb):
                return int(counters.PeakWorkingSetSize), ""
        return None, "os_query_blocked"
    except Exception as exc:  # noqa: BLE001
        return None, f"probe_failed: {type(exc).__name__}"


def measure_resources(
    started_at: str = "",
    wall_started: float = 0.0,
    cpu_started: float = 0.0,
) -> Dict[str, Any]:
    """Best-effort resource snapshot for a finished run (task P1-06).

    Wall-clock and process CPU time come from the standard library and are
    always available.  Peak memory depends on the host allowing the query; when
    it is not, ``peak_rss_bytes`` is ``null`` and ``peak_rss_note`` says why --
    an absent measurement is reported as absent, never estimated.
    """
    import os
    import time as _time

    out: Dict[str, Any] = {"started_at": started_at, "cpu_count": os.cpu_count()}
    if wall_started:
        out["wall_time_s"] = round(max(0.0, _time.perf_counter() - wall_started), 3)
    if cpu_started:
        out["cpu_time_s"] = round(max(0.0, _time.process_time() - cpu_started), 3)
    peak, note = _peak_rss_bytes()
    out["peak_rss_bytes"] = peak
    if note:
        out["peak_rss_note"] = note
    return out


def build_node_record(
    record: Any,
    node_instance: Any = None,
    environment: Optional[EnvironmentInfo] = None,
    run_id: str = "",
) -> ProvenanceRecord:
    """Create a :class:`ProvenanceRecord` from an engine execution record.

    ``record`` is a :class:`workflow_engine.engine.NodeExecutionRecord`;
    ``node_instance`` (optional) contributes node version, params, provider /
    model and fallback information when the node exposes them.
    """
    prov = ProvenanceRecord(
        run_id=run_id or "",
        node_id=getattr(record, "node_id", ""),
        node_type=getattr(record, "node_type", ""),
        started_at=getattr(record, "started_at", ""),
        finished_at=getattr(record, "finished_at", ""),
        duration_ms=float(getattr(record, "duration_ms", 0.0) or 0.0),
        cache_hit=bool(getattr(record, "cached", False)),
        status=getattr(record, "status", ""),
    )
    if getattr(record, "error", ""):
        prov.errors.append(str(record.error))
    prov.warnings.extend(
        line for line in getattr(record, "logs", []) if str(line).lower().startswith("[warn")
    )

    if node_instance is not None:
        prov.node_version = str(getattr(node_instance, "version", "") or "")
        prov.params = dict(getattr(node_instance, "params", {}) or {})
        prov.provider = str(getattr(node_instance, "last_provider", "") or "")
        prov.model = str(getattr(node_instance, "last_model", "") or "")
        prov.fallback_used = bool(getattr(node_instance, "fallback_used", False))
        prov.fallback_reason = str(getattr(node_instance, "fallback_reason", "") or "")
        prov.device = str(getattr(node_instance, "last_device", "") or "")
        prov.random_seed = getattr(node_instance, "random_seed", None)
        prov.deterministic = bool(getattr(node_instance, "deterministic", True))
        # v0.7.2 (task P1-06): record what actually ran, and the declared
        # capability level, so a report can never imply external software did
        # work that an internal approximation performed.
        apply_instance_facts(prov, node_instance)
        external = getattr(node_instance, "external_software", None)
        if isinstance(external, dict):
            prov.external_software = {str(k): str(v) for k, v in external.items()}

    env = environment or getattr(build_node_record, "_env_cache", None)
    if env is None:
        env = collect_environment()
        build_node_record._env_cache = env  # type: ignore[attr-defined]
    prov.environment = env.to_dict()
    return prov


def workflow_identity(workflow: Any) -> Dict[str, Any]:
    """Digest + shape of the workflow definition that produced this run.

    v0.7.2 (task P1-06) requirement: "工作流定义及版本".  The digest is taken
    over a *canonical* serialisation (sorted keys) so that reordering the JSON
    does not change the identity, while any change to a node parameter does.
    """
    if workflow is None:
        return {}
    raw: Any = workflow
    for attr in ("to_dict", "model_dump", "dict"):
        fn = getattr(workflow, attr, None)
        if callable(fn):
            try:
                raw = fn()
                break
            except Exception:  # noqa: BLE001
                pass
    try:
        canonical = json.dumps(raw, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return {}
    return {
        "name": str(getattr(workflow, "name", "") or ""),
        "description": str(getattr(workflow, "description", "") or ""),
        "schema_version": str(getattr(workflow, "schema_version", "") or ""),
        "definition_digest": content_digest(canonical.encode("utf-8")),
        "node_count": len(getattr(workflow, "nodes", []) or []),
        "edge_count": len(getattr(workflow, "edges", []) or []),
    }


class ProvenanceCollector:
    """Event-bus listener that records provenance for a whole run."""

    def __init__(
        self,
        run_id: str,
        environment: Optional[EnvironmentInfo] = None,
        workflow: Any = None,
        max_workers: Optional[int] = None,
    ):
        self.run_id = run_id
        self.environment = environment or collect_environment()
        self.records: Dict[str, ProvenanceRecord] = {}
        self.started_at = utc_now_iso()
        self.finished_at = ""
        self.run_status = "running"
        #: v0.7.2 (task P1-06): what was asked to run, and under what
        #: parallelism -- neither is derivable from the node records alone.
        self.workflow: Dict[str, Any] = workflow_identity(workflow)
        self.max_workers = max_workers
        self.resource_usage: Dict[str, Any] = {}
        #: v0.7.2 (task P1-06): node instances, keyed by node id.  The event bus
        #: carries ids and parameter snapshots only, so without this the record
        #: could not say whether a node actually ran as ``external`` or as an
        #: internal approximation.
        self._instances: Dict[str, Any] = {}
        # v0.7.2 (task P1-06): baselines for the resource snapshot.  Captured
        # here because this is the earliest point that belongs to the run.
        import time as _time

        self._wall_started = _time.perf_counter()
        self._cpu_started = _time.process_time()
        #: v0.7.2 (task P1-06): run-scoped literals normalised out of digests.
        #: The engine fills these with the run id and run directory once known.
        self.scrub_terms: List[str] = [run_id] if run_id else []

    def record_outputs(
        self, node_id: str, outputs: Any, artifact_paths: Any = None
    ) -> None:
        """Attach output digests and artefact references to a node record.

        v0.7.2 (task P1-06): "输出文件标识与哈希".  Before this the schema had
        the fields but nothing ever filled them, so ``output_digests`` was
        always ``{}`` -- evidence that looked present but proved nothing.
        """
        record = self.records.get(node_id)
        if record is None:
            return
        if isinstance(outputs, dict):
            for port, value in outputs.items():
                digest = digest_value(value, self.scrub_terms)
                if digest:
                    record.output_digests[str(port)] = digest
        for raw in artifact_paths or []:
            digest = file_digest(raw)
            record.output_artifacts.append(
                {"path": str(raw), "digest": digest, "exists": bool(digest)}
            )

    def resource_snapshot(self) -> Dict[str, Any]:
        """Run-level resource usage, measured from the run's own baselines."""
        self.resource_usage = measure_resources(
            self.started_at, self._wall_started, self._cpu_started
        )
        return self.resource_usage

    def bind_instance(self, node_id: str, instance: Any) -> None:
        """Attach a live node instance so its *actual* execution facts are kept."""
        self._instances[node_id] = instance
        record = self.records.get(node_id)
        if record is not None:
            self._apply_instance(record, instance)

    @staticmethod
    def _apply_instance(record: ProvenanceRecord, instance: Any) -> None:
        mode_fn = getattr(instance, "effective_execution_mode", None)
        if callable(mode_fn):
            try:
                mode, _note = mode_fn()
                record.execution_mode = str(mode or "")
            except Exception:  # noqa: BLE001 - diagnostics only
                record.execution_mode = str(getattr(instance, "execution_mode", "") or "")
        else:
            record.execution_mode = str(getattr(instance, "execution_mode", "") or "")
        record.capability_status = str(getattr(instance, "capability_status", "") or "")
        if not record.node_version:
            record.node_version = str(getattr(instance, "version", "") or "")
        record.deterministic = bool(getattr(instance, "deterministic", record.deterministic))
        if record.random_seed is None:
            record.random_seed = getattr(instance, "random_seed", None)

    # -- engine event hook --------------------------------------------------- #
    def __call__(self, event: Any) -> None:
        etype = getattr(event, "type", "")
        payload = getattr(event, "payload", {}) or {}
        node_id = str(getattr(event, "node_id", "") or "")
        if not node_id:
            if etype in {"run_completed", "run_failed"}:
                self.finished_at = utc_now_iso()
                self.run_status = "completed" if etype == "run_completed" else "failed"
            return
        record = self.records.get(node_id)
        if record is None:
            record = ProvenanceRecord(
                run_id=self.run_id,
                node_id=node_id,
                node_type=str(getattr(event, "node_type", "") or ""),
                environment=self.environment.to_dict(),
            )
            self.records[node_id] = record
        bound = self._instances.get(node_id)
        if bound is not None:
            self._apply_instance(record, bound)
        if etype == "node_started":
            record.started_at = utc_now_iso()
            params = payload.get("params")
            if isinstance(params, dict):
                record.params = dict(params)
        elif etype in {"node_completed", "node_cached"}:
            record.finished_at = utc_now_iso()
            record.status = "completed"
            record.cache_hit = etype == "node_cached"
        elif etype == "node_failed":
            record.finished_at = utc_now_iso()
            record.status = "failed"
            message = str(getattr(event, "message", "") or "")
            if message:
                record.errors.append(message)
        elif etype == "node_skipped":
            record.status = "skipped"

    # -- persistence ----------------------------------------------------------- #
    def execution_mode_census(self) -> Dict[str, int]:
        """Count nodes by the mode that *actually* executed (task P1-06).

        Lets a reader see at a glance how much of a result came from real
        external software versus a built-in approximation, without opening every
        node record.
        """
        census: Dict[str, int] = {}
        for record in self.records.values():
            key = record.execution_mode or "unspecified"
            census[key] = census.get(key, 0) + 1
        return dict(sorted(census.items()))

    def reproducibility(self) -> Dict[str, Any]:
        """State what is and is not expected to repeat bit-for-bit.

        The spec forbids an absolute promise ("all inputs always produce
        identical output"), so this returns *which* nodes are deterministic and
        *which* factors could cause divergence for the rest.

        Only nodes that genuinely consume randomness are listed.  A node that
        declares ``deterministic=True`` and does no sampling must not be
        reported as "unseeded": a report that flags every node trains readers to
        ignore the warning, which is worse than not warning at all.  A node is
        treated as randomness-consuming when it either declares itself
        non-deterministic, or exposes a ``seed`` parameter it left unset.
        """
        nondeterministic = [
            record.node_id
            for record in self.records.values()
            if not record.deterministic
        ]
        unseeded = [
            record.node_id
            for record in self.records.values()
            # It has a seed knob and did not set it -> its result genuinely may
            # vary and we cannot say why.
            if "seed" in (record.params or {}) and record.params.get("seed") is None
            and record.random_seed is None
        ]
        at_risk = sorted(set(nondeterministic) | set(unseeded))
        return {
            "all_nodes_deterministic": not nondeterministic,
            "nondeterministic_nodes": sorted(nondeterministic),
            "unseeded_random_nodes": sorted(unseeded),
            "nodes_at_risk_of_divergence": at_risk,
            "divergence_factors": [
                "线程调度顺序影响浮点求和次序（同代并行执行）",
                "外部科研软件版本差异（若 execution_mode=external）",
                "GPU 非确定性算子（若 device 为 cuda:*）",
                "模型采样温度大于 0（若节点调用了 LLM）",
            ] if at_risk else [],
            "claim": (
                "本记录的确定性结论仅覆盖声明为 deterministic 且已固定随机种子的节点。"
                "平台不承诺「所有输入永远产生完全相同的输出」。"
            ),
            "digest_scope": {
                "note": (
                    "output_digests 是科学内容摘要：按节点输出端口的规范化序列化计算，"
                    "已剔除运行期身份字段，因此同一确定性的图重复运行应得到相同摘要。"
                ),
                "excluded_keys": sorted(VOLATILE_DIGEST_KEYS),
                "excluded_value_pattern": GENERATED_ID_RE.pattern,
                "artifact_digests": "output_artifacts[].digest 为磁盘文件字节的 SHA-256。",
            },
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.records_default_schema(),
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.run_status,
            "platform": self.environment.platform,
            "environment": self.environment.to_dict(),
            "workflow": self.workflow,
            "max_workers": self.max_workers,
            "resource_usage": self.resource_usage,
            "execution_modes": self.execution_mode_census(),
            "reproducibility": self.reproducibility(),
            "nodes": {k: v.to_dict() for k, v in self.records.items()},
        }

    def records_default_schema(self) -> str:
        from .schema import PROVENANCE_SCHEMA_VERSION

        return PROVENANCE_SCHEMA_VERSION

    def write(self, run_dir: str | Path) -> Path:
        """Write ``provenance.json`` into ``run_dir`` atomically.

        A temp file is written and then *renamed* over the target.  The earlier
        version wrote the payload to both the temp and the target and then
        deleted the temp, which provided no atomicity (a crash mid-write still
        truncated the real file) while leaving a stray deletion behind.  On a
        hardened host that deletion is a liability, and the rename is strictly
        more correct.
        """
        target = Path(run_dir) / "provenance.json"
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        tmp = target.with_suffix(".json.tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, target)
        return target
