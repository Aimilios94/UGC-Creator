"""A long story (D30): kept whole up to 12,000 characters; every clip within Kling's 2,500 characters,
the scene's own text word for word and the notes cut down per scene; a scene too long on its own is
refused with a readable message until it is shortened (by hand or with "Shorten it for me")."""

from __future__ import annotations

from app import repository as repo
from app import worker
from app.services.video_gen import MAX_PROMPT
from conftest import BRIEF, new_session
from helpers import approve, create_job, to_video

NOTES = " ".join(
    [
        "Style, Continuity & Transition Rules: hyper-realistic live-action capture on a 35mm f/1.4 lens at 24 FPS"
        " with natural motion blur and subtle organic camera momentum.",
        "Male character: a young man in his mid-twenties with realistic unretouched skin, visible pores, light"
        " stubble, damp dark hair clumping at the temples, a calm expression and moist dark eyes.",
        "Female character: a woman in her mid-twenties on an upper balcony, thin black glasses catching cyan and"
        " magenta reflections, damp strands of dark hair, a quiet watchful expression.",
        "Setting: an empty city street at midnight in steady visible rain, puddles reflecting neon signs,"
        " overhead balconies, wet railings and urban mist.",
        "Lighting: high-contrast night grading in cold blues, cyans and magentas, crisp specular reflections on"
        " wet pavement, cyan and magenta rim light on the man and the white hoodie, a warm orange lighter flame.",
    ]
    * 5  # long notes, like the owner's styled prompt (about 4,500 characters)
)
BEAT = (
    "the camera glides forward behind the man at a steady pace with subtle handheld breathing, rain streaks"
    " falling and splashing on the asphalt, the white hoodie with natural cotton folds and damp shoulders,"
    " the back graphic crisp, the camera keeping its rear-gliding speed as he walks slowly on. "
)
LONG_STORY = (
    NOTES
    + "\n20-Second Continuous Timeline (5 Scenes x 4 Seconds):\n"
    + "\n".join(f"0:{4 * i:02d} - 0:{4 * i + 4:02d} | Scene {i + 1}: {BEAT * 3}" for i in range(5))
)


def _h(session_id: str) -> dict:
    return {"X-Session-Id": session_id}


def test_a_long_story_is_kept_whole_and_every_clip_fits(client, ctx, session_id, photo_bytes):
    assert 7000 < len(LONG_STORY) < 12000
    job = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": LONG_STORY}).json()
    assert job["brief"]["story"] == LONG_STORY.strip()  # nothing cut
    board = job["storyboard"]
    assert len(board["scenes"]) == 5 and len(board["notes"]) > 4000  # the notes stay whole
    clips = job["clips"]
    assert len(clips) == 5
    for scene, clip in zip(board["scenes"], clips, strict=True):
        assert clip["chars"] <= MAX_PROMPT and clip["too_long_by"] == 0
        assert scene["motion_prompt"] in clip["text"]  # the scene's own text, word for word
        assert clip["notes"] == "short" and scene["notes_short"]  # the notes, cut down for this scene

    to_video(client, ctx, session_id, job["id"])
    worker.run_once(ctx)
    sent = [r.arguments["prompt"] for r in ctx.media.submits if r.kind == "video"]
    assert sent == [c["text"] for c in clips]  # the preview is exactly what the video AI gets
    picture = next(r for r in ctx.media.submits if r.kind == "image")
    assert board["notes"] in picture.arguments["prompt"]  # the picture AI (50,000 characters) gets them all


def test_a_story_over_the_limit_is_refused_with_a_message(client, session_id, photo_bytes):
    r = create_job(client, session_id, photo_bytes, brief={**BRIEF, "story": "x " * 6001})
    assert r.status_code == 422
    job = create_job(client, session_id, photo_bytes).json()
    late = client.post(f"/jobs/{job['id']}/story", json={"story": "y " * 6001}, headers=_h(session_id))
    assert late.status_code == 422


def test_a_scene_too_long_on_its_own_is_refused_until_shortened(client, ctx, session_id, photo_bytes):
    job = create_job(client, session_id, photo_bytes).json()
    board = job["storyboard"]
    long_text = " ".join(f"Beat {k}: the camera keeps gliding forward slowly while the rain falls." for k in range(34))
    board["scenes"][1]["motion_prompt"] = long_text[:2400]
    board["scenes"][1]["duration_s"] = 4  # played faster ...
    board["scenes"][2]["image_source"] = "product"  # ... to end on the next picture: the most rules

    # The preview reflects the unsaved board; another session cannot use it.
    preview = client.post(f"/jobs/{job['id']}/clip-texts", json=board, headers=_h(session_id)).json()
    assert preview[1]["too_long_by"] > 0 and preview[0]["too_long_by"] == 0
    assert client.post(f"/jobs/{job['id']}/clip-texts", json=board, headers=_h(new_session())).status_code == 404

    assert client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id)).status_code == 200
    r = approve(client, session_id, job["id"])
    assert r.status_code == 409 and "scene 2 by" in r.json()["detail"] and "Shorten it for me" in r.json()["detail"]

    calls_before = len(repo.list_stage_runs(ctx.db, job["id"]))
    short = client.post(f"/jobs/{job['id']}/scenes/1/shorten", json=board, headers=_h(session_id))
    assert short.status_code == 200, short.text
    text = short.json()["text"]
    assert len(text) < len(board["scenes"][1]["motion_prompt"]) and text.startswith("Beat 0:")
    assert len(repo.list_stage_runs(ctx.db, job["id"])) == calls_before + 1  # one shorten stage, billed
    assert client.post(f"/jobs/{job['id']}/scenes/9/shorten", json=board, headers=_h(session_id)).status_code == 404

    board["scenes"][1]["motion_prompt"] = text
    assert client.put(f"/jobs/{job['id']}/storyboard", json=board, headers=_h(session_id)).status_code == 200
    assert approve(client, session_id, job["id"]).status_code == 202
    late = client.post(f"/jobs/{job['id']}/scenes/1/shorten", json=board, headers=_h(session_id))
    assert late.status_code == 409  # the scenes are fixed while the pictures are made


def test_a_moment_inside_a_scene_does_not_make_a_new_scene():
    from app.services.story_beats import story_beats

    story = (
        "0:00 - 0:04 | Scene 1: he walks on. Around 0:02-0:04, still walking, he flicks the lighter open.\n"
        "0:04 - 0:08 | Scene 2: he lights it. Around 0:06 - 0:08 he looks up to the balcony.\n"
        "0:08 - 0:12 | Scene 3: he pulls the hood up."
    )
    beats = story_beats(story)
    assert [b.seconds for b in beats] == [4, 4, 4]  # not 6 s: the inner range is a moment of the scene
    assert "flicks the lighter" in beats[0].text and "looks up" in beats[1].text
