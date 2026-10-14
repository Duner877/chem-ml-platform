"""DAG execution engine.

The engine turns a :class:`~workflow_engine.workflow.Workflow` into a
NetworkX directed graph, resolves it with a topological sort and executes the
nodes generation by generation (nodes that do not depend on each other run in
parallel).  Data flows along the edges as :class:`ScientificObject` instances.
"""

from __future__ import annotations

import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import networkx as nx

from .cache import ResultCache, compute_cache_key
from .errors import WorkflowValidationError
from .events import (
    NODE_CACHED,
    NODE_COMPLETED,
    NODE_FAILED,
    NODE_LOG,
    NODE_SKIPPED,
    NODE_STARTED,
    RUN_CANCELLED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    Event,
    EventBus,
)
from .objects import deserialize_object, serialize_object
from .ports import port_by_name
from .registry import NodeRegistry, registry as global_registry
from .utils import ensure_dir, new_id, now_iso
from .workflow import Workflow

__all__ = ["NodeExecutionRecord", "RunResult", "ExecutionContext", "WorkflowEngine"]

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"
STATUS_CANCELLED = "cancelled"


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
@dataclass
class NodeExecutionRecord:
    """Execution trace of a single node."""

    node_id: str
    node_type: str
    status: str = STATUS_PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    error: str = ""
    logs: List[str] = field(default_factory=list)
    outputs: Dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    progress: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_type": self.node_type,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "error": self.error,
            "logs": list(self.logs),
            "outputs": serialize_object(self.outputs),
            "cached": self.cached,
            "progress": self.progress,
        }


@dataclass
class RunResult:
    """Outcome of a workflow execution."""

    run_id: str
    workflow_name: str = ""
    status: str = STATUS_PENDING
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    records: Dict[str, NodeExecutionRecord] = field(default_factory=dict)
    artifacts: List[str] = field(default_factory=list)
    errors: List[Dict[str, str]] = field(default_factory=list)
    provenance_path: str = ""  # v0.7: provenance.json inside the run directory

    # -- convenience -------------------------------------------------------- #
    def outputs(self, node_id: str) -> Dict[str, Any]:
        record = self.records.get(str(node_id))
        return dict(record.outputs) if record else {}

    def output(self, node_id: str, port: Optional[str] = None) -> Any:
        values = self.outputs(node_id)
        if port is not None and port in values:
            return values[port]
        for value in values.values():
            if value is not None:
                return value
        return None

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMPLETED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "artifacts": list(self.artifacts),
            "errors": list(self.errors),
            "provenance_path": self.provenance_path,
            "records": {
                key: record.to_dict() for key, record in self.records.items()
            },
        }


# --------------------------------------------------------------------------- #
# Execution context
# --------------------------------------------------------------------------- #
class NodeLogger:
    """Logging facade bound to a node, emitting engine events."""

    def __init__(self, ctx: "ExecutionContext", node_id: str, node_type: str):
        self.ctx = ctx
        self.node_id = node_id
        self.node_type = node_type

    def __call__(self, message: str) -> None:
        self.ctx.emit(
            NODE_LOG,
            str(message),
            node_id=self.node_id,
            node_type=self.node_type,
        )

    # Allow ctx.logger.info / .warning / .error
    def info(self, message: str) -> None:
        self(message)

    def warning(self, message: str) -> None:
        self(f"[warn] {message}")

    def error(self, message: str) -> None:
        self(f"[error] {message}")


