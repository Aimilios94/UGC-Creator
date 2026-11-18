"""Guardrail (M1): the API and worker connect after a simulated first-connection failure
(Neon waking up from scale-to-zero)."""

from __future__ import annotations

import psycopg
import pytest

from app.repository import Database
from conftest import TEST_DB_URL


def _flaky(fail_times: int):
    calls = {"n": 0}

    def connect(url, **kwargs):
        calls["n"] += 1
        if calls["n"] <= fail_times:
            raise psycopg.OperationalError("endpoint is waking up")
        if TEST_DB_URL:
            return psycopg.connect(url, **kwargs)
        return "connection"

    return connect, calls


def test_connect_retries_after_a_wake_up_failure():
    connect, calls = _flaky(1)
    waits = []
    db = Database(TEST_DB_URL or "postgresql://x", retries=3, connect_fn=connect, sleep=waits.append)
    conn = db.connect()
    assert calls["n"] == 2 and waits == [0.5]
    if TEST_DB_URL:
        assert conn.execute("select 1 as one").fetchone()["one"] == 1
        conn.close()


def test_connect_gives_up_after_the_retry_budget():
    connect, calls = _flaky(10)
    db = Database("postgresql://x", retries=3, connect_fn=connect, sleep=lambda s: None)
    with pytest.raises(psycopg.OperationalError):
        db.connect()
    assert calls["n"] == 3


def test_api_and_worker_share_the_retrying_connection(monkeypatch, settings):
    """Both entrypoints build their Database the same way, with the configured retries."""
    from app import deps, worker

    s = settings.model_copy(update={"database_url": "postgresql://x", "db_connect_retries": 4})
    ctx = worker.build_context(s)
    assert ctx.db.retries == 4
    monkeypatch.setattr(deps, "get_settings", lambda: s)
    deps._context.cache_clear()
    try:
        assert deps.get_ctx().db.retries == 4
    finally:
        deps._context.cache_clear()
