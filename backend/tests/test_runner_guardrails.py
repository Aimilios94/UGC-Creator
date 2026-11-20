"""Guardrails (M1) for the job runner and the spend limits."""

from __future__ import annotations

import pytest

from app import repository as repo
from app import worker
from app.services.pipeline import run_media_stage
from helpers import approve, create_job


def _approved_job(client, session_id, photo_bytes) -> str:
    job = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, job["id"]).status_code == 202
    return job["id"]


def _job(ctx, job_id):
    return repo.get_job(ctx.db, job_id)


def test_empty_queue_exits_zero(ctx, monkeypatch):
    """An execution started with an empty queue exits with code 0."""
    monkeypatch.setattr(worker, "build_context", lambda s: ctx)
    assert worker.main([]) == 0
    assert worker.run_once(ctx) is False


def test_retried_job_resumes_and_never_pays_twice(client, ctx, session_id, photo_bytes):
    """A crash while polling the video: the next attempt polls the same render (no new submit)
    and does not redo the finished image stage."""
    job_id = _approved_job(client, session_id, photo_bytes)
    real_status = ctx.media.status
    calls = {"n": 0}

    def crash_on_video(model, prediction_id):
        calls["n"] += 1
        if "video" in prediction_id and calls.setdefault("video_crashes", 0) == 0:
            calls["video_crashes"] = 1
            raise RuntimeError("worker killed while polling")
        return real_status(model, prediction_id)

    ctx.media.status = crash_on_video
    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "queued" and job["attempts"] == 1
    assert repo.get_stage_run(ctx.db, job_id, "image", 0)["status"] == "done"
    assert repo.get_stage_run(ctx.db, job_id, "video", 0)["status"] == "submitted"

    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "done" and job["attempts"] == 2
    assert [r.kind for r in ctx.media.submits] == ["image", "video"] * 3  # each scene's renders paid once
    with ctx.db.tx() as c:
        billed = c.execute(
            "select kind, count(*) as n from llm_calls where job_id = %s and kind in ('image','video') group by kind",
            (job_id,),
        ).fetchall()
    assert {r["kind"]: r["n"] for r in billed} == {"image": 3, "video": 3}


def test_always_failing_job_fails_after_two_attempts_with_error_shown(client, ctx, session_id, photo_bytes):
    job_id = _approved_job(client, session_id, photo_bytes)

    def boom(req):
        raise RuntimeError("provider is down")

    ctx.media.submit = boom
    worker.run_once(ctx)
    assert _job(ctx, job_id)["status"] == "queued"
    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "failed" and job["attempts"] == 2
    assert "provider is down" in job["last_error"]
    assert worker.run_once(ctx) is False  # never started a third time
    view = client.get(f"/jobs/{job_id}", headers={"X-Session-Id": session_id}).json()
    assert view["status"] == "failed" and "provider is down" in view["last_error"]
    # a failed submit spent nothing
    assert repo.job_spend_usd(ctx.db, job_id) == pytest.approx(
        sum(float(r["cost_usd"]) for r in _calls(ctx, job_id) if r["kind"] == "llm")
    )


def _calls(ctx, job_id):
    with ctx.db.tx() as c:
        return c.execute("select * from llm_calls where job_id = %s", (job_id,)).fetchall()


def test_no_paid_stage_starts_past_the_job_cap(client, ctx, session_id, photo_bytes):
    """Cap 0.20 EUR: the image (0.035 EUR) fits, the 5 s video (0.30 EUR) does not."""
    job_id = _approved_job(client, session_id, photo_bytes)
    ctx.settings = ctx.settings.model_copy(update={"job_cost_cap_eur": 0.20})
    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "failed" and "cost cap" in job["last_error"]
    assert [r.kind for r in ctx.media.submits] == ["image"]  # the video was never submitted
    assert repo.job_spend_usd(ctx.db, job_id) * ctx.settings.usd_to_eur_rate <= 0.20


