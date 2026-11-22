"""The user's choices on the Storyboard step (D27): own story, own scene images, clip length,
hook choice, visual style, and the two steps (images, then video)."""

from __future__ import annotations

import io

from PIL import Image

from app import worker
from app.services.video_gen import MAX_PROMPT
from conftest import BRIEF, new_session
from helpers import approve, create_job, make_video, separate_shots, to_video

STORY = (
    'My grandad played every Sunday in boots that slipped. He said "My boots never held me." '
    'Now the whole team wears Grip Socks Pro under their boots. "Not one slip all season," says the coach. '
    'Sunday morning, kit bag on the bench. "Grab a pair before Sunday with code KICK10."'
)
SHOT_LIST = (
    "Rainy night, 10-second timeline. 0:00 - 0:02 (Establish): handheld low-angle shot follows a man crossing "
    "a wet zebra crossing in a city at night, wearing the hoodie.\n"
    "0:02 - 0:06 (Detail): he lifts his hands into the rain, neon reflections on the wet fabric.\n"
    "0:06 - 0:10 (Closing): slow cinematic push-in on the back print, neon bokeh at the edges."
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
    assert lines[0] == "My boots never held me." and "KICK10" in lines[2]  # the spoken lines, word for word
    assert "grandad" in view["storyboard"]["scenes"][0]["description"]  # the scenes tell this story
    assert view["brief"]["story"] == STORY
    assert view["flags"] == []  # a claim from the user's own story counts as supplied
    with ctx.db.tx() as c:
        n = c.execute(
            "select count(*) as n from llm_calls where job_id = %s and kind = 'llm' and status = 'billed'", (job["id"],)
        ).fetchone()["n"]
    assert n == 7  # analyze, slots, storyboard, continuity, then slots, storyboard and continuity from the story
    approve(client, session_id, job["id"])
    late = client.post(f"/jobs/{job['id']}/story", json={"story": STORY}, headers=_h(session_id))
    assert late.status_code == 409


def test_a_too_short_story_is_refused(client, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    r = client.post(f"/jobs/{job['id']}/story", json={"story": "too short"}, headers=_h(session_id))
    assert r.status_code == 422


# --- own images -----------------------------------------------------------------------------------
def _upload_scene_image(client, session_id, job_id, idx, w, h):
    return client.post(
        f"/jobs/{job_id}/scenes/{idx}/image",
        files={"image": ("mine.png", _png(w, h), "image/png")},
        headers=_h(session_id),
    )


def test_an_uploaded_scene_image_close_to_the_ratio_is_cropped_free(client, ctx, session_id, photo_bytes):
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    before = job["estimate"]["images"]["eur"]
    r = _upload_scene_image(client, session_id, job["id"], 1, 1000, 1600)  # 5:8, a crop keeps 90%
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
        assert im.size == (1080, 1920)  # cropped to the 9:16 ad


def test_an_uploaded_scene_image_far_from_the_ratio_is_extended_not_blurred(client, ctx, session_id, photo_bytes):
    """A blurred fill was animated by Kling into every later scene (real test, 21 Nov 2026), so a
    picture a crop would cut too much is extended to the full frame by the image model (D31)."""
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    before = job["estimate"]["images"]["eur"]
    view = _upload_scene_image(client, session_id, job["id"], 1, 1600, 900).json()  # 16:9 into a 9:16 ad
    assert view["estimate"]["images"]["eur"] == before  # one picture's price: extended instead of generated

    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    assert [r.kind for r in ctx.media.submits] == ["image"] * 3
    extend = ctx.media.submits[1]
    assert extend.arguments["prompt"].startswith("This photo was placed in a frame")
    assert extend.arguments["aspect_ratio"] == "9:16"
    with Image.open(io.BytesIO(extend.input_image.data)) as im:
        assert im.size == (1080, 1920)  # the model gets the picture already placed at the ad's shape
    run = next(r for r in ctx_runs(ctx, job["id"]) if r["scene_idx"] == 1)
    assert run["output"]["fit"] == "extend" and run["output"]["own"] == "upload"


def ctx_runs(ctx, job_id):
    from app import repository as repo

    return [r for r in repo.list_stage_runs(ctx.db, job_id) if r["stage"] == "image"]


def test_the_product_photo_can_be_a_scene_image(client, ctx, session_id, photo_bytes):
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    board = job["storyboard"]
    board["scenes"][0]["image_source"] = "product"
    assert _put(client, session_id, job["id"], board).status_code == 200
    approve(client, session_id, job["id"])
    worker.run_once(ctx)
    # The 4:5 test photo would lose 30% in a 9:16 crop, so the image model extends it.
    assert len(ctx.media.submits) == 3
    assert ctx.media.submits[0].arguments["prompt"].startswith("This photo was placed in a frame")


def test_own_fit_crops_when_it_keeps_enough_else_extends():
    from app.services.pipeline import own_fit

    assert own_fit(1080, 1920, "9:16") == "crop"
    assert own_fit(1000, 1600, "9:16") == "crop"  # keeps 90%
    assert own_fit(800, 1000, "9:16") == "extend"  # keeps 70%
    assert own_fit(1600, 900, "9:16") == "extend"
    assert own_fit(1600, 900, "16:9") == "crop"
    assert own_fit(1000, 1000, "4:5") == "crop"  # keeps 80%


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
    ctx.settings.job_cost_cap_eur = 1.75  # the cap is a safety limit (5 EUR, D31); a low one shows the refusal
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    for s in board["scenes"]:
        s["duration_s"] = 10
    view = _put(client, session_id, job["id"], board).json()
    assert view["estimate"]["fits_cap"] is False  # 3 x 10 s is about 2 EUR, over this 1.75 EUR cap
    r = approve(client, session_id, job["id"])
    assert r.status_code == 409 and "cap" in r.json()["detail"]

    board["scenes"][2]["duration_s"] = 5
    view = _put(client, session_id, job["id"], board).json()
    assert view["estimate"]["fits_cap"] is True
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    clips = [r for r in ctx.media.submits if r.kind == "video"]
    assert [r.arguments["duration"] for r in clips] == ["10", "10", "5"]
    assert "Spread the beats evenly over 10 seconds" in clips[0].arguments["prompt"]
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


def test_a_shot_list_story_drives_the_visuals_and_the_scene_lengths(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": SHOT_LIST}).json()
    scenes = job["storyboard"]["scenes"]
    assert [s["duration_s"] for s in scenes] == [2, 4, 4]  # from the story's timestamps
    assert "zebra crossing" in scenes[0]["motion_prompt"] and "push-in on the back print" in scenes[2]["motion_prompt"]
    assert all(s["voiceover"] == "" for s in scenes)  # no spoken lines in a shot list
    assert {h["formula"] for h in job["storyboard"]["hooks"]} == {"pov", "problem_first", "three_reasons"}


def test_short_scenes_render_a_5_s_clip_and_are_cut_to_length(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    for s, length in zip(board["scenes"], (3, 7, 5), strict=True):
        s["duration_s"] = length
    view = client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id)).json()
    assert [s["duration_s"] for s in view["storyboard"]["scenes"]] == [3, 7, 5]
    bad = {**board, "scenes": [{**board["scenes"][0], "duration_s": 12}, *board["scenes"][1:]]}
    assert client.put(f"/jobs/{job['id']}/storyboard", json=bad, headers=_h(session_id)).status_code == 422
    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    clips = [r for r in ctx.media.submits if r.kind == "video"]
    assert [r.arguments["duration"] for r in clips] == ["5", "10", "5"]  # billed clip lengths
    assert "Only the first 3 seconds are used" in clips[0].arguments["prompt"]


def test_all_in_one_go_makes_images_and_video_without_stopping(client, ctx, session_id, photo_bytes):
    job = separate_shots(client, session_id, create_job(client, session_id, photo_bytes).json())
    r = client.post(f"/jobs/{job['id']}/approve", json={"mode": "video"}, headers=_h(session_id))
    assert r.status_code == 202 and r.json()["phase"] == "video"
    worker.run_once(ctx)
    done = client.get(f"/jobs/{job['id']}", headers=_h(session_id)).json()
    assert (done["status"], done["phase"]) == ("done", "video")
    assert [r.kind for r in ctx.media.submits] == ["image"] * 3 + ["video"] * 3
    assert done["variants"][0]["status"] == "done" and done["variants"][0]["ratios"]
