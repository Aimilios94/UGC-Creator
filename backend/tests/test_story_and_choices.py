"""The user's choices on the Storyboard step (D27): own story, own scene images, clip length,
hook choice, visual style, and the two steps (images, then video)."""

from __future__ import annotations

import io

from PIL import Image

from app import worker
from app.services.video_gen import MAX_PROMPT
from conftest import BRIEF, new_session
from helpers import approve, create_job, make_video, to_video

STORY = (
    "My grandad played every Sunday in boots that slipped. "
    "Now the whole team wears Grip Socks Pro under their boots. "
    "Grab a pair before Sunday with code KICK10."
)


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def _png(w: int, h: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 160, 90)).save(buf, "PNG")
    return buf.getvalue()


def _put(client, session_id, job_id, board):
    return client.put(f"/jobs/{job_id}/storyboard", json=board, headers=_h(session_id))


# --- own story ------------------------------------------------------------------------------
def test_my_own_story_rewrites_the_storyboard_keeping_my_lines(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    r = client.post(f"/jobs/{job['id']}/story", json={"story": STORY}, headers=_h(session_id))
    assert r.status_code == 200, r.text
    view = r.json()
    lines = [s["voiceover"] for s in view["storyboard"]["scenes"]]
    assert lines[0].startswith("My grandad played") and "KICK10" in lines[2]
    assert view["brief"]["story"] == STORY
    assert view["flags"] == []  # a claim from the user's own story counts as supplied
    with ctx.db.tx() as c:
        n = c.execute(
            "select count(*) as n from llm_calls where job_id = %s and kind = 'llm' and status = 'billed'", (job["id"],)
        ).fetchone()["n"]
    assert n == 3  # analyze, storyboard, storyboard from the story
    approve(client, session_id, job["id"])
    late = client.post(f"/jobs/{job['id']}/story", json={"story": STORY}, headers=_h(session_id))
    assert late.status_code == 409


def test_a_too_short_story_is_refused(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    r = client.post(f"/jobs/{job['id']}/story", json={"story": "too short"}, headers=_h(session_id))
    assert r.status_code == 422


# --- own images -----------------------------------------------------------------------------------
def test_an_uploaded_scene_image_is_used_free_and_fitted_to_the_ratio(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    before = job["estimate"]["images"]["eur"]
    r = client.post(
        f"/jobs/{job['id']}/scenes/1/image",
        files={"image": ("mine.png", _png(1600, 900), "image/png")},
        headers=_h(session_id),
    )
    assert r.status_code == 200, r.text
    view = r.json()
    scene = view["storyboard"]["scenes"][1]
    assert scene["image_source"] == "upload" and scene["image_upload_key"] is None  # the key stays on the server
    assert view["estimate"]["images"]["eur"] < before
    assert any(a["kind"] == "upload" and a["scene_idx"] == 1 for a in view["assets"])

    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    assert [r.kind for r in ctx.media.submits] == ["image", "image"]  # scenes 1 and 3 only
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    own = next(a for a in done["assets"] if a["kind"] == "image" and a["scene_idx"] == 1)
    got = client.get(own["url"].replace("http://testserver", ""))
    with Image.open(io.BytesIO(got.content)) as im:
        assert im.size == (1080, 1920)  # a 16:9 photo fitted to the 9:16 ad (blurred fill)


def test_the_product_photo_can_be_a_scene_image(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    board["scenes"][0]["image_source"] = "product"
    assert _put(client, session_id, job["id"], board).status_code == 200
    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    assert len(ctx.media.submits) == 2


def test_the_browser_cannot_point_a_scene_at_another_file(client, ctx, session_id, photo_bytes):
    victim = create_job(client, new_session(), photo_bytes).json()
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    board["scenes"][0]["image_source"] = "upload"
    board["scenes"][0]["image_upload_key"] = f"jobs/{victim['id']}/upload.jpg"
    r = _put(client, session_id, job["id"], board)
    assert r.status_code == 422  # the injected key is ignored, so there is no upload for that scene
    with ctx.db.tx() as c:
        stored = c.execute("select storyboard from jobs where id = %s", (job["id"],)).fetchone()["storyboard"]
    assert stored["scenes"][0]["image_upload_key"] is None


# --- clip length, cap and hook ------------------------------------------------------------------
def test_ten_second_clips_and_the_cap(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    for s in board["scenes"]:
        s["duration_s"] = 10
    view = _put(client, session_id, job["id"], board).json()
    assert view["estimate"]["fits_cap"] is False  # 3 x 10 s is about 1.93 EUR, over the 1.75 EUR cap
    r = approve(client, session_id, job["id"])
    assert r.status_code == 409 and "cap" in r.json()["detail"]

    board["scenes"][2]["duration_s"] = 5
    view = _put(client, session_id, job["id"], board).json()
    assert view["estimate"]["fits_cap"] is True
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    clips = [r for r in ctx.media.submits if r.kind == "video"]
    assert [r.arguments["duration"] for r in clips] == ["10", "10", "5"]
    assert "spread these beats evenly over the 10 seconds" in clips[0].arguments["prompt"]
    assert all(len(r.arguments["prompt"]) <= MAX_PROMPT for r in clips)


def test_the_chosen_hook_becomes_variant_a(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    board["hook_choice"] = 2
    board["scenes"][0]["voiceover"] = board["hooks"][2]["text"]
    _put(client, session_id, job["id"], board)
    view = approve(client, session_id, job["id"]).json()
    assert view["variants"][0]["hook_idx"] == 2


# --- step 2 edits and the visual style ------------------------------------------------------------
def test_video_step_takes_text_and_motion_edits_but_not_image_changes(client, ctx, session_id, photo_bytes):
    brief = {**BRIEF, "visual_style": "3d"}
    job = create_job(client, session_id, photo_bytes, brief=brief).json()
    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    image_prompts = [r.arguments["prompt"] for r in ctx.media.submits]
    assert all("Stylised 3D render" in p for p in image_prompts)

    view = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    board = view["storyboard"]
    board["scenes"][0]["voiceover"] = "Your boots, finally locked in."
    board["scenes"][0]["motion_prompt"] = "0-5 s: slow orbit around the socks, warm light."
    board["scenes"][0]["image_prompt"] = "something else entirely"
    board["scenes"][0]["image_source"] = "product"
    r = make_video(client, session_id, job["id"], board)
    assert r.status_code == 202, r.text
    scene = r.json()["storyboard"]["scenes"][0]
    assert scene["voiceover"] == "Your boots, finally locked in."
    assert scene["image_prompt"] != "something else entirely" and scene["image_source"] == "generate"
    worker.run_once(ctx)
    clip = next(r for r in ctx.media.submits if r.kind == "video")
    assert clip.arguments["prompt"].startswith("0-5 s: slow orbit") and "3D animation" in clip.arguments["prompt"]
    assert "letters" in clip.arguments["negative_prompt"]  # no made-up lettering
    assert ctx.voice.requests[0].text == "Your boots, finally locked in."


def test_make_the_video_needs_the_images_first_and_is_idempotent(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    assert make_video(client, session_id, job["id"]).status_code == 409  # still a draft
    to_video(client, ctx, session_id, job["id"])
    again = make_video(client, session_id, job["id"])
    assert again.status_code == 202 and again.json()["phase"] == "video"
    assert make_video(client, new_session(), job["id"]).status_code == 404
