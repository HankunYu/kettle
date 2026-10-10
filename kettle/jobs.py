"""In-memory background jobs for slow operations (analysis, probes)."""

import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

from .config import now_iso

MAX_KEPT_JOBS = 50


class JobRunner:
    def __init__(self, workers=1):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="kettle-job")
        self._jobs = {}
        self._lock = threading.Lock()

    def submit(self, kind, meta, fn):
        """Queue fn() to run in the background; returns the job snapshot."""
        job = {
            "id": secrets.token_hex(6),
            "kind": kind,
            "meta": meta,
            "status": "queued",
            "created_at": now_iso(),
            "finished_at": None,
            "result": None,
            "error": None,
        }
        with self._lock:
            self._jobs[job["id"]] = job
            self._prune()
        self._pool.submit(self._run, job, fn)
        return dict(job)

    def _run(self, job, fn):
        self._set(job, status="running")
        try:
            result = fn()
        except Exception as e:
            self._set(job, status="failed", error=str(e), finished_at=now_iso())
        else:
            self._set(job, status="done", result=result, finished_at=now_iso())

    def _set(self, job, **fields):
        with self._lock:
            job.update(fields)

    def _prune(self):
        finished = [j for j in self._jobs.values() if j["status"] in ("done", "failed")]
        excess = len(self._jobs) - MAX_KEPT_JOBS
        for j in sorted(finished, key=lambda j: j["created_at"])[:max(excess, 0)]:
            del self._jobs[j["id"]]

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None

    def list(self):
        with self._lock:
            return sorted((dict(j) for j in self._jobs.values()), key=lambda j: j["created_at"], reverse=True)

    def active_for(self, kind, key, value):
        """Snapshot of a queued/running job of this kind whose meta[key] == value."""
        with self._lock:
            for j in self._jobs.values():
                if j["kind"] == kind and j["status"] in ("queued", "running") and j["meta"].get(key) == value:
                    return dict(j)
        return None