class ExecutionContext:
    """Runtime services handed to every node ``execute()`` call."""

    def __init__(
        self,
        run_id: str = "",
        workdir: str | Path | None = None,
        bus: EventBus | None = None,
        max_workers: int = 4,
    ):
        self.run_id = run_id or new_id("run_")
        base = Path(workdir) if workdir else Path(ensure_dir(Path(__file__).resolve().parents[1] / "output"))
        self.workdir = ensure_dir(base)
        self.run_dir = ensure_dir(self.workdir / "runs" / self.run_id)
        self.artifacts_dir = ensure_dir(self.run_dir / "artifacts")
        self.cache_dir = ensure_dir(self.workdir / "cache")
        self.bus = bus or EventBus()
        self.max_workers = max(1, int(max_workers))
        self.artifacts: List[str] = []
        self.cache = ResultCache(self.cache_dir, enabled=False)
        self._loggers: Dict[str, NodeLogger] = {}
        # v0.7.1 (task H/J): live provenance + workflow metadata so report nodes
        # can cite the exact execution context instead of guessing.
        self.provenance: Any = None
        self.workflow_meta: Dict[str, Any] = {}

    # -- events -------------------------------------------------------------- #
    def emit(
        self,
        type_: str,
        message: str = "",
        *,
        node_id: str = "",
        node_type: str = "",
        progress: float = 0.0,
        **payload: Any,
    ) -> Event:
        return self.bus.emit(
            type_,
            message,
            run_id=self.run_id,
            node_id=node_id,
            node_type=node_type,
            progress=progress,
            **payload,
        )

    def logger(self, node_id: str = "", node_type: str = "") -> NodeLogger:
        key = f"{node_id}:{node_type}"
        if key not in self._loggers:
            self._loggers[key] = NodeLogger(self, node_id, node_type)
        return self._loggers[key]

    # -- artefacts ------------------------------------------------------------ #
    def artifact_path(self, filename: str, subdir: str = "") -> Path:
        """Return a path inside the run artefact folder and remember it."""
        directory = ensure_dir(self.artifacts_dir / subdir) if subdir else self.artifacts_dir
        path = directory / filename
        self.artifacts.append(str(path))
        return path

    def relative_artifact(self, path: str | Path) -> str:
        """Artefact path relative to the run directory (for GUI download)."""
        try:
            return str(Path(path).relative_to(self.run_dir))
        except ValueError:
            return str(path)


