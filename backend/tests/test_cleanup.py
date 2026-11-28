"""The scheduled cleanup and sweep, and "delete my data" (M2 item 6, plan §8 and §11, D6, D34)."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app import repository as repo
from app import worker
from app.services.cleanup import run_cleanup
from conftest import new_session
from helpers import approve, create_job

TOKEN = "test-admin-token-0123456789"


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def _sql(ctx, sql: str, params=()) -> None:
    with ctx.db.tx() as c:
        c.execute(sql, params)


def _one(ctx, sql: str, params=()):
    with ctx.db.tx() as c:
        return c.execute(sql, params).fetchone()


def _files(storage, prefix: str) -> list:
    folder = storage.root / prefix
    return [p for p in folder.rglob("*") if p.is_file()] if folder.is_dir() else []


def _logo() -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", (64, 64), (10, 20, 30, 128)).save(buf, "PNG")
    return buf.getvalue()


def _with_token(ctx):
    ctx.settings.admin_token = TOKEN


# --- the endpoint -------------------------------------------------------------------
def test_cleanup_endpoint_refuses_calls_without_the_token(client, ctx):
    assert client.post("/admin/cleanup").status_code == 503  # not configured: off
    _with_token(ctx)
    assert client.post("/admin/cleanup").status_code == 401
    assert client.post("/admin/cleanup", headers={"X-Admin-Token": "wrong"}).status_code == 401
    r = client.post("/admin/cleanup", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200 and r.json()["jobs_deleted"] == 0


# --- the sweep ----------------------------------------------------------------------
def _running(client, ctx, session_id, photo_bytes, *, attempts: int, minutes_ago: int) -> str:
    job = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, job["id"]).status_code == 202
    _sql(
        ctx,
        "update jobs set status = 'running', attempts = %s, claimed_at = now() - make_interval(mins => %s) "
        "where id = %s",
        (attempts, minutes_ago, job["id"]),
    )
    return job["id"]


def test_a_stale_running_job_is_requeued_and_picked_up_without_a_new_approval(client, ctx, session_id, photo_bytes):
    job_id = _running(client, ctx, session_id, photo_bytes, attempts=1, minutes_ago=120)
    out = run_cleanup(ctx)
    assert out["requeued"] == 1 and out["failed"] == 0
    row = repo.get_job(ctx.db, job_id)
    assert row["status"] == "queued" and row["attempts"] == 1
    assert worker.run_once(ctx) is True  # the worker takes it again on its own
    assert repo.get_job(ctx.db, job_id)["status"] == "done"


def test_a_stale_job_on_its_last_try_fails_and_its_open_estimates_are_settled(client, ctx, session_id, photo_bytes):
    job_id = _running(client, ctx, session_id, photo_bytes, attempts=2, minutes_ago=120)
    sent = repo.start_stage(ctx.db, job_id, "video", 0, provider="mock", model="m", attempt=2)
    repo.mark_submitted(ctx.db, sent["id"], "pred-1")
    never_sent = repo.start_stage(ctx.db, job_id, "image", 0, provider="mock", model="m", attempt=2)
    for sr in (sent, never_sent):
        _sql(
            ctx,
            "insert into llm_calls (job_id, stage_run_id, kind, provider, model, status, est_cost_usd) "
            "values (%s, %s, 'video', 'mock', 'm', 'reserved', 0.5)",
            (job_id, sr["id"]),
        )

    out = run_cleanup(ctx)
    assert out["failed"] == 1 and out["requeued"] == 0
    row = repo.get_job(ctx.db, job_id)
    assert row["status"] == "failed" and "stopped twice" in row["last_error"]
    calls = {r["stage_run_id"]: r for r in _all_calls(ctx, job_id)}
    assert calls[sent["id"]]["status"] == "billed" and float(calls[sent["id"]]["cost_usd"]) == 0.5
    assert calls[never_sent["id"]]["status"] == "released" and float(calls[never_sent["id"]]["cost_usd"]) == 0
    assert worker.run_once(ctx) is False  # never started again


def _all_calls(ctx, job_id):
    with ctx.db.tx() as c:
        return c.execute("select * from llm_calls where job_id = %s", (job_id,)).fetchall()


def test_a_queued_job_with_every_try_used_is_failed_and_never_started(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, job["id"]).status_code == 202
    _sql(ctx, "update jobs set attempts = 2 where id = %s", (job["id"],))
    assert run_cleanup(ctx)["failed"] == 1
    assert repo.get_job(ctx.db, job["id"])["status"] == "failed"
    assert worker.run_once(ctx) is False


def test_a_fresh_second_try_is_left_alone(client, ctx, session_id, photo_bytes):
    job_id = _running(client, ctx, session_id, photo_bytes, attempts=2, minutes_ago=5)
    out = run_cleanup(ctx)
    assert out["failed"] == 0 and out["requeued"] == 0
    assert repo.get_job(ctx.db, job_id)["status"] == "running"


# --- retention ----------------------------------------------------------------------
def test_retention_deletes_expired_ads_files_and_unused_brand_data(client, ctx, storage, session_id, photo_bytes):
    old = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, old["id"]).status_code == 202
    assert worker.run_once(ctx) is True
    assert _files(storage, f"jobs/{old['id']}")
    spent = float(_one(ctx, "select sum(cost_usd) as s from llm_calls where job_id = %s", (old["id"],))["s"])
    assert client.post("/brand-kit/logo", files={"logo": ("l.png", _logo(), "image/png")}, headers=_h(session_id))
    assert _files(storage, "brand")
    other = new_session()
    recent = create_job(client, other, photo_bytes).json()

    _sql(ctx, "update jobs set finished_at = now() - interval '31 days', created_at = now() - interval '31 days', "
              "updated_at = now() - interval '31 days' where id = %s", (old["id"],))  # fmt: skip
    _sql(ctx, "update brand_kits set updated_at = now() - interval '31 days'")
    _sql(ctx, "update campaigns set updated_at = now() - interval '31 days' where session_hash <> "
              "(select session_hash from jobs where id = %s)", (recent["id"],))  # fmt: skip

    out = run_cleanup(ctx)
    assert out["jobs_deleted"] == 1 and out["brand_kits_deleted"] == 1 and out["campaigns_deleted"] >= 1
    assert repo.get_job(ctx.db, old["id"]) is None
    assert not _files(storage, f"jobs/{old['id']}") and not _files(storage, "brand")
    assert repo.get_job(ctx.db, recent["id"]) is not None and _files(storage, f"jobs/{recent['id']}")
    # its cost still counts toward the day, without the link to the ad
    kept = _one(ctx, "select sum(cost_usd) as s from llm_calls where job_id is null")["s"]
    assert float(kept) == pytest.approx(spent)


def test_a_brand_kit_in_use_is_kept(client, ctx, storage, session_id, photo_bytes):
    assert client.post("/brand-kit/logo", files={"logo": ("l.png", _logo(), "image/png")}, headers=_h(session_id))
    _sql(ctx, "update brand_kits set updated_at = now() - interval '31 days'")
    create_job(client, session_id, photo_bytes)  # a new ad this month counts as use
    assert run_cleanup(ctx)["brand_kits_deleted"] == 0
    assert _files(storage, "brand")


# --- delete my data -----------------------------------------------------------------
def test_delete_my_data_removes_this_sessions_data_and_leaves_others(client, ctx, storage, session_id, photo_bytes):
    mine = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, mine["id"]).status_code == 202
    assert worker.run_once(ctx) is True
    assert client.post("/brand-kit/logo", files={"logo": ("l.png", _logo(), "image/png")}, headers=_h(session_id))
    other = new_session()
    theirs = create_job(client, other, photo_bytes).json()
    assert client.post("/brand-kit/logo", files={"logo": ("l.png", _logo(), "image/png")}, headers=_h(other))

    r = client.delete("/my-data", headers=_h(session_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["jobs_deleted"] == 1 and body["brand_kits_deleted"] == 1 and body["campaigns_deleted"] >= 1
    assert body["files_deleted"] > 0 and body["kept_busy"] is False
    assert client.get("/jobs", headers=_h(session_id)).json() == []
    assert client.get("/campaigns", headers=_h(session_id)).json() == []
    assert not _files(storage, f"jobs/{mine['id']}")

    assert [j["id"] for j in client.get("/jobs", headers=_h(other)).json()] == [theirs["id"]]
    assert _files(storage, f"jobs/{theirs['id']}") and _files(storage, "brand")
    assert len(client.get("/campaigns", headers=_h(other)).json()) == 1


def test_delete_my_data_waits_while_an_ad_is_being_made(client, ctx, storage, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, job["id"]).status_code == 202  # queued
    r = client.delete("/my-data", headers=_h(session_id))
    assert r.status_code == 409 and "being made" in r.json()["detail"]
    assert repo.get_job(ctx.db, job["id"]) is not None and _files(storage, f"jobs/{job['id']}")


def test_delete_my_data_needs_a_session(client):
    assert client.delete("/my-data").status_code == 400


def test_a_storage_folder_must_be_one_job_or_one_session(storage):
    for bad in ("jobs/", "jobs", "brand/", "", "../x/"):
        with pytest.raises(ValueError):
            storage.delete_prefix(bad)
