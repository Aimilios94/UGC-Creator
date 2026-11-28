"""History and cost per stage (M2 item 4): this browser's ads only, with what each step cost."""

from __future__ import annotations

import pytest

from app import worker
from conftest import BRIEF, new_session
from helpers import approve, create_job


def test_history_lists_only_this_browsers_ads_newest_first(client, session_id, photo_bytes):
    first = create_job(client, session_id, photo_bytes, brief={**BRIEF, "product_name": "First"}).json()
    second = create_job(client, session_id, photo_bytes, brief={**BRIEF, "product_name": "Second"}).json()
    other = new_session()
    create_job(client, other, photo_bytes, brief={**BRIEF, "product_name": "Not mine"})

    rows = client.get("/jobs", headers={"X-Session-Id": session_id}).json()
    assert [r["id"] for r in rows] == [second["id"], first["id"]]
    assert [r["product_name"] for r in rows] == ["Second", "First"]
    assert rows[0]["status"] == "draft" and rows[0]["picture_url"]  # the product photo until a picture exists
    assert rows[0]["cost"]["eur"] == pytest.approx(rows[0]["cost"]["usd"] * 0.91, abs=1e-4)
    assert len(client.get("/jobs", headers={"X-Session-Id": other}).json()) == 1


def test_history_needs_a_session(client):
    assert client.get("/jobs").status_code in (400, 401, 422)


def test_cost_per_stage_adds_up_to_what_was_spent(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    assert approve(client, session_id, job["id"]).status_code == 202
    assert worker.run_once(ctx) is True  # the mock makes the starting pictures (priced like real ones)

    view = client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).json()
    stages = {s["stage"]: s for s in view["stage_costs"]}
    assert stages["image"]["label"] == "Starting pictures" and stages["image"]["cost"]["usd"] > 0
    assert "other" not in stages  # every call belongs to a step
    total = sum(s["cost"]["usd"] for s in view["stage_costs"])
    assert total == pytest.approx(view["spend"]["usd"], abs=1e-6)

    row = next(r for r in client.get("/jobs", headers={"X-Session-Id": session_id}).json() if r["id"] == job["id"])
    assert row["cost"]["usd"] == pytest.approx(view["spend"]["usd"], abs=1e-6)
    pictures = {a["url"].split("?")[0] for a in view["assets"] if a["kind"] == "image"}
    assert row["picture_url"].split("?")[0] in pictures  # a starting picture now, not the product photo
