"""Integration: the full M1 flow through the API with mock providers, plus the privacy and
access guardrails (session-scoped jobs, expiring asset URLs, access code, idempotent Approve)."""

from __future__ import annotations

import json

import httpx

from app import worker
from conftest import BRIEF, new_session
from helpers import approve, create_job, make_video, separate_shots


def test_brief_to_storyboard_to_playable_video(client, ctx, session_id, photo_bytes):
    r = create_job(client, session_id, photo_bytes)
    assert r.status_code == 201, r.text
    job = r.json()
    assert job["status"] == "draft"
    assert job["last_error"] is None
    assert [s["role"] for s in job["storyboard"]["scenes"]] == ["hook", "demo", "cta"]
    assert {h["formula"] for h in job["storyboard"]["hooks"]} == {"pov", "problem_first", "three_reasons"}
    assert job["analysis"]["people_in_photo"] is False
    assert {s["stage"]: s["status"] for s in job["stages"]} == {
        "analyze": "done",
        "slots": "done",  # the slot filler (D31 phase 3)
        "storyboard": "done",
        "continuity": "done",
    }
    structure = job["storyboard"]["structure"]
    assert [c["uid"] for c in structure["scenes"]] == [s["uid"] for s in job["storyboard"]["scenes"]]
    assert ctx.media.submits == []  # nothing paid renders before approval
    assert job["storyboard"]["continuity"] == "continuous"  # the default since D30
    job = separate_shots(client, session_id, job)  # this flow counts one picture per scene

    r = approve(client, session_id, job["id"])
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["phase"] == "images"

    # Step 1: the images only, then the job waits for "Make the video".
    assert worker.run_once(ctx) is True
    step1 = client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).json()
    assert (step1["status"], step1["phase"]) == ("done", "images")
    assert {a["kind"] for a in step1["assets"]} == {"upload", "image"}
    assert [r.kind for r in ctx.media.submits] == ["image"] * 3
    assert step1["variants"][0]["status"] == "queued"
    assert step1["estimate"]["images"]["eur"] == 0 and step1["estimate"]["video"]["eur"] > 0

    # Step 2: voice, clips and the composed ad.
    r = make_video(client, session_id, job["id"])
    assert r.status_code == 202 and r.json()["status"] == "queued" and r.json()["phase"] == "video"
    assert worker.run_once(ctx) is True
    done = client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).json()
    assert done["status"] == "done", done["last_error"]
    scene_files = {(a["kind"], a["scene_idx"]) for a in done["assets"] if a["scene_idx"] is not None}
    assert scene_files == {(k, i) for k in ("audio", "image", "video") for i in range(3)}  # 3 scenes, voiced (M2)
    variant = done["variants"][0]
    assert (variant["label"], variant["hook_idx"], variant["status"]) == ("A", 0, "done")
    assert variant["ratios"][0] == "9:16" and set(variant["ratios"]) == {"9:16", "1:1", "4:5", "16:9"}
    assert variant["skipped"] == {} and all(c["passed"] for c in variant["checks"])
    ads = {a["ratio"]: a for a in done["assets"] if a["kind"] == "ad"}
    assert set(ads) == set(variant["ratios"])
    counts = {k: sum(a["kind"] == k for a in done["assets"]) for k in ("cover", "still", "carousel")}
    assert counts == {"cover": 1, "still": 3, "carousel": 4}
    assert done["spend"]["eur"] > 0 and done["spend"]["eur"] <= done["cost_cap"]["eur"]

    path = httpx.URL(ads["9:16"]["url"])
    got = client.get(path.path, params=dict(path.params))
    assert got.status_code == 200 and got.headers["content-type"] == "video/mp4"
    assert got.content[4:8] == b"ftyp"  # an MP4 container


def test_the_reference_image_uses_the_master_ratio(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "aspect_ratio": "4:5"}).json()
    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    image_req = next(r for r in ctx.media.submits if r.kind == "image")
    assert image_req.arguments["aspect_ratio"] == "4:5"
    assert image_req.image_field == "image_urls"


def test_a_second_browser_cannot_open_the_job(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    other = new_session()
    assert client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": other}).status_code == 404
    assert approve(client, other, job["id"]).status_code == 404
    assert client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).status_code == 200
    assert client.get(f"/jobs/{job['id']}").status_code == 400  # no session at all