# --------------------------------------------------------------------------- #
# Engine
# --------------------------------------------------------------------------- #
class WorkflowEngine:
    """Executes workflows described as JSON / :class:`Workflow` objects."""

    def __init__(
        self,
        registry: NodeRegistry | None = None,
        workdir: str | Path | None = None,
        max_workers: int = 4,
        use_cache: bool = False,
        event_listeners: Optional[List[Callable[[Event], None]]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.registry = registry or global_registry
        self.max_workers = max(1, int(max_workers))
        self.use_cache = bool(use_cache)
        self.workdir = Path(workdir) if workdir else None
        self._listeners = list(event_listeners or [])
        #: Cooperative cancellation (v0.7.1, spec B.6): polled between node
        #: generations so a cancelled task stops *scheduling* further work and
        #: records exactly which nodes never ran.
        self.cancel_check = cancel_check

    # -- validation ---------------------------------------------------------- #
    def validate(self, workflow: Workflow | Dict[str, Any]) -> List[str]:
        """Return the list of structural problems of ``workflow``."""
        wf = self._as_workflow(workflow)
        return wf.validate(self.registry)

    def assert_valid(self, workflow: Workflow | Dict[str, Any]) -> Workflow:
        wf = self._as_workflow(workflow)
        issues = wf.validate(self.registry)
        if issues:
            raise WorkflowValidationError(
                f"Workflow {wf.name!r} is invalid:\n"
                + "\n".join(f"  - {i}" for i in issues)
            )
        return wf

    # -- execution ----------------------------------------------------------- #
    def run(
        self,
        workflow: Workflow | Dict[str, Any],
        inputs: Optional[Dict[str, Dict[str, Any]]] = None,
        run_id: str = "",
        event_listener: Optional[Callable[[Event], None]] = None,
    ) -> RunResult:
        """Execute ``workflow`` and return the full :class:`RunResult`.

        ``inputs`` optionally injects data into specific node inputs, using the
        ``{node_id: {port_name: value}}`` layout.
        """
        wf = self.assert_valid(workflow)
        ctx = ExecutionContext(
            run_id=run_id or new_id("run_"),
            workdir=self.workdir,
            max_workers=self.max_workers,
        )
        ctx.cache = ResultCache(ctx.cache_dir, enabled=self.use_cache)
        for listener in self._listeners:
            ctx.bus.subscribe(listener)
        if event_listener:
            ctx.bus.subscribe(event_listener)
        # v0.7 (spec section 11): every run records provenance via the bus.
        from provenance import ProvenanceCollector

        collector = ProvenanceCollector(ctx.run_id)
        ctx.bus.subscribe(collector)
        ctx.provenance = collector
        ctx.workflow_meta = {
            "name": wf.name,
            "version": str(getattr(wf, "version", "") or ""),
            "node_count": len(wf.nodes),
            "edge_count": len(wf.edges),
            "run_id": ctx.run_id,
        }

        external = {str(k): dict(v or {}) for k, v in (inputs or {}).items()}
        result = RunResult(
            run_id=ctx.run_id,
            workflow_name=wf.name,
            started_at=now_iso(),
            status=STATUS_RUNNING,
        )
        ctx.emit(RUN_STARTED, f"start {wf.name}", progress=0.0, total=len(wf.nodes))

        graph = wf.to_networkx()
        outputs: Dict[str, Dict[str, Any]] = {}
        started = time.perf_counter()
        total = max(1, len(wf.nodes))
        done = 0
        cancelled = False

        for generation in nx.topological_generations(graph):
            batch = [wf.get_node(node_id) for node_id in generation]
            batch = [n for n in batch if n is not None]
            if not batch:
                continue
            # Cooperative cancellation: stop scheduling new generations and
            # mark everything still pending as skipped (never "completed").
            if self.cancel_check is not None and self.cancel_check():
                cancelled = True
                for node in batch:
                    record = result.records.setdefault(
                        node.node_id,
                        NodeExecutionRecord(node_id=node.node_id, node_type=node.node_type),
                    )
                    if record.status in (STATUS_PENDING, STATUS_RUNNING):
                        record.status = STATUS_SKIPPED
                        record.error = "cancelled before execution"
                    ctx.emit(NODE_SKIPPED, "cancelled", node_id=node.node_id,
                             node_type=node.node_type)
                break
            if len(batch) == 1 or self.max_workers == 1:
                for node in batch:
                    self._execute_node(node, wf, ctx, outputs, external, result)
                    done += 1
                    ctx.emit(
                        NODE_LOG,
                        "progress",
                        progress=round(done / total, 3),
                    )
            else:
                with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                    futures = [
                        pool.submit(
                            self._execute_node, node, wf, ctx, outputs, external, result
                        )
                        for node in batch
                    ]
                    for future in futures:
                        future.result()
                    done += len(batch)
                    ctx.emit(NODE_LOG, "progress", progress=round(done / total, 3))

        result.duration_ms = (time.perf_counter() - started) * 1000.0
        result.finished_at = now_iso()
        result.artifacts = list(dict.fromkeys(ctx.artifacts))
        if cancelled:
            result.status = STATUS_CANCELLED
        else:
            result.status = (
                STATUS_FAILED if result.errors else STATUS_COMPLETED
            )
        ctx.emit(
            RUN_CANCELLED if cancelled else (RUN_COMPLETED if result.ok else RUN_FAILED),
            f"finished {wf.name} ({result.status})",
            progress=1.0,
            status=result.status,
        )
        # v0.7: persist provenance.json after the terminal event so the
        # collector has seen the full lifecycle; never break the run.
        try:
            prov_file = collector.write(ctx.run_dir)
            result.provenance_path = str(prov_file)
        except Exception as exc:  # noqa: BLE001 - diagnostics only
            ctx.emit(NODE_LOG, f"provenance write failed: {exc}")
        return result

    # -- internals ----------------------------------------------------------- #
    def _execute_node(
        self,
        node,
        wf: Workflow,
        ctx: ExecutionContext,
        outputs: Dict[str, Dict[str, Any]],
        external: Dict[str, Dict[str, Any]],
        result: RunResult,
    ) -> None:
        record = NodeExecutionRecord(
            node_id=node.id, node_type=node.type, started_at=now_iso()
        )
        result.records[node.id] = record

        # 1. upstream state ------------------------------------------------- #
        for edge in wf.incoming(node.id):
            upstream = result.records.get(edge.source)
            if upstream is not None and upstream.status in {
                STATUS_FAILED,
                STATUS_SKIPPED,
            }:
                record.status = STATUS_SKIPPED
                record.error = f"upstream node {edge.source} did not complete"
                record.finished_at = now_iso()
                ctx.emit(
                    NODE_SKIPPED,
                    record.error,
                    node_id=node.id,
                    node_type=node.type,
                )
                return

        # 2. gather inputs --------------------------------------------------- #
        try:
            node_cls = self.registry.get(node.type)
        except Exception as exc:  # pragma: no cover - validation covers this
            record.status = STATUS_FAILED
            record.error = str(exc)
            result.errors.append({"node_id": node.id, "error": str(exc)})
            return

        incoming: Dict[str, Any] = {}
        for edge in wf.incoming(node.id):
            src_outputs = outputs.get(edge.source, {})
            src_port = port_by_name(node_cls.output_ports, edge.source_port)
            dst_port = port_by_name(node_cls.input_ports, edge.target_port)
            src_key = src_port.name if src_port else edge.source_port
            dst_key = dst_port.name if dst_port else edge.target_port
            if src_key is None:
                value = next(iter(src_outputs.values()), None) if src_outputs else None
            else:
                value = src_outputs.get(src_key)
            if dst_key is None:
                continue
            previous = incoming.get(dst_key)
            if previous is None:
                incoming[dst_key] = value
            elif isinstance(previous, list):
                previous.append(value)
            else:
                incoming[dst_key] = [previous, value]

        for port, value in external.get(node.id, {}).items():
            incoming[port] = deserialize_object(value)

        record.status = STATUS_RUNNING
        ctx.emit(
            NODE_STARTED,
            f"run {node.type}",
            node_id=node.id,
            node_type=node.type,
            params=dict(node.params),
        )

        instance = node_cls(node_id=node.id, params=dict(node.params))
        started = time.perf_counter()

        # 3. cache lookup ------------------------------------------------------ #
        cache_key = ""
        if self.use_cache and instance.cacheable:
            cache_key = compute_cache_key(node.type, instance.params, incoming)
            cached = ctx.cache.get(cache_key)
            if cached is not None:
                record.outputs = deserialize_object(cached)
                outputs[node.id] = record.outputs
                record.status = STATUS_COMPLETED
                record.cached = True
                record.duration_ms = (time.perf_counter() - started) * 1000.0
                record.finished_at = now_iso()
                record.progress = 1.0
                ctx.emit(
                    NODE_CACHED,
                    f"{node.type} (cache hit)",
                    node_id=node.id,
                    node_type=node.type,
                    progress=1.0,
                )
                return

        # 4. execute ----------------------------------------------------------- #
        try:
            result_outputs = instance.process(incoming, ctx)
        except Exception as exc:  # noqa: BLE001 - reported, run continues
            record.status = STATUS_FAILED
            record.error = str(exc)
            record.logs.extend(instance.logs)
            record.finished_at = now_iso()
            record.duration_ms = (time.perf_counter() - started) * 1000.0
            result.errors.append(
                {
                    "node_id": node.id,
                    "node_type": node.type,
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=6),
                }
            )
            ctx.emit(
                NODE_FAILED,
                str(exc),
                node_id=node.id,
                node_type=node.type,
            )
            return

        record.outputs = result_outputs
        outputs[node.id] = result_outputs
        record.status = STATUS_COMPLETED
        record.logs.extend(instance.logs)
        record.duration_ms = (time.perf_counter() - started) * 1000.0
        record.finished_at = now_iso()
        record.progress = 1.0

        if cache_key:
            ctx.cache.put(cache_key, result_outputs)

        ctx.emit(
            NODE_COMPLETED,
            f"{node.type} done",
            node_id=node.id,
            node_type=node.type,
            progress=1.0,
        )

    @staticmethod
    def _as_workflow(workflow: Workflow | Dict[str, Any]) -> Workflow:
        if isinstance(workflow, Workflow):
            return workflow
        if isinstance(workflow, dict):
            return Workflow.from_dict(workflow)
        raise TypeError(f"Unsupported workflow type: {type(workflow).__name__}")
