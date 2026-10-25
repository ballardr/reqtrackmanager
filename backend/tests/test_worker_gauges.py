"""Tests for the per-worker memory and database-pool gauges: they report a
plausible value, appear on `/metrics`, and the refresh loop survives a failure."""

import asyncio
import re

import pytest

from app import metrics
from app.database import engine


def _sample(client, name: str, labels: str = "") -> float | None:
    match = re.search(rf"^{name}{re.escape(labels)} ([0-9.e+]+)$", client.get("/metrics").text, re.MULTILINE)
    return float(match.group(1)) if match else None


def test_resident_memory_is_a_plausible_byte_count():
    # A Python process with the app imported is far above 10 MiB and far below 100 GiB.
    assert 10 * 2**20 < metrics.read_resident_memory_bytes() < 100 * 2**30


def test_resident_memory_falls_back_when_proc_is_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(metrics, "_STATM", tmp_path / "missing")
    assert metrics.read_resident_memory_bytes() > 0


def test_gauges_are_exported(client):
    metrics.update_worker_gauges(engine)
    assert _sample(client, "worker_resident_memory_bytes") > 10 * 2**20
    for state in ("checked_out", "idle"):
        assert _sample(client, "db_pool_connections", f'{{state="{state}"}}') is not None


def test_checked_out_connection_is_counted(client):
    with engine.connect():
        metrics.update_worker_gauges(engine)
        held = _sample(client, "db_pool_connections", '{state="checked_out"}')
    assert held >= 1


def test_loop_survives_a_failed_refresh(monkeypatch):
    calls = []

    def flaky(_engine):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")

    monkeypatch.setattr(metrics, "update_worker_gauges", flaky)

    async def run():
        task = asyncio.create_task(metrics.run_worker_gauge_loop(engine, interval_seconds=0.01))
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(calls) > 1


def test_dead_worker_gauge_files_are_purged(tmp_path):
    """A worker that exited leaves a `live*` gauge file behind; only the dead pid's file is dropped."""
    import os
    import subprocess
    import sys

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    (tmp_path / f"gauge_liveall_{dead.pid}.db").write_bytes(b"")
    (tmp_path / f"gauge_liveall_{os.getpid()}.db").write_bytes(b"")
    (tmp_path / "counter_1.db").write_bytes(b"")
    assert metrics.purge_dead_worker_gauges(str(tmp_path)) == [dead.pid]
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([f"gauge_liveall_{os.getpid()}.db", "counter_1.db"])
