"""Bounded background rendering with an in-memory job table.

Rendering a map holds tens of MB of raster in memory, so the number of
maps rendered at once is capped (``workers``) and so is the number of jobs
queued or running (``max_pending``); beyond that callers get ``QueueFull``
and should answer 503. Synchronous renders (``run``) never queue: they need
an idle worker right away, or a proxy idle timeout would drop the client
while the render still runs. Finished jobs whose result is never downloaded are
dropped, with their temp files, after ``ttl_s``.

Single-process only: the table lives in this worker's memory.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

log = logging.getLogger(__name__)


class QueueFull(RuntimeError):
    """Too many jobs queued or running; try again later."""


class JobStore:
    def __init__(
        self,
        *,
        workers: int,
        max_pending: int,
        ttl_s: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="render")
        self._workers = workers
        self._max_pending = max_pending
        self._ttl_s = ttl_s
        self._clock = clock
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._active = 0  # queued + running, async and sync

    def __len__(self) -> int:
        with self._lock:
            return len(self._jobs)

    def _reserve(self, *, idle_worker: bool = False) -> None:
        with self._lock:
            if self._active >= self._max_pending:
                raise QueueFull(f"{self._active} maps already queued or rendering")
            if idle_worker and self._active >= self._workers:
                raise QueueFull("no idle render worker")
            self._active += 1

    def _release(self) -> None:
        with self._lock:
            self._active -= 1

    def submit(self, fn: Callable[[], dict[str, Any]]) -> str:
        """Queue ``fn`` (returns the result fields, incl. ``path``); return a job id."""
        self.sweep()
        self._reserve()
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = {"status": "pending"}
        try:
            self._pool.submit(self._run, job_id, fn)
        except BaseException:
            with self._lock:
                self._jobs.pop(job_id, None)
            self._release()
            raise
        return job_id

    def _run(self, job_id: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            update = {"status": "done", **fn()}
        except Exception as exc:
            log.warning("job %s failed: %s", job_id, exc)
            update = {"status": "error", "error": str(exc)}
        finally:
            self._release()
        with self._lock:
            self._jobs[job_id].update(update, finished=self._clock())

    def run(self, fn: Callable[[], Any]) -> Any:
        """Run ``fn`` on an idle worker and wait for its result; never queues."""
        self._reserve(idle_worker=True)

        def wrapped():
            try:
                return fn()
            finally:
                self._release()

        try:
            future = self._pool.submit(wrapped)
        except BaseException:
            self._release()
            raise
        return future.result()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job is not None else None

    def take_done(self, job_id: str) -> dict[str, Any] | None:
        """Atomically remove and return a finished job.

        A job that is not done yet stays in the table and is returned as a
        copy (callers answer 409); an unknown or already taken one gives None.
        Once taken, a sweep or a second download can no longer touch its file.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            if job["status"] != "done":
                return dict(job)
            return self._jobs.pop(job_id)

    def shutdown(self) -> None:
        """Stop accepting work and cancel queued renders (results are in memory
        and lost on exit anyway). Renders already running still finish: the
        interpreter joins pool threads at exit."""
        self._pool.shutdown(wait=False, cancel_futures=True)

    def sweep(self) -> None:
        """Drop finished jobs older than the TTL and delete their files."""
        cutoff = self._clock() - self._ttl_s
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if "finished" in job and job["finished"] < cutoff
            ]
            removed = [self._jobs.pop(job_id) for job_id in expired]
        for job in removed:
            path = job.get("path")
            if path:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if removed:
            log.info("swept %d expired jobs", len(removed))
