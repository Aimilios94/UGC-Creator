"""Small helpers shared by the API tests."""

from __future__ import annotations

import json

from conftest import BRIEF


def create_job(
    client,
    session_id: str,
    photo: bytes,
    brief: dict | None = None,
    code: str | None = None,
    extra: dict | None = None,
):
    headers = {"X-Session-Id": session_id}
    if code is not None:
        headers["X-Access-Code"] = code
    return client.post(
        "/jobs",
        data={"brief": json.dumps(brief or BRIEF), **(extra or {})},
        files={"photo": ("product.jpg", photo, "image/jpeg")},
        headers=headers,
    )


def approve(client, session_id: str, job_id: str, code: str | None = None):
    headers = {"X-Session-Id": session_id}
    if code is not None:
        headers["X-Access-Code"] = code
    return client.post(f"/jobs/{job_id}/approve", headers=headers)


def make_video(client, session_id: str, job_id: str, board: dict | None = None, code: str | None = None):
    headers = {"X-Session-Id": session_id}
    if code is not None:
        headers["X-Access-Code"] = code
    return client.post(f"/jobs/{job_id}/video", json=board, headers=headers)


def to_video(client, ctx, session_id: str, job_id: str) -> None:
    """Step 1 (approve, the worker makes the images), then step 2 queued: the next worker run makes the video."""
    from app import worker

    assert approve(client, session_id, job_id).status_code == 202
    assert worker.run_once(ctx) is True
    r = make_video(client, session_id, job_id)
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "queued" and r.json()["phase"] == "video"