def test_try_again_still_counts_spend_from_earlier_tries(client, ctx, session_id, photo_bytes):
    job_id = _approved_job(client, session_id, photo_bytes)
    ctx.settings = ctx.settings.model_copy(update={"job_cost_cap_eur": 0.20})
    worker.run_once(ctx)
    spent_before = repo.job_spend_usd(ctx.db, job_id)
    assert spent_before > 0

    r = client.post(f"/jobs/{job_id}/retry", headers={"X-Session-Id": session_id})
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["attempts"] == 0
    assert repo.job_spend_usd(ctx.db, job_id) == pytest.approx(spent_before)  # spend never resets
    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "failed" and "cost cap" in job["last_error"]
    assert [r.kind for r in ctx.media.submits] == ["image"]  # finished image reused, video still refused


def test_no_paid_stage_starts_past_the_daily_limit(client, ctx, session_id, photo_bytes):
    job_id = _approved_job(client, session_id, photo_bytes)
    # another job already spent almost all of today's limit
    with ctx.db.tx() as c:
        c.execute(
            """insert into llm_calls (kind, provider, model, status, est_cost_usd, cost_usd)
               values ('video', 'fal', 'x', 'billed', %s, %s)""",
            (ctx.settings.daily_spend_limit_usd - 0.01, ctx.settings.daily_spend_limit_usd - 0.01),
        )
    worker.run_once(ctx)
    job = _job(ctx, job_id)
    assert job["status"] == "failed" and "daily spend limit" in job["last_error"]
    assert ctx.media.submits == []


def test_daily_limit_also_guards_the_storyboard_step(client, ctx, session_id, photo_bytes):
    ctx.settings = ctx.settings.model_copy(update={"daily_spend_limit_eur": 0.0})
    with ctx.db.tx() as c:  # some spend already today
        c.execute("""insert into llm_calls (kind, provider, model, status, est_cost_usd, cost_usd)
                     values ('llm', 'openai', 'x', 'billed', 0.01, 0.01)""")
    r = create_job(client, session_id, photo_bytes)
    assert r.status_code == 201
    assert "daily spend limit" in r.json()["last_error"] and r.json()["storyboard"] is None


def test_open_reservations_count_toward_the_limit(client, ctx, session_id, photo_bytes):
    """An in-flight render's estimate counts, so a parallel stage cannot slip under the cap."""
    job_id = _approved_job(client, session_id, photo_bytes)
    with ctx.db.tx() as c:
        c.execute(
            """insert into llm_calls (job_id, kind, provider, model, status, est_cost_usd)
               values (%s, 'video', 'fal', 'x', 'reserved', %s)""",
            (job_id, ctx.settings.job_cost_cap_usd),
        )
    worker.run_once(ctx)
    assert "cost cap" in _job(ctx, job_id)["last_error"]
    assert ctx.media.submits == []


def test_media_cache_hit_costs_nothing(client, ctx, session_id, photo_bytes):
    job_id = _approved_job(client, session_id, photo_bytes)
    worker.run_once(ctx)
    assert len(ctx.media.submits) == 6  # 3 scenes x (image + video)
    # the same render again (same model, prompt, seed, input, settings) is served from the cache
    job = _job(ctx, job_id)
    with ctx.db.tx() as c:
        c.execute("delete from stage_runs where job_id = %s and stage = 'image'", (job_id,))
    from app.models import Brief, Scene
    from app.services.image_gen import plan_scene_image
    from app.services.pipeline import job_seed
    from app.services.providers.media import InputImage

    scene = Scene.model_validate(repo.list_scenes(ctx.db, job_id)[0]["data"])
    product = InputImage(ctx.storage.get(job["upload_key"]), "image/jpeg")
    run_media_stage(
        ctx,
        job,
        "image",
        0,
        lambda: plan_scene_image(
            model=ctx.settings.image_model,
            scene=scene,
            aspect_ratio=Brief.model_validate(job["brief"]).aspect_ratio,
            seed=job_seed(job_id),
            product=product,
            product_sha256=job["upload_sha256"],
        ),
    )
    assert len(ctx.media.submits) == 6  # no new paid render
    hits = [r for r in _calls(ctx, job_id) if r["cache_hit"]]
    assert len(hits) == 1 and float(hits[0]["cost_usd"]) == 0
