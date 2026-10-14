"""Simulation job manager.

:mod:`simulation_runtime` runs one simulation at a time.  The job manager wraps
it so a request can be *submitted* and polled instead of blocking::

    from simulation_runtime.jobs import jobs

    job = jobs.submit("quantum", molecule, backend="orca", task="single_point")
    job.status          # queued -> running -> completed
    jobs.get(job.id)    # refreshed copy
    jobs.list()         # newest first

Every job records the engine that actually answered (``external:orca`` or
``internal:eht``) plus the metrics, so the GUI can show whether a real program
ran or the built-in engine was used.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflow_engine.utils import new_id, now_iso

__all__ = ["SimulationJob", "JobManager", "jobs", "get_jobs"]

#: Terminal states.
_STATUS_DONE = {"completed", "failed"}


@dataclass
class SimulationJob:
    """One submitted simulation and its lifecycle."""

    id: str
    family: str
    backend: str
    status: str = "queued"  # queued | running | completed | failed
    created_at: str = ""
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    engine: str = ""
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    ports: Dict[str, str] = field(default_factory=dict)
    workdir: str = ""
    error: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "family": self.family,
            "backend": self.backend,
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 3),
            "engine": self.engine,
            "message": self.message,
            "metrics": dict(self.metrics),
            "ports": dict(self.ports),
            "workdir": self.workdir,
            "error": self.error,
            "params": dict(self.params),
        }


class JobManager:
    """Thread backed simulation job queue."""

    def __init__(self, max_workers: int = 2, history: int = 200) -> None:
        self._jobs: List[SimulationJob] = []
        self._lock = threading.Lock()
        self._history = max(1, int(history))
        self._pool = ThreadPoolExecutor(max_workers=max(1, int(max_workers)))

    # -- submission --------------------------------------------------------- #
    def submit(
        self,
        family: str,
        system: Any,
        *,
        backend: str = "",
        **params: Any,
    ) -> SimulationJob:
        """Queue a simulation and return the job immediately."""
        job = SimulationJob(
            id=new_id("simg_"),
            family=str(family),
            backend=str(backend),
            created_at=now_iso(),
            params=_safe_params(params),
        )
        with self._lock:
            self._jobs.append(job)
            self._trim()
        self._pool.submit(self._execute, job, system, params)
        return job

    def run_now(
        self,
        family: str,
        system: Any,
        *,
        backend: str = "",
        **params: Any,
    ) -> SimulationJob:
        """Run a simulation synchronously and return the finished job."""
        job = SimulationJob(
            id=new_id("simg_"),
            family=str(family),
            backend=str(backend),
            created_at=now_iso(),
            params=_safe_params(params),
        )
        with self._lock:
            self._jobs.append(job)
            self._trim()
        self._execute(job, system, params)
        return job

    # -- execution ---------------------------------------------------------- #
    def _execute(self, job: SimulationJob, system: Any, params: Dict[str, Any]) -> None:
        from simulation_runtime import run

        with self._lock:
            job.status = "running"
            job.started_at = now_iso()
        started = time.perf_counter()
        try:
            result = run(job.family, system, backend=job.backend, **params)
        except Exception as exc:  # noqa: BLE001 - surfaced on the job
            with self._lock:
                job.status = "failed"
                job.error = f"{type(exc).__name__}: {exc}"
                job.finished_at = now_iso()
                job.duration_ms = (time.perf_counter() - started) * 1000.0
            return
        with self._lock:
            job.engine = str(getattr(result, "engine", "") or "")
            job.message = str(getattr(result, "message", "") or "")
            job.metrics = dict(getattr(result, "metrics", {}) or {})
            job.workdir = str(getattr(result, "workdir", "") or "")
            job.ports = {
                name: type(value).__name__
                for name, value in (getattr(result, "ports", {}) or {}).items()
            }
            job.status = "completed" if getattr(result, "success", True) else "failed"
            if not getattr(result, "success", True) and not job.error:
                job.error = job.message or "simulation failed"
            job.finished_at = now_iso()
            job.duration_ms = (time.perf_counter() - started) * 1000.0

    # -- reading ------------------------------------------------------------ #
    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for job in self._jobs:
                if job.id == job_id:
                    return job.to_dict()
        return None

    def list(self, *, limit: int = 50, family: str = "") -> List[Dict[str, Any]]:
        """Newest first, optionally filtered by family."""
        with self._lock:
            items = [
                job for job in self._jobs if not family or job.family == family
            ]
            items = list(reversed(items))
        if limit:
            items = items[: max(0, int(limit))]
        return [job.to_dict() for job in items]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            jobs = list(self._jobs)
        histogram: Dict[str, int] = {}
        for job in jobs:
            histogram[job.status] = histogram.get(job.status, 0) + 1
        return {"total": len(jobs), "by_status": histogram}

    def clear(self) -> None:
        with self._lock:
            self._jobs = [job for job in self._jobs if job.status not in _STATUS_DONE]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    # -- helpers ------------------------------------------------------------ #
    def _trim(self) -> None:
        """Keep only the newest ``_history`` jobs."""
        if len(self._jobs) > self._history:
            self._jobs = self._jobs[-self._history :]


#: Process wide job manager.
jobs = JobManager()


def get_jobs() -> JobManager:
    """The process wide job manager."""
    return jobs


def _safe_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """JSON safe copy of the job params (drop large / unserialisable values)."""
    clean: Dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
        else:
            clean[key] = type(value).__name__
    return clean
