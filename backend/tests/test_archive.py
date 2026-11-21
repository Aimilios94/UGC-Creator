"""The findings archive (D31): every local test ad is kept with what went in, the exact text each
AI got, what came out and the frames at every cut. Off unless ARCHIVE_DIR is set."""

from __future__ import annotations

import json

from app import worker
from app.models import Brief, Scene, Storyboard
from app.services.archive import archive_job
from app.services.pipeline import clip_texts
from helpers import create_job, to_video


def test_a_finished_ad_is_archived_with_inputs_prompts_outputs_and_cut_frames(
    client, ctx, session_id, photo_bytes, tmp_path
):
    ctx.settings.archive_dir = str(tmp_path / "archive")
    job = create_job(client, session_id, photo_bytes).json()
    to_video(client, ctx, session_id, job["id"])  # the images run is archived too
    folders = list((tmp_path / "archive").glob(f"*_{job['id'][:8]}"))
    assert len(folders) == 1 and (folders[0] / "notes.md").exists()
    out = folders[0]
    (out / "notes.md").write_text("my notes", encoding="utf-8")

    worker.run_once(ctx)  # the video run refreshes the same folder
    assert [p.name for p in (tmp_path / "archive").iterdir() if p.is_dir()] == [out.name]
    assert (out / "notes.md").read_text(encoding="utf-8") == "my notes"  # the owner's notes are kept
    assert (out / "input" / "photo.jpg").read_bytes()
    assert json.loads((out / "input" / "brief.json").read_text(encoding="utf-8"))["product_name"]

    board = Storyboard.model_validate(json.loads((out / "storyboard.json").read_text(encoding="utf-8")))
    full = client.get(f"/jobs/{job['id']}", headers={"X-Session-Id": session_id}).json()
    brief = Brief.model_validate(full["brief"])
    scenes = board.model_copy(update={"scenes": [Scene.model_validate(s) for s in board.scenes]})
    expected = clip_texts(ctx.settings, scenes, brief)
    clips = [r for r in ctx.media.submits if r.kind == "video"]
    for i, sent in enumerate(clips):
        saved = (out / "prompts" / f"clip_{i + 1}.txt").read_text(encoding="utf-8")
        assert saved.endswith(sent.arguments["prompt"]) and expected[i].text == sent.arguments["prompt"]
        assert "(as sent)" in saved.splitlines()[0]
    picture = next(r for r in ctx.media.submits if r.kind == "image")
    assert (out / "prompts" / "picture_1.txt").read_text(encoding="utf-8") == picture.arguments["prompt"]
    assert (out / "prompts" / "negative.txt").read_text(encoding="utf-8") == clips[0].arguments["negative_prompt"]

    names = {p.name for p in (out / "outputs").iterdir()}
    assert "variant-A_ad_9x16.mp4" in names and "upload.jpg" in names
    assert {"scene-0_video.mp4", "scene-1_video.mp4", "scene-2_video.mp4", "scene-0_image.jpg"} <= names
    assert sorted(p.name for p in (out / "frames").iterdir()) == [
        "cut_1_after.jpg", "cut_1_before.jpg", "cut_2_after.jpg", "cut_2_before.jpg",
    ]  # fmt: skip
    run = json.loads((out / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "done" and run["cost_eur"] > 0
    assert run["models_used"]["video"] == [f"mock: {ctx.settings.video_model}"]  # what the ad used, not today's setting
    assert {s["stage"] for s in run["stages"]} >= {"storyboard", "continuity", "image", "video", "compose"}


def test_the_archive_is_off_by_default_and_never_fails_a_job(client, ctx, session_id, photo_bytes, tmp_path):
    assert ctx.settings.archive_dir == ""
    job = create_job(client, session_id, photo_bytes).json()
    assert archive_job(ctx, job["id"]) is None
    ctx.settings.archive_dir = str(tmp_path / "file")
    (tmp_path / "file").write_text("not a folder", encoding="utf-8")
    assert archive_job(ctx, job["id"]) is None  # logged, not raised