def test_an_asset_url_stops_working_after_it_expires(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    upload = next(a for a in job["assets"] if a["kind"] == "upload")
    url = httpx.URL(upload["url"])
    assert client.get(url.path, params=dict(url.params)).status_code == 200
    real_clock = ctx.storage._clock
    ctx.storage._clock = lambda: real_clock() + upload["expires_in_s"] + 1
    try:
        assert client.get(url.path, params=dict(url.params)).status_code == 403
    finally:
        ctx.storage._clock = real_clock
    tampered = dict(url.params) | {"sig": "0" * 64}
    assert client.get(url.path, params=tampered).status_code == 403


def test_double_clicked_approve_creates_one_job(client, ctx, session_id, photo_bytes):
    """Guardrail (M1): a double-clicked or retried Approve creates exactly one job row."""
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    first = approve(client, session_id, job["id"])
    second = approve(client, session_id, job["id"])
    assert first.status_code == second.status_code == 202
    with ctx.db.tx() as c:
        rows = c.execute("select count(*) as n from jobs").fetchone()["n"]
        scenes = c.execute("select count(*) as n from scenes where job_id = %s", (job["id"],)).fetchone()["n"]
    assert rows == 1 and scenes == 3
    assert worker.run_once(ctx) is True
    assert worker.run_once(ctx) is False  # only one job was ever queued
    assert [r.kind for r in ctx.media.submits] == ["image"] * 3  # step 1 only
    # "Make the video", double-clicked: one more run, one clip per scene, once.
    assert make_video(client, session_id, job["id"]).status_code == 202
    assert make_video(client, session_id, job["id"]).status_code == 202
    assert worker.run_once(ctx) is True
    assert worker.run_once(ctx) is False
    assert len([r for r in ctx.media.submits if r.kind == "video"]) == 3


def test_storyboard_is_editable_until_approved(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    board["scenes"][0]["voiceover"] = "Edited hook line."
    r = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers={"X-Session-Id": session_id})
    assert r.status_code == 200 and r.json()["storyboard"]["scenes"][0]["voiceover"] == "Edited hook line."
    approve(client, session_id, job["id"])
    r = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers={"X-Session-Id": session_id})
    assert r.status_code == 409


def test_access_code_gate(client, ctx, session_id, photo_bytes):
    ctx.settings = ctx.settings.model_copy(update={"access_codes": "letmein-2026"})
    assert create_job(client, session_id, photo_bytes).status_code == 403
    assert create_job(client, session_id, photo_bytes, code="wrong").status_code == 403
    r = create_job(client, session_id, photo_bytes, code="letmein-2026")
    assert r.status_code == 201
    assert approve(client, session_id, r.json()["id"]).status_code == 403
    assert approve(client, session_id, r.json()["id"], code="letmein-2026").status_code == 202
    assert client.post("/access/check", json={"code": "letmein-2026"}).json() == {"ok": True}


def test_production_fails_closed_without_codes(client, ctx, session_id, photo_bytes):
    ctx.settings = ctx.settings.model_copy(update={"app_env": "prod", "access_codes": ""})
    assert create_job(client, session_id, photo_bytes, code="anything").status_code == 403


def test_bad_uploads_and_briefs_are_rejected(client, session_id, photo_bytes):
    r = client.post(
        "/jobs",
        data={"brief": "{}"},
        files={"photo": ("p.jpg", photo_bytes, "image/jpeg")},
        headers={"X-Session-Id": session_id},
    )
    assert r.status_code == 422
    r = client.post(
        "/jobs",
        data={"brief": json.dumps(BRIEF)},
        files={"photo": ("p.jpg", b"not an image", "image/jpeg")},
        headers={"X-Session-Id": session_id},
    )
    assert r.status_code == 422 and "image" in r.json()["detail"]


def test_health_and_config_work(client):
    assert client.get("/health").json()["status"] == "ok"
    cfg = client.get("/config").json()
    assert cfg["currency"] == "EUR" and cfg["job_cost_cap"]["eur"] == 5.0  # D31: a safety limit, quality first
    assert 0 < cfg["job_estimate"]["eur"] < cfg["job_cost_cap"]["eur"]
    assert client.get("/health/db").json() == {"status": "ok"}
