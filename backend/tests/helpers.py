"""Small helpers shared by the API tests."""

from __future__ import annotations

import json

from conftest import BRIEF


def create_job(client, session_id: str, photo: bytes, brief: dict | None = None, code: str | None = None):
    headers = {"X-Session-Id": session_id}
    if code is not None:
        headers["X-Access-Code"] = code
    return client.post(
        "/jobs",
        data={"brief": json.dumps(brief or BRIEF)},
        files={"photo": ("product.jpg", photo, "image/jpeg")},
        headers=headers,
    )


def approve(client, session_id: str, job_id: str, code: str | None = None):
    headers = {"X-Session-Id": session_id}
    if code is not None:
        headers["X-Access-Code"] = code
    return client.post(f"/jobs/{job_id}/approve", headers=headers)
