import threading
import time

import pytest

from fastmap.services.jobs import JobStore, QueueFull


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def _wait(store, job_id, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        job = store.get(job_id)
        if job and job["status"] != "pending":
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def _until(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        if time.monotonic() > end:
            raise AssertionError("condition not reached")
        time.sleep(0.01)


def _blocking_store(**kw):
    """Store whose jobs wait on ``gate``; tracks peak concurrency."""
    gate = threading.Event()
    state = {"running": 0, "peak": 0}
    lock = threading.Lock()

    def job():
        with lock:
            state["running"] += 1
            state["peak"] = max(state["peak"], state["running"])
        gate.wait(5)
        with lock:
            state["running"] -= 1
        return {"path": None, "filename": "f.pdf"}

    return JobStore(**kw), job, gate, state


def test_submit_runs_job_and_records_result():
    store = JobStore(workers=1, max_pending=5, ttl_s=60)
    job_id = store.submit(lambda: {"path": None, "filename": "a.pdf", "actual_scale": 20000})
    job = _wait(store, job_id)
    assert job["status"] == "done"
    assert job["filename"] == "a.pdf"
    assert job["actual_scale"] == 20000


def test_failed_job_records_error():
    def boom():
        raise RuntimeError("tile 11/2/3 failed")

    store = JobStore(workers=1, max_pending=5, ttl_s=60)
    job = _wait(store, store.submit(boom))
    assert job["status"] == "error"
    assert job["error"] == "tile 11/2/3 failed"


def test_at_most_workers_jobs_render_at_once():
    store, job, gate, state = _blocking_store(workers=2, max_pending=10, ttl_s=60)
    ids = [store.submit(job) for _ in range(5)]
    _until(lambda: state["running"] == 2)
    time.sleep(0.1)  # give a third job the chance to (wrongly) start
    assert state["running"] == 2
    gate.set()
    for i in ids:
        assert _wait(store, i)["status"] == "done"
    assert state["peak"] == 2


def test_queue_full_rejects_until_a_job_finishes():
    store, job, gate, _ = _blocking_store(workers=1, max_pending=2, ttl_s=60)
    first = store.submit(job)
    store.submit(job)
    with pytest.raises(QueueFull):
        store.submit(job)
    gate.set()
    _wait(store, first)  # the slot is freed before the job shows as done
    store.submit(lambda: {"path": None, "filename": "x"})  # room again


def test_run_waits_for_result_and_counts_against_the_limit():
    store, job, gate, _ = _blocking_store(workers=1, max_pending=1, ttl_s=60)
    assert store.run(lambda: 42) == 42
    store.submit(job)
    with pytest.raises(QueueFull):
        store.run(lambda: 1)
    gate.set()


def test_run_reraises_the_job_exception():
    store = JobStore(workers=1, max_pending=5, ttl_s=60)

    def boom():
        raise ValueError("bad")

    with pytest.raises(ValueError, match="bad"):
        store.run(boom)
    assert store.run(lambda: "ok") == "ok"  # slot was released


def test_sweep_removes_expired_jobs_and_their_files(tmp_path):
    clock = FakeClock()
    store = JobStore(workers=1, max_pending=5, ttl_s=60, clock=clock)
    old_file = tmp_path / "old.pdf"
    old_file.write_bytes(b"%PDF")
    old = _wait(store, store.submit(lambda: {"path": str(old_file), "filename": "old.pdf"}))
    assert old["status"] == "done"

    clock.t += 61
    new_file = tmp_path / "new.pdf"
    new_file.write_bytes(b"%PDF")
    new_id = store.submit(lambda: {"path": str(new_file), "filename": "new.pdf"})
    _wait(store, new_id)

    store.sweep()
    assert not old_file.exists()
    assert new_file.exists()
    assert store.get(new_id)["status"] == "done"
    assert len(store) == 1


def test_sweep_keeps_unfinished_jobs():
    clock = FakeClock()
    store, job, gate, _ = _blocking_store(workers=1, max_pending=5, ttl_s=60, clock=clock)
    job_id = store.submit(job)
    clock.t += 10_000
    store.sweep()
    assert store.get(job_id)["status"] == "pending"
    gate.set()


def test_run_rejects_when_no_worker_is_free_right_now():
    """Sync requests must not queue behind async renders (proxy idle timeout)."""
    store, job, gate, state = _blocking_store(workers=1, max_pending=5, ttl_s=60)
    store.submit(job)
    _until(lambda: state["running"] == 1)
    with pytest.raises(QueueFull):
        store.run(lambda: 1)  # queue has room, but no idle worker
    gate.set()
    _until(lambda: state["running"] == 0)
    _until(lambda: _try_run(store) == 1)


def _try_run(store):
    try:
        return store.run(lambda: 1)
    except QueueFull:
        return None


def test_take_done_removes_only_finished_jobs():
    store, job, gate, _ = _blocking_store(workers=1, max_pending=5, ttl_s=60)
    pending = store.submit(job)
    assert store.take_done(pending)["status"] == "pending"
    assert store.get(pending) is not None  # still there
    gate.set()
    _wait(store, pending)
    assert store.take_done(pending)["status"] == "done"
    assert store.take_done(pending) is None  # a second download gets nothing


def test_failed_pool_submit_frees_the_slot(monkeypatch):
    store = JobStore(workers=1, max_pending=1, ttl_s=60)
    real_submit = store._pool.submit

    def broken(*a, **kw):
        raise RuntimeError("cannot schedule new futures after shutdown")

    monkeypatch.setattr(store._pool, "submit", broken)
    with pytest.raises(RuntimeError):
        store.submit(lambda: {"path": None, "filename": "x"})
    with pytest.raises(RuntimeError):
        store.run(lambda: 1)
    assert len(store) == 0  # no orphan "pending" row

    monkeypatch.setattr(store._pool, "submit", real_submit)
    assert store.run(lambda: 7) == 7  # the single slot is free again


def test_shutdown_cancels_queued_jobs():
    store, job, gate, state = _blocking_store(workers=1, max_pending=5, ttl_s=60)
    store.submit(job)
    queued = store.submit(job)
    _until(lambda: state["running"] == 1)
    store.shutdown()
    gate.set()
    time.sleep(0.1)
    assert store.get(queued)["status"] == "pending"  # never ran
    assert state["peak"] == 1
    with pytest.raises(RuntimeError):
        store.submit(job)
